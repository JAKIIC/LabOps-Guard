# POLAR-AUDIT-001-R3 — Polar 码竞赛 baseline 只读代码结构与可复现性审计

- **任务类型**：一次性只读覆盖（代码结构与可复现性证据提取）
- **审计员**：researcher（仅证据提取；不判断最终根因、不提出优化方案）
- **快照**：`shared/tasks/POLAR-AUDIT-001/attempt-R1/project_snapshot_lite/`（13 个允许文件）
- **核验**：`shared/tasks/POLAR-AUDIT-001/attempt-R2/snapshot_verification.json` = **VERIFIED**（13/13 SHA-256 一致）
- **范围**：仅 13 个允许文件；排除数据（CSV/标签/模型/密钥）一律未读取

---

## 1. 审计范围与文件清单（13 个允许文件，不含 manifest.json）

| 路径 | 类型 | 角色 |
|------|------|------|
| `README.md` | 文档 | 顶层说明：运行方式、参考 BER、抽样校准 + OSD-2 |
| `baseline.py` | Python | **主可执行 baseline**（OSD-2 译码器 + 信道校准） |
| `baseline/baseline/README.md` | 文档 | 数据集说明（字段、结构、私有标签说明） |
| `baseline/baseline/participant_pipeline_cnn_mlp.ipynb` | Notebook | 参考参与者流水线（CNN+MLP 残差译码器） |
| `baseline/baseline/Codes_DB/*.txt`（7 个） | 数据 | 校验矩阵码表（POLAR×3 + BCH×4） |
| `public_test/README_数据说明.md` | 文档 | 公开测试输入说明 |
| `submit_sample/README_提交说明.md` | 文档 | 提交格式与评测约束 |

> 说明：manifest.json 为清单元数据（非允许文件），仅用于核对 13 个允许文件清单，未将其作为审计对象。

---

## 2. 程序入口

### 2.1 CLI baseline（主入口）
- **`baseline.py` → `main()`（L246）**，由 `if __name__ == "__main__": main()`（L298）触发。
- 命令示例（README.md）：
  - `python baseline.py --max-rows 100 --output submission_debug.csv`（校准+验证+前 100 行）
  - `python baseline.py --reuse-calibration --output submission.csv`（复用校准，生成完整提交）

### 2.2 Notebook 参考流水线
- **`participant_pipeline_cnn_mlp.ipynb`，入口 Cell 1**（imports），全流程从 Cell 1 顺序执行至 Cell 9。

---

## 3. 模型结构与数据流

### 3.1 baseline.py（OSD-2，非神经网络）
流程：
1. **加载校验矩阵**：`load_parity_matrix`（L41）从 `baseline.zip` 内 `baseline/Codes_DB/POLAR_N64_K32.txt` 读取 32×64 校验矩阵（或 `--matrix` 直读），校验 shape==(32,64)。
2. **派生生成矩阵**：`rref_binary`（L53，GF(2) 行化简）+ `generator_from_parity`（L73）。
3. **信道校准**（除非 `--reuse-calibration`）：`discover_training_pair`（L84）定位配对 shard → `load_training_sample`（L95，seed=42 抽样 10000 校准 + 2000 验证）→ `fit_channel`（L112，估计每 bit 的 mean0/mean1/variance/prior）→ `validate_and_select`（L205，在验证集按 BER 选 raw 或 calibrated LLR 模式）→ `save_calibration`（L228，存 `channel_calibration.npz`）。
4. **推理**：`open_test_source`（L239）读 `public_test.zip` 或 `--test-csv` → 分块 `calibrated_llr`（L132，若 calibrated 模式）→ `osd_decode`（L196）→ 组装 `submission.csv`。

OSD 核心：`make_flip_patterns`（L143）+ `osd_decode_one`（L150），对每条样本动态构造最可靠信息基（MRB），枚举少量低可靠 bit 翻转取最大似然合法码字。默认 `--list-size 10 --order 2`。

