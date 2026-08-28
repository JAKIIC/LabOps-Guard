# GOAI Agent Infra requirement mapping

核对日期：2026-08-28
官方入口：<https://www.goaihz.com/tracks?track=infra>

## 初赛交付

| 要求 | LabOps Guard 交付 | 当前状态 |
|---|---|---|
| 500 字以内作品简介 | `docs/competition-submission-draft.md` | 429 个非空白字符，统一 AT-004 精确口径 |
| 方案 PPT/PDF | 官方模板 18 页，含个人参赛者介绍 | 已逐页渲染并进行模板/溢出检查 |
| 可执行代码包 | 源码、固定 Runner 契约、三案例证据、manifest/checksum | 源码可提交；Runner 镜像不随包分发 |

## 技术要求

| 要求 | 实现 | 可验证证据 |
|---|---|---|
| 至少 3 个不同职能 Agent | 6 个职责隔离角色，不新增第七 Agent | `agentteams/agent_identities_v2.json` |
| 以 AgentTeams 为协同基点 | Manager + 5 Worker，Matrix 交接、MinIO 共享产物 | AT-004 `handoff_manifest.json` 和 Trace |
| 任务输入与拆解 | Incident Commander 拆成 Evidence、RCA、Plan、Execute、Verify | AT-004 task contract |
| 上下文传递 | 只传 Schema 化 ID、相对路径、哈希、时间和状态 | 原始证据 ZIP |
| 工具调用 | Safe Executor 向白名单 Gateway 提交已批准计划，宿主启动断网 Runner | Gateway request/response、Runner 五文件 |
| 结果验证 | Auditor 从 raw stdout、manifest、哈希与审批时序独立复核 | `verification.json` |
| 审批与回滚 | 执行前人工批准；非法 metric 修改被拒绝并回滚 | AT-004 approval、AT-002 rollback |
| 可观测与证据 | Trace、Log、Metrics、Artifact、Approval 五类信号 | `docs/observability.md` |
| 经验沉淀 | Skill 版本化 + AT-004 postmortem + 可搜索 case memory | `skills/CHANGELOG.md`、`memory/cases/` |
| Skill 工程 | 7 个 Skill 包；五个主流程 Skill + Commander 的打包/记忆能力 | `docs/skill-integration-matrix.md` |
| 共享状态/轨迹 | Matrix + MinIO 共享状态、两类哈希链与 Dashboard 投影 | 三个独立证据包 |
| 治理评测 | 10 案例 Trust Evaluation Suite，输入与 Oracle 分离 | `docs/trust-evaluation-report-v1.0.md` |

## 评委优化意见收口

| 关注点 | 当前答卷 | 证据或准确边界 |
|---|---|---|
| 真实流程、风险与返工成本 | 补充引入前跨角色人工流程、责任人与返工来源，不虚构生产金额或节省比例 | `docs/lab-workflow-value.md` |
| 任务、上下文与状态 | task / incident / attempt、Schema 化 artifact、Matrix event 与状态交接 | AT-004 handoff / Trace；新 live session verifier |
| 审批触发与责任 | 真人 Approval；ApprovalGrant v1 强绑定计划哈希、范围、预算、时效与 nonce | Approval Schema、Gateway fail-closed tests |
| Retry / Reassign / Recovery | append-only attempt overlay；有限重试；真实备用 Worker 证据；无证据则 takeover | `labops/recovery.py`、recovery tests |
| Human Takeover | 与 Approval 分离；真人 accept/resume，不能直接 resolved，Auditor 仍最终裁决 | Recovery CLI、Trace 与 live verifier |
| 七 Skill 工程 | Registry、版本、I/O、调用条件、权限、失败、安全和验证均完整 | `docs/skill-framework.md` |
| Skill runtime 证据 | 新 live Gateway 可验证 `control-lab-action`；其余六个不伪造 invocation event | `skill_runtime_evidence` 输出 |
| 可观测与工具审计 | Matrix、Gateway I/O、Runner Artifact、hash-chained Trace、Evidence 与 Dashboard | `docs/observability.md` |
| 版本、回滚、部署与运维 | Schema/Skill 版本、策略回滚、Docker/compose/CI 已实现；生产告警、IAM、HA 是路线图 | `KNOWN_LIMITATIONS.md`、deployment/compliance docs |

## 工具契约与迁移边界

Runner Gateway 当前是本地 HTTP 适配层，不宣称已经实现 MCP Server：

| 契约 | 当前实现 | 生产迁移 |
|---|---|---|
| 输入 | 结构化 ExperimentPlan + Approval，固定大小上限 | 保持 Schema，映射 MCP tool invocation |
| 权限 | 固定任务、事件、镜像、命令、路径和 run-id 白名单 | 工作负载身份、细粒度授权、mTLS/OIDC |
| 失败 | 结构化 4xx/5xx；能力不足保持 BLOCKED | 队列、重试策略与持久化幂等键 |
| 审计 | request、response、Runner manifest、Trace | 未来 OTel adapter 只读导出，不改证据 |

ApprovalGrant v1 进一步把计划 SHA-256、批准范围、副作用、保护资源、资源预算、有效期和 nonce
绑定到 incident/plan/run；任何不一致或重放都在 Gateway 前 fail closed。Recovery 与状态机分层：
原 attempt 不覆盖，恢复创建新 attempt；真人接管不能直接设置终态。

## 评分维度答卷

| 权重 | 答卷重点 |
|---:|---|
| 场景价值与行业复制 25% | 解决 Agent 工程行动“是否获准、是否可信”，以 AI 评测漂移作为可复核样例 |
| 多 Agent 协同 25% | 六角色职责隔离、结构化 handoff、审批、失败分支和独立裁决 |
| Skill 工程与生态复用 25% | 版本、I/O、生命周期、失败处理、安全边界和跨项目参数化 |
| 工程运行与安全审计 20% | 断网 Runner、保护哈希、回滚、证据 ZIP、Trust Dashboard 与治理评测 |
| 开放/开源贡献 5% | Schema、Skill、Runner 契约、案例记忆、文档与最小 CI |

## Trust Evaluation Suite 边界

Suite 固定为 10 个治理案例，集中检查 Policy violation prevention、Evidence completeness、
False resolution prevention 和 Independent audit。执行阶段不读取 Oracle；评分阶段再对照独立
期望终态。该结果不作为综合分数，也不外推为通用 Agent 推理或全场景 MLOps 能力。

## 明确不宣称

不把 checkpoint 备用案例当主演示，不把 Worker Auditor 描述为 PyTorch 二次运行，不把
回放描述为实时执行，不把未来 OTel/MCP/生产身份写成已完成，也不以 RAG、新数据库或新
Agent 堆叠技术名词。

## 提交与发布边界

`docs/compliance/runner-sbom.json` 已完成两张本地 Runner 镜像的离线清单；许可证与 NOTICE
复核结论见 `docs/compliance/`。由于基础镜像再分发条款、Debian 源码义务和完整镜像 NOTICE
包仍未闭合，本轮只提交源码、文档和证据，不创建 Tag/Release，也不提供镜像 tar。
