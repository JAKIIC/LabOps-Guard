# 数据说明

公开测试输入文件为 `competition_data/test_noisy_y_public.csv`，字段为：

```text
id,y_0,y_1,...,y_63
```

该文件不包含真实码字标签。选手需要基于每一行的 64 维接收信号，输出对应的 `bit_0` 到 `bit_63`。

训练集由赛题页面提供下载链接。下载训练集后，建议与本公开测试文件放在同一个 `competition_data/` 目录中，以便直接运行 baseline notebook。