### 3.2 Notebook（CNN+MLP 残差译码器）
- **模型 `ResidualDecoder`（Cell 6）**：输入 hard-decision bits + LLR + syndrome（由 `H_tensor` 计算，`H_tensor` 来自 POLAR_N64_K32 校验矩阵，Cell 5）。
  - `conv_feat` Conv1d(2,64,1) → `syn_dense` Linear(32,64) → `conv_combined` Conv1d(65,64,1) → `ResidualBlock1d(64)`（含 SeparableConv1d×2 + BN + ReLU，残差连接）→ `fc`（64*64→1024→1024→64）。
- **损失/优化器（Cell 6）**：BCEWithLogitsLoss，Adam lr=1e-3。
- **数据（Cell 3-4）**：枚举 `competition_data/train_codeword_x_shard_*.csv` 与 `train_noisy_y_shard_*.csv`；`SingleShardByIdDataset` 以 `id % 20 == 0`（VAL_MOD=20, VAL_REM=0）划分 train/val。
- **训练（Cell 8）**：BATCH_SIZE=512，EPOCHS=min(200, shards)，PATIENCE=50 早停，保存 `best_participant_residual_decoder.pt`。
- **推理（Cell 9）**：加载最优 checkpoint，对公开测试推理，写出 `submission_residual_decoder.csv`。

---

## 4. 指标计算流程
- **baseline.py**：`validate_and_select`（L205）计算 hard / raw OSD / calibrated OSD 三种 BER（`np.mean((received<0)!=truth)` 等），取 min 选模式。评测指标为 **BER，越低越好**（submit_sample/README、baseline/baseline/README）。
- **Notebook**：`ber_from_logits`（Cell 7）由 `sigmoid(logits)>0.5` 得翻转预测，`predicted_x = hd_bits ^ flip_pred`，与 `original_x` 比较得 BER。

---

## 5. 可复现性评估

### 已具备（strong 证据）
- 抽样用固定 seed（baseline.py `--seed 42` L37/L95；notebook `set_seed(42)` Cell 2）。
- 校准结果可持久化并可复用（`channel_calibration.npz`，`--reuse-calibration`）。
- 模型 checkpoint 可保存/加载（notebook Cell 8/9）。
- 提交格式与评测约束有明确文档（submit_sample/README、baseline/baseline/README）。
- 校验矩阵源码表随快照提供（`Codes_DB/POLAR_N64_K32.txt` 等 7 个）。

### 缺口（missing / weak 证据，详见 evidence_gaps.json）
- **无 requirements.txt / 依赖版本锁定**（GAP-001）——数值结果复现无法仅凭快照保证。
- **训练 shard / 测试输入 / zip 归档缺失**（GAP-002/003/004）——排除数据未读取，抽样依赖的 BER 无法复现。
- **预计算校准 npz / 预训练 checkpoint 缺失**（GAP-005/006）——`--reuse-calibration` 与 notebook 推理需先运行生成。
- **README 参考 BER（0.055/0.013/0.01272）仅文档值，未独立复现**（GAP-007）；且抽样具随机性。
- **无运行脚本/编排，报告所用精确命令史未记录**（GAP-008）。
- **私有测试标签（test_codeword_x_private.csv）按设计不提供**（GAP-009）。
- **CUDA/设备未锁定，notebook 数值可能随设备变化**（GAP-010）。

---

## 6. 结论（证据层面，不判根因）
- 快照包含**两条可执行路径**：`baseline.py`（OSD-2 经典译码）与参考 notebook（CNN+MLP 残差译码）。
- 两者均以 `POLAR_N64_K32` 校验矩阵为代码基础，输出 `id,bit_0..bit_63` 提交格式，评测指标 BER。
- **结构层面证据充分（strong）**；**端到端数值复现所需的外部数据与依赖锁定在快照中缺失（missing）**，无法仅凭快照独立复现文档所报 BER。
- 所有不确定项已如实记入 `evidence_gaps.json`，未作猜测。
