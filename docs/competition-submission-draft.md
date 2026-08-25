# 复赛提交文字

## 项目名称

LabOps Guard：面向生产级 Agent 系统的可信基础设施

## 一句话定位

LabOps Guard 以身份、Skill、策略、审批、受限执行、证据和独立审计约束 Agent 的每一次工程行动。

## 500 字以内作品简介

Agent 进入真实工程环境后，会修改配置、运行评测并影响工程结论。LabOps Guard 基于
AgentTeams 构建六角色职责隔离闭环，并用 Trust Contract v1 统一 Identity、Skill、Policy、
Execution、Evidence 与 Audit。Collector 只采白名单证据，Analyst 形成可证伪假设，Planner
生成单变量可回滚计划，Executor 仅在人工批准后调用断网 CPU Runner，Auditor 从原始产物、
保护哈希、审批时序和 Trace 独立裁决。AT-004 中，系统将 71.875%×3 的预处理漂移恢复到
97.8124976%×3，六组保护哈希不变；越权修改 metric.py 则得到 POLICY_VIOLATION /
ROLLED_BACK。10 案例 Trust Evaluation Suite 进一步验证策略阻断、证据完整、错误关闭防护和
独立审计。项目开放七个版本化 Skill、Schema、Tool Contract、Runner 契约、Evidence Bundle
与只读 Trust Dashboard。

## 官方模板

### 复赛 18 页内容

1. 标题与新定位。
2. Agent 获得执行权后的信任问题。
3. 项目目标与适用范围。
4. Agent Trust Layer 总体架构。
5. 六 Agent 职责隔离。
6. Identity 与 Skill Registry。
7. Policy 与 Human Approval。
8. Tool Contract 与 Secure Runner。
9. Independent Auditor。
10. Trace 与 Evidence Bundle。
11. Trust Dashboard。
12. AT-004 事故与证据。
13. 合法修复结果。
14. 非法 metric 修改阻断。
15. Trust Evaluation Suite v1.0。
16. CI、SBOM、License 与开源规范。
17. 当前限制与生产化路线。
18. 总结、GitHub 与 Public Evidence Replay。
