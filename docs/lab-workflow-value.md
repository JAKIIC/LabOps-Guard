# 真实实验室流程、责任与受控收益

本文说明 LabOps-Guard 所针对的 AI 工程实验事故流程。它用于复赛场景说明和受控演示口径，
不把演示数据外推为真实生产 ROI，也不声称替代实验室现有的安全、质量或合规制度。

## 1. 引入前：一次评测漂移如何被处理

典型流程不是“一个人改一处配置”这么简单，而是跨角色的人工闭环：

```text
值班人员发现指标异常
→ 工程师分散查找日志、配置、数据与模型版本
→ 研究员讨论根因并提出实验
→ 负责人判断风险并批准高风险动作
→ 工程师修改、重跑和收集结果
→ 独立复核人员确认是否真的恢复
→ 多处归档聊天、日志、指标和结论
```

| 环节 | 主要责任人 | 典型风险与返工来源 |
|---|---|---|
| 发现与登记 | 值班人员 / Incident Owner | 输入信息不全、任务边界不清，后续反复补问 |
| 证据收集 | 工程师 | 日志、指标、配置与版本分散，证据来源和时间不一致 |
| 根因讨论 | 研究员 / 工程师 | 假设没有绑定证据，容易把相关性当因果 |
| 方案与审批 | 负责人 / 审批人 | 审批对象、范围、预算或副作用描述不精确 |
| 修改与重跑 | 执行工程师 | 变量过多、越权修改、环境漂移或重复运行 |
| 复核与关闭 | 独立复核人员 | 只相信执行者结论、缺失原始产物或过早关闭 |
| 归档与复用 | Incident Owner | 证据散落，下一次事故重复调查 |

成本主要体现为人工接触次数、消息往返、重复运行、证据整理、等待审批和错误关闭后的再次返工。
本项目不虚构统一金额或生产节省比例；不同实验室的算力、人力和合规成本需要在真实部署中测量。

## 2. 引入后：责任隔离的 Agent 治理闭环

```text
Incident
→ Evidence Collection
→ RCA
→ Single-variable Plan
→ Human Approval
→ Secure Execution
→ Independent Audit
→ Evidence Bundle / Case Memory
```

| 阶段 | Agent / 人员 | 责任边界 | 可核验输出 |
|---|---|---|---|
| 任务分派 | Incident Commander | 编排、验收交接，不执行、不自证 | task / incident / attempt、handoff |
| 采证 | Evidence Collector | 只读白名单证据，不诊断 | 带来源与 SHA-256 的 Evidence |
| 分析 | RCA Analyst | 只基于 evidence ID 形成可证伪假设 | hypothesis、支持/反证、置信度 |
| 规划 | Experiment Planner | 单变量、有限预算、可回滚 | ExperimentPlan 与成功/回滚条件 |
| 正常授权 | 真人 Approver | 只批准具体计划、范围、预算与时效 | ApprovalGrant v1 |
| 受控执行 | Safe Executor + Runner | 仅提交获批 Tool Contract；不能宣布成功 | Gateway I/O、Runner Artifact |
| 独立裁决 | Verification Auditor | 从原始产物重算；独占终态裁决 | verification、Trace、final decision |
| 异常接管 | 真人 Operator | 接受并恢复 takeover；不能直接写 `RESOLVED` | append-only recovery events、新 attempt |

`Human Approval` 与 `Human Takeover` 不是同一机制：前者是正常高风险动作的授权门；后者是
worker timeout、证据不足、能力缺失、工具失败、审计不确定或重试预算耗尽后的异常恢复责任转移。
接管后仍须回到 AgentTeams 流程，并由 Verification Auditor 最终裁决。

## 3. Approval 强绑定与异常恢复

ApprovalGrant v1 绑定 `incident_id`、`plan_id`、规范化计划 SHA-256、`run_id`、批准范围、允许
副作用、保护资源、资源预算、审批人、时间、失效时间与 nonce。Gateway 对计划哈希、范围、预算、
时效或 nonce 重放不一致实行 fail closed；Agent 不能自行批准。

Recovery 使用独立的 append-only attempt/ownership overlay，不改写 Trust Contract v1 或 Trust
State Machine v1。原 attempt 保持终态，新恢复创建新的 attempt/run；自动重试受预算约束，
Reassign 必须引用真实备用 Worker 与 Matrix/capability 证据，否则记录
`REASSIGN_UNAVAILABLE → HUMAN_TAKEOVER`，不伪造重派成功。

## 4. 可度量的受控收益

复赛演示只报告当前证据能够支持的指标：

| 指标 | 如何度量 | 预期变化 |
|---|---|---|
| 人工接触次数 | 一个 incident 中需要人工作出决定或补充输入的次数 | 正常闭环减少；高风险审批和异常接管保留 |
| 消息往返 | Agent/人员之间可核验 handoff 数量 | 从自由聊天转为结构化交接，减少重复确认 |
| 重复运行 | 相同计划或 run 的重复执行次数 | session/run 隔离与幂等门禁阻止误重跑 |
| 证据完整度 | 必需 Evidence、Trace、Artifact、Approval、Audit 的齐备率 | 缺项即 `BLOCKED`，不以口头结论替代 |
| 错误关闭 | 不满足 Oracle/验证条件却进入 resolved 的案例数 | 固定治理案例中保持为零 |
| 处理时间 | 从 incident 创建到 Auditor 裁决的时间 | 在真实部署中持续采集，不在受控 Demo 中虚构 ROI |

AT-004 只证明一个可复核闭环：`71.875% × 3` 恢复到 `97.8124976% × 3`，六组保护哈希不变；
它不证明所有实验事故都能自动修复。Trust Evaluation Suite v1.0 只证明 10 个固定治理案例中
系统判定与预设 Oracle 一致，不宣称“100% 安全”。

## 5. 当前证据与边界

- 六角色历史真实协作：AT-002/003/004 Matrix event、handoff artifact 与冻结 Evidence Bundle；
- 新 live run：ApprovalGrant、Session、Recovery/Takeover 与 Gateway Tool Contract verifier 已就绪；
- Skill：七个 Registry/Schema 契约均可校验；只有 `control-lab-action` 可由新 live Gateway Evidence
  独立证明 runtime binding，其余六个仍为 `CONFIGURED / AGENTTEAMS_HOOK_REQUIRED`；
- 生产路线：IAM/KMS、不可变对象存储、告警、发布回滚、OTel adapter、HA 与多租户保留为路线图，
  本轮不为了关键词堆叠实现。
