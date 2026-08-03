# 赛题二 Baseline：抽样信道校准 + OSD-2

这个 baseline 只使用一个真实训练 shard，不需要完整下载约 498 个 shard。它先从抽样数据
估计每个 bit 在 0/1 条件下的接收均值、噪声方差和先验概率，再在真实留出集选择原始或
校准后的 LLR。最终使用官方 `POLAR_N64_K32` 校验矩阵进行二阶有序统计译码（OSD-2）。

OSD 会针对每条样本动态构造“最可靠信息基”，枚举少量低可靠 bit 翻转并选取最大似然
合法码字。它比固定信息位的 Chase 或逐位硬判决更适合这个长度为 64 的短码。

## 环境

进入 `competition-baseline` 目录，后续命令均从这一层运行：

```bash
cd competition-baseline
pip install numpy pandas
```

## 抽样训练数据

在 `train/` 放置同编号的一对 shard，例如：

```text
train_codeword_x_shard_000.csv
train_noisy_y_shard_000.csv
```

来源是 `prompt.md` 指定的数据集：
`https://hf-mirror.com/datasets/aprofeta/ecc-dataset`。当前目录已经准备了 shard 000。

默认只随机使用 10000 条做信道校准、2000 条做真实验证。在本地 shard 000 上，默认配置
的参考结果约为：硬判决 BER 0.055，OSD-2 BER 0.013（不同抽样会略有波动）。使用当前
baseline 生成的正式提交文件，实际排行榜 BER 为 **0.01272**。

## 运行

校准、验证并检查前 100 条测试数据：

```bash
python baseline.py --max-rows 100 --output submission_debug.csv
```

复用校准参数生成完整提交：

```bash
python baseline.py --reuse-calibration --output submission.csv
```

正式提交 `submission.csv`，不要压缩。评测指标是 BER，越低越好。

可用 `--calibration-rows`、`--validation-rows` 调整抽样规模。默认 OSD 参数为
`--list-size 10 --order 2`；机器较慢时可改为 `--list-size 8 --order 1`。
