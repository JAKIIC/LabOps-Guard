# competition_data 数据集说明

本 README 用于解释 `competition_data/` 数据集的内容、字段含义和生成方式。数据集已经下载到本仓库中，选手可以直接读取本地 `competition_data/` 目录进行训练和推理。

## 1. 任务目标

本任务是纠错码解码任务。给定经过信道噪声污染后的接收序列 `y`，模型需要恢复原始码字 `x`。

每个样本的真实码字长度为 `N=64`：

```text
x = [bit_0, bit_1, ..., bit_63]
```

公开给选手的输入是连续接收值：

```text
y = [y_0, y_1, ..., y_63]
```

选手最终需要输出每个测试样本对应的 `bit_0` 到 `bit_63`。

## 2. 数据集配置

当前数据集配置如下：

| 字段 | 含义 | 当前值 |
| `code_type` | 编码类型 | `POLAR` |
| `code_n` | 码字长度 | `64` |
| `code_k` | 信息位长度 | `32` |
| `train_shard_size` | 每个训练 shard 的样本数 | `64000` |
| `test_samples` | 测试集样本数 | `100000` |


## 3. 文件结构

`competition_data/` 中主要包含：

```text
train_codeword_x_shard_000.csv
train_noisy_y_shard_000.csv
train_codeword_x_shard_001.csv
train_noisy_y_shard_001.csv
...
test_noisy_y_public.csv
```

训练集被切成多个 shard。每个 shard 有一对文件：

- `train_codeword_x_shard_XXX.csv`：真实码字标签 `x`。
- `train_noisy_y_shard_XXX.csv`：带噪声接收序列 `y`。

同一编号的 `x` 文件和 `y` 文件通过 `id` 一一对应。例如：

```text
train_codeword_x_shard_000.csv
train_noisy_y_shard_000.csv
```

这两个文件中 `id=0` 的行表示同一个样本。

## 4. CSV 字段说明

### 4.1 训练标签文件

文件名示例：

```text
train_codeword_x_shard_000.csv
```

列格式：

```text
id,bit_0,bit_1,...,bit_63
```

字段含义：

- `id`：样本编号。
- `bit_0` 到 `bit_63`：原始码字的 64 个二进制 bit，取值为 `0` 或 `1`。

### 4.2 训练输入文件

文件名示例：

```text
train_noisy_y_shard_000.csv
```

列格式：

```text
id,y_0,y_1,...,y_63
```

字段含义：

- `id`：样本编号，与同编号的 `train_codeword_x_shard_XXX.csv` 对齐。
- `y_0` 到 `y_63`：经过调制和加噪后的连续接收值。

注意：`y_i` 是浮点数，不是 bit。一般情况下，`y_i > 0` 倾向于对应 bit `0`，`y_i < 0` 倾向于对应 bit `1`，但由于噪声存在，硬判决可能出错。

### 4.3 公开测试输入

文件名：

```text
test_noisy_y_public.csv
```

列格式：

```text
id,y_0,y_1,...,y_63
```

这是选手需要预测的测试输入，不包含真实码字标签。

### 4.4 私有测试标签

文件名：

```text
test_codeword_x_private.csv
```

列格式：

```text
id,bit_0,bit_1,...,bit_63,ebno_db
```

该文件包含测试集真实码字和样本对应的 Eb/N0，主要用于主办方评测或本地核验，不应作为选手提交时的输入标签。


## 6. 提交格式

提交文件必须是 CSV，列名如下：

```text
id,bit_0,bit_1,...,bit_63
```

要求：

- `id` 必须与 `test_noisy_y_public.csv` 中的 `id` 对应。
- 每个 `bit_i` 必须是 `0` 或 `1`。
- 不要添加 `y_i`、`ebno_db` 或其他额外列。

## 7. Baseline

可参考：

```text
participant_pipeline_cnn_mlp.ipynb
```

该 notebook 会读取 `competition_data/` 中的训练 shard，训练一个 CNN + MLP 残差解码器，并生成提交文件。

