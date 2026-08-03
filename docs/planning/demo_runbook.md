# LabOps Guard — Polar-baseline 本地优先 MVP 演示 Runbook（demo_runbook.md）

- **任务**：LABOPS-MVP-PLAN-001
- **性质**：规划/规格产出（不写代码、不训练、不测试、不安装依赖、不联网）
- **核心原则**：无证据不诊断，无审批不执行，无验证不闭环
- **演示约束**：只展示**缺失证据识别**与**审批闭环**；**不得伪造故障**、**不得读取比赛测试标签/排除数据**。

---

## 1. 演示目标

用 polar-baseline 的**真实 evidence gaps**（evidence_gaps.json 的 10 项 GAP）走通一条
"快照登记 → 证据采集 → 诊断候选 → 人工审批 → 受控动作（demo）→ 验证闭环"的完整链路，
向评审展示 LabOps Guard 的**默认安全、证据驱动、可审计、可复现**能力。

> 演示中所有安装/下载/训练动作均为 **SIMULATED 适配器**（记录预期效果，不真实执行外部/风险动作）。
> 读文件、算哈希、规则分类为 **REAL**。全程不读取排除数据、不伪造故障。

---

## 2. 前置输入（已核验）

| 输入 | 来源 | 状态 |
|------|------|------|
| 13 个允许文件 | `project_snapshot_lite/` | 已核验（snapshot_verification.json = VERIFIED） |
| repository_map.json | POLAR-AUDIT-001-R3 | 已验收 |
| execution_contract.json | POLAR-AUDIT-001-R3 | 已验收 |
| evidence_index.json | POLAR-AUDIT-001-R3 | 已验收 |
| evidence_gaps.json | POLAR-AUDIT-001-R3 | 已验收（10 项 GAP） |
| baseline_audit.md | POLAR-AUDIT-001-R3 | 已验收 |
| approval_policy.json / incident_contract.json / architecture.json | 本任务 | 待实现 |

---

## 3. 演示步骤

### Step 0 — 初始化
```
labops init --project polar-baseline --snapshot project_snapshot_lite/
```
- 登记 13 个允许文件 + SHA-256，与 `snapshot_verification.json`（VERIFIED）比对。
- 记录运行契约（来自 execution_contract.json：OSD-2 / POLAR_N64_K32 / BER 指标）。
- 写入 append-only trace。
- **预期**：`registry_record.json` 生成；13/13 哈希一致；trace 追加。

### Step 1 — 证据采集
```
labops evidence collect --project polar-baseline
```
- 加载 evidence_index（22 项：17 strong / 2 weak / 3 missing）与 evidence_gaps（10 项）。
- 重新确认 strong 证据引用（文件+行/cell）；缺失项标记 MISSING/UNKNOWN。
- **绝不访问排除数据**（训练/测试 CSV、私有标签、密钥）。
- **预期**：`collected_evidence.json`；排除数据访问次数 = 0。

### Step 2 — 诊断候选（无证据不诊断）
```
labops diagnose --project polar-baseline
```
- 将 10 项 GAP 转为诊断候选，**每项必须引用 evidence_id**。
- 无证据项输出 **BLOCKED / UNKNOWN**，**绝不把缺失证据猜成事实**。

**10 项 GAP 的演示分类（源自 evidence_gaps.json，非伪造）：**

| GAP | 类别 | 演示状态 | 说明 |
|-----|------|---------|------|
| GAP-001 无 requirements/依赖锁定 | environment | BLOCKED（须审批） | 缺依赖版本，无法锁定复现环境 |
| GAP-002 训练 shard 缺失 | data | BLOCKED（须审批） | 缺训练数据，无法复现抽样依赖的 BER |
| GAP-003 测试输入缺失 | data | BLOCKED（须审批） | 缺 test csv，无法生成提交 |
| GAP-004 baseline.zip/public_test.zip 缺失 | data | BLOCKED（须审批） | 缺归档；矩阵仅解包可用 |
| GAP-005 channel_calibration.npz 缺失 | artifact | BLOCKED（须审批） | 需先运行校准生成 |
| GAP-006 模型 checkpoint 缺失 | artifact | BLOCKED（须审批） | 需先训练生成 |
| GAP-007 文档 BER 不可独立复现 | runtime | **UNKNOWN** | README 值非事实，不可断言 |
| GAP-008 无运行脚本/编排 | config | BLOCKED（须审批） | 精确命令史未记录 |
| GAP-009 私有测试标签缺失 | data | **FORBIDDEN** | 按设计不读取/不请求 |
| GAP-010 CUDA/设备未锁定 | environment | UNKNOWN/BLOCKED | 设备相关数值可能变化 |

