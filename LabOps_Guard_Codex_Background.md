# LabOps Guard 项目背景与实施规范

> 文档版本：v0.2.0  
> 更新时间：2026-08-03  
> 项目阶段：Agent Infra 初赛冲刺  
> 内部冻结：2026-08-10  
> 官方截止：2026-08-16

本文件取代 v0.1.0 中“Polar 优先”的执行顺序。未明确修改的安全、证据、审批、Agent
职责和合规原则继续有效。

## 当前路线

- 核心系统：LabOps Guard。
- 主交付：轻量 checkpoint regression 故障诊断兜底 Demo。
- 首个新事故：`DEMO-RCA-001`。
- 扩展案例：Polar 码实验审计与优化。
- Polar 不得阻塞初赛交付。

## 目标演示

错误评测配置加载 `last.pt`，其指标明显低于训练保存的 `best.pt`。系统必须完成：

`Incident → Evidence → RCA → Plan → Policy → Sandbox Execute → Independent Verify → Postmortem`

合法修复只允许把 checkpoint 路径从 `last.pt` 改为 `best.pt`，结果应为 `PASS`。
修改数据、目标指标或 `metric.py` 来制造提升必须返回 `POLICY_VIOLATION` 并回滚。

## 工程分层

1. 确定性核心：状态机、Schema、取证、策略、执行、验证。
2. Skills：核心能力的可复用契约。
3. AgentTeams：1 Manager + 5 Worker 调用 Skill，不重复实现 Python 逻辑。
4. Demo 与证据：输入、日志、Trace、截图、报告、视频。

即使 LLM 或 AgentTeams 暂时不可用，本地 CLI 也必须完整运行兜底 Demo。

## 六角色边界

- `incident-commander`：编排和状态治理，不修改代码、不自证成功。
- `evidence-collector`：只读取证，不输出最终根因。
- `rca-analyst`：只基于 Evidence ID 排序假设。
- `experiment-planner`：生成单变量最小实验，不执行。
- `safe-executor`：只在 sandbox 执行批准计划，失败回滚。
- `verification-auditor`：独立验证，唯一可推动到 `RESOLVED` 的角色。

## 不可违反的原则

- 无证据不诊断，无审批不执行，无验证不闭环。
- 默认离线、默认只读、默认 dry-run。
- 不读取密钥、私有标签或排除数据。
- 不修改指标定义、测试数据和比赛规则。
- 不直接覆盖原项目；实验仅发生在沙箱副本。
- 所有结论、状态变化、审批、工具结果和回滚必须写入 Trace。
- 信息不足时输出缺口，不得编造。

## 冻结顺序

1. checkpoint Demo 连续成功三次。
2. 本地 CLI 完整闭环和安全反例通过。
3. 新六角色 AgentTeams 流程录制完成。
4. README、PPT、视频和提交材料冻结。
5. 仅在上述条件满足后开展 Polar 扩展案例。

