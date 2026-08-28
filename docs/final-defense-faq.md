# LabOps-Guard 复赛答辩 FAQ

## 1. 为什么这是 Agent Infra，而不是 MLOps？

AT-004 使用模型评测漂移作为可验证载体，但系统治理的是 Agent 获得工具和执行权限后的通用信任
问题：Identity、Skill、Policy、Approval、Secure Execution、Evidence 和 Independent Audit。
Runner 只允许契约内副作用，Auditor 独占终态裁决权；这是一层可复用的 Agent 执行与治理基础设施，
不是实验看板或训练调度器。

## 2. AgentTeams 在哪里？六个 Agent 是否真实协作？

外部 HiClaw / AgentTeams 运行时由一个 Manager 和五个 Worker 构成，通过 Matrix 进行真实 handoff，
通过共享文件系统/MinIO 传递结构化 artifact。AT-004 的冻结 Evidence 含六次角色交接对应的真实 Matrix
event ID、时间、输入与输出。Python 的确定性测试和 Public Replay 不被当作 live AgentTeams 证据。

## 3. Skill 与普通 Prompt 有什么区别？

七个 Skill 都在 Registry 中版本化，并声明 owner、调用条件、输入/输出 Schema、工具依赖、失败状态、
安全边界和审计事件。Prompt 可以指导一次任务；Skill Contract 可以被不同符合 Schema 的工程场景
发现、校验和复用。历史 AT-004 没有独立的 runtime `skill_id` 事件，因此项目不回填、不伪造该证据。

## 4. 为什么没有为了比赛加入 MCP、RAG 或 OTel？

当前评分闭环的关键是安全工具调用、证据和审计，而不是协议名。项目已经有向后兼容的 Tool Contract、
轻量 Case Memory 和 Evidence-centric observability；仓库没有宣称 MCP Server、通用 RAG 或 OTel 后端。
冻结阶段增加这些组件会扩大依赖和故障面，却不会提高现有 AT-004 证据真实性。

## 5. Verification Auditor 是否真正独立？

Safe Executor 只能提交原始 Runner 输出，不能决定 `RESOLVED`。Verification Auditor 从三次原始指标、
审批时序、唯一变更路径、network 设置、manifest、受保护哈希与 Trace 链独立重算。只有 Auditor 可产生
终态；Manager 只封包和发布。

## 6. Evaluation Suite 是否过拟合？

它是 10 个固定治理案例的回归验证，不是通用 Agent Benchmark，也不证明“100% 安全”。执行阶段只读
inputs，评分阶段再读独立 Oracle；评估 Policy violation prevention、Evidence completeness、False
resolution prevention 和 Independent audit。结论应表述为：当前固定案例中系统判定与预设 Oracle
一致，8 个不应关闭的案例没有错误关闭。

## 7. AT-002 是否真的修改了生产 metric.py？

没有。准确口径是：危险动作方案 → Policy / protected-resource boundary → real resource execution
rejected → isolated adversarial/tampered fixture 验证检测能力 → `POLICY_VIOLATION` / rollback
verification。不能描述为“生产文件被越权修改后系统才发现”。

## 8. 为什么当前视频不重新跑 AT-004？

2026-08-26 的实机彩排中，在线 Manager 复核到固定 task/run ID 已有 2026-08-04 的完整真实闭环，
因此正确拒绝重复执行。删除状态、换 ID 或复用审批会破坏治理语义。视频采用 Strategy C：真实历史
AgentTeams 素材 + 当前 live verifier 与只读 Dashboard，并明确标注 archived/live。

## 9. 如何部署到生产环境？

当前版本是单机、安全 Runtime 的 source-only candidate，不是分布式多租户平台。生产化需要把策略
Identity 接到组织 IAM/KMS，把 Gateway 接到受控执行集群，把 Evidence 接到不可变对象存储与组织审计，
并增加密钥轮换、隔离租户、灾备和长期可观测后端。现有 Trust Contract、Tool Contract、Policy、
Runner 和 Auditor 提供可迁移的治理边界。

## 10. 真实实验室原来怎么处理，成本在哪里？

典型流程是值班人员发现异常、工程师跨系统找日志/配置/版本、研究员讨论根因、负责人审批、
工程师修改重跑、独立人员复核，再把聊天、日志和结论分散归档。成本不只来自算力，还来自人工
接触、消息往返、等待审批、重复运行、证据整理和错误关闭后的返工。项目只报告可核验的受控指标，
不把 AT-004 外推为生产 ROI；完整口径见 `docs/lab-workflow-value.md`。

## 11. Human Approval 与 Human Takeover 有什么区别？

Approval 是正常高风险路径的授权：真人批准一个强绑定计划、范围、预算与有效期。Human Takeover
是异常恢复路径：证据不完整、timeout、能力缺失、工具失败、审计不确定或重试预算耗尽后，由真人
接受 ownership 并恢复新 attempt。接管者不能直接写 `RESOLVED`，最终仍由 Auditor 裁决。

## 12. 七个 Skill 都有运行时调用证据吗？

没有过度宣称。七个 Skill 的 Registry、Schema 和版本化工程契约均可验证；新 live run 中只有
`safe-executor → control-lab-action → labops.runner.execute` 可以通过 Gateway 归档 Tool Contract
独立证明 runtime binding。其余六个在没有可靠 AgentTeams Worker hook 时准确标记为
`CONFIGURED / AGENTTEAMS_HOOK_REQUIRED`，历史 Trace 不回填 `skill_id`。

## 13. 异常告警、发布回滚与持续运维是否完成？

当前已有结构化失败码、BLOCKED、Recovery/Takeover、策略回滚、版本化 Schema/Skill、CI、compose、
Evidence verifier 和只读 Dashboard。生产级 Alertmanager、IAM/KMS、HA、多租户、不可变远端存储和
OTel backend 是明确路线图，不包装成已部署能力；比赛版本优先保证真实 AgentTeams 闭环可核验。
