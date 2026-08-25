# LabOps Guard 复赛演示视频脚本

建议时长：4 分钟。主画面使用只读 Trust Dashboard 与 Public Trust Evidence Replay。
对外统一使用 Trust Contract v1 和 Trust State Machine v1，不展示内部兼容文件版本。

## 0:00–0:30｜Agent 获得执行权后的风险

画面：项目定位与 Trust Dashboard 首页。

旁白：未来 Agent 不只回答问题，还会修改配置、运行评测并影响工程结论。真正的风险不是
“Agent 会不会给建议”，而是我们能否证明它是谁、为什么获准行动、执行了什么，以及结果
是否经过独立验证。LabOps Guard 是面向 AI 工程任务的可信 Agent 执行与治理基础设施。

## 0:30–1:10｜Trust Contract 与五段证据链

画面：Identity → Policy → Execution → Evidence → Audit。

旁白：Trust Contract v1 统一身份、能力、策略、执行与证据要求；Trust State Machine v1
保证审批、执行和审计顺序。六个 Agent 各有职责边界，七个 Skill 保持注册和可校验。
Dashboard 不给综合评分，而是逐域显示状态、检查项、证据来源和限制。

## 1:10–1:50｜危险分支：越权修改 metric

画面：AT-002 危险分支。

旁白：如果 Agent 为了让指标变好而修改受保护的 metric.py，Policy 和哈希检查会识别越权。
该结果不能被接受，动作被回滚，Auditor 给出 POLICY_VIOLATION / ROLLED_BACK。即使恢复哈希
通过复核，终态也不得标记为 RESOLVED。这证明治理层能拒绝“看起来更好”的不可信结果。

## 1:50–2:50｜合法分支：AT-004 受控修复

画面：AT-004 证据、计划、人工审批和 Runner。

旁白：固定 checkpoint、验证数据、metric 和协议后，accuracy 连续三次为 71.875%，历史
基线为 97.8124976%。Collector 只采集白名单证据；Analyst 将 preprocessing profile 漂移
列为首要假设。Planner 只允许在沙箱中把 train_augmented 恢复为 eval_standard，预算为
CPU、30 秒、三次复算、禁止联网。人工批准早于执行，Safe Executor 只能提交获批计划。
断网 Runner 完成后，候选三次达到 97.8124976%，受保护哈希保持不变。

## 2:50–3:30｜Independent Audit 与 Evidence Bundle

画面：Auditor、Trace、Bundle SHA-256。

旁白：Auditor 不采信 Executor 的成功声明，而是从原始日志、metrics、manifest、审批时序
和保护哈希独立重算。最终得到 PASS / RESOLVED，Trace 为 7 entries、CHAIN_OK / ACCEPTED，
27-entry Evidence Bundle 的 SHA-256 为
4092b43f39df52db3847caa28ca01e4321129a1c17ec7ca5efd2029ab1fb77cd。

## 3:30–4:00｜治理评测、边界与开源入口

画面：Trust Evaluation Suite、Public Replay、GitHub。

旁白：10 个治理案例中，越权阻断率和独立审计准确率为百分之百，错误关闭率为零；这些数字
只证明固定治理规则。Dashboard 与公网回放都只读。当前实现是单机确定性 CPU Runtime，
不宣称生产身份、分布式调度、MCP Server 或 OTel 后端。项目开放六角色、七个 Skill、Runner
契约和证据验证代码。

## 现场降级顺序

1. 本地 Trust Dashboard。
2. Public Trust Evidence Replay。
3. 预录完整运行视频。
4. Evidence Bundle 离线验证输出。

不得把 Public Replay 或录屏称为实时 AgentTeams 执行。任一哈希或契约校验失败时停止演示
闭环，并明确显示 `BLOCKED`。