- **预期**：`diagnosis_candidates.json`；10 项全部有 evidence_id；无一条臆造结论。

### Step 3 — 审批闭环（无审批不执行）
```
labops approve list --project polar-baseline
labops approve review --id A-003 --decision approve|reject
```
- **read_only_auto**（哈希、读允许文件、生成记录）：自动执行，仅记 trace。
- **manual_approval**（安装依赖、下载 zip、生成校准/checkpoint、写输出文件）：发出审批请求，dry-run 先行，须人工 approve/reject。
- **forbidden**（读私有标签等）：**即使批准也拒绝执行**。
- 拒绝 / 超时 / 挂起均为一等状态。
- **预期**：`approval_requests.json` + `approval_decisions.json`；拒绝/超时可见；forbidden 动作被强制拦截。

### Step 4 — 受控动作（SIMULATED，演示模式）
```
labops run --id A-003 --demo
```
- 默认 dry-run 先行；命令白名单；工作目录边界；超时；输出截断 + 脱敏。
- 演示中 `pip install` / 下载 zip / 训练均为 **SIMULATED**（记录"将安装 X / 将下载 Y / 将训练并产出 checkpoint"，不真实执行）。
- 良性文件/哈希操作 **REAL**。
- **预期**：`execution_result.json`；status ∈ {DRY_RUN, SUCCEEDED, FAILED, TIMEOUT, FORBIDDEN, SKIPPED}。

### Step 5 — 验证闭环（无验证不闭环）
```
labops verify --id A-003
```
- 动作后检查：退出码、产物存在性、哈希匹配。
- 仅 **PASSED** 才关闭 incident；FAILED/PARTIAL/NOT_VERIFIED 保持 BLOCKED。
- **预期**：`verification_result.json`；closure 规则强制（无 PASSED 不关闭，除非显式 REJECTED/UNVERIFIED 留痕）。

### Step 6 — 审计与可复现
```
labops trace dump --project polar-baseline
```
- 输出 append-only、哈希链完整的 trace；展示每一步决策、审批、验证。
- 输入快照哈希 + 运行契约 + 配置均可追溯。
- **预期**：`trace.log` 完整、链式校验通过。

---

## 4. 演示验收清单

- [ ] 13 个允许文件哈希与 VERIFIED 一致
- [ ] 10 项 GAP 全部以 BLOCKED/UNKNOWN/FORBIDDEN 呈现，无臆造事实
- [ ] 每个诊断候选引用 >=1 evidence_id
- [ ] read-only 自动、高风险审批、forbidden 拦截三态清晰
- [ ] 审批拒绝 / 动作失败 / 验证失败均为一等状态
- [ ] dry-run 先行、命令白名单、工作目录边界、超时、截断脱敏生效
- [ ] 全程 append-only trace，输入哈希可复现
- [ ] 未读取任何排除数据 / 未伪造任何故障 / 未提出比赛模型优化

---

## 5. 边界与安全红线（演示绝不可越界）

1. **不读取排除数据**：训练/测试 CSV、`test_codeword_x_private.csv`、密钥等一律不访问。
2. **不伪造故障**：只展示真实存在的缺失证据（10 项 GAP），不制造虚假错误/故障。
3. **不真实执行风险动作**：安装/下载/训练一律 SIMULATED；不联网、不装依赖、不训练。
4. **不把缺失证据当事实**：GAP-007 文档 BER 记为 UNKNOWN，不断言为真实结果。
5. **不提出比赛模型优化方案**：本演示仅展示运维/审计闭环，不含算法优化建议。

---

*本 runbook 为规格/演示设计文档；实际演示执行在后续实现阶段（implementation_backlog P0）进行。*
