# GOAI Agent Infra 赛事要求映射

核对日期：2026-08-04
官方依据：<https://www.goaihz.com/tracks?track=infra>

## 初赛交付

| 官方要求 | LabOps Guard 对应内容 | 可验证证据 | 状态 |
|---|---|---|---|
| 500 字以内作品简介 | `docs/competition-submission-draft.md` | 字数检查 | 已起草 |
| 方案 PPT/PDF | 14 页文字结构 | 同上 | 已起草，待视觉定稿 |
| 可执行代码包（可选） | 离线 Release Candidate | `release/v0.2.0-rc1/` 与 SHA-256 | 生成后验收 |

## 技术要求

| 官方要求 | 实现 | 证据/入口 |
|---|---|---|
| 不少于 3 个不同职能 Agent | 6 个职责隔离角色 | `agentteams/agent_identities_v2.json` |
| 以 AgentTeams 为协同基点 | Manager + 5 Worker，Matrix 交接、MinIO 共享产物 | `handoff_manifest.json`、`agentteams_trace.jsonl` |
| 任务输入与拆解 | Commander 将事件拆成 Evidence、RCA、Plan、Execute、Verify | `agentteams/tasks/LABOPS-AT-003.json` |
| 上下文传递 | 只传递 schema 化 artifact ID、输入输出路径与状态 | AT-003 证据包 |
| 工具调用 | Safe Executor 调用本机 Gateway，Gateway 启动隔离 Runner | `gateway_request.json`、Runner 五文件 |
| 结果验证 | Verification Auditor 独立复核 Runner 原始证据 | `verification.json` |
| 审批与回滚 | 执行前人工批准；非法篡改阻断并回滚 | `approval.json`、AT-002 非法案例 rollback artifact |
| 执行证据沉淀 | Matrix、MinIO、Artifact、Metrics、Log、Trace、ZIP | 两个正式证据包 |
| 经验沉淀 | 能力检查前置、单变量策略、异常案例与限制固化为 Skill/策略/文档 | `skills/`、`KNOWN_LIMITATIONS.md` |
| Skill 必选 | Evidence、RCA、Plan、Execute、Verify、Pack 六类 Skill | `skills/*/SKILL.md` 与 I/O schema |
| 记忆/RAG/共享状态/轨迹至少 2 项 | 不使用 RAG；实现共享状态与轨迹可观测 | Matrix + MinIO、两类 Trace hash chain |

## 无 MCP 时的等价工具契约

当前 Runner Gateway 是协议适配层，不宣称已实现 MCP Server。

| 契约项 | 当前实现 | 边界/迁移方式 |
|---|---|---|
| 协议与入口 | HTTP `POST /v1/run`，JSON body | 可直接映射为 MCP tool invocation |
| 输入 Schema | `experiment_plan` + `approval`，最大 64 KiB | Plan 先经 JSON Schema 与 policy 校验 |
| 返回结构 | 状态、task/run/approval ID、Runner 五文件 | MCP 适配层保持字段不变 |
| 权限范围 | 固定 AT-003、incident、Runner image、run-id 格式 | 生产环境应使用服务身份和细粒度授权 |
| 鉴权 | localhost/宿主网络边界 + 人工审批字段 + 固定白名单 | 当前无密码学服务身份；生产迁移必须增加 mTLS/OIDC |
| 失败处理 | 400/403/409/413/422/500；能力不足时拒绝执行 | 不把失败降级成成功 |
| 幂等/防覆盖 | 已存在 `run_id` 返回 409，正式证据 append-only | 生产可换为持久化幂等键 |
| 并发 | 单进程锁；繁忙返回 409 | 生产迁移到队列/调度器 |
| 审计 | 保存 request、response、Runner manifest、Trace | MCP 适配不改变证据模型 |
| 降级 | Gateway/Runner 不可用时进入 BLOCKED | 证据回放仅用于展示，不冒充新执行 |

## 评分维度对应

| 权重 | 答卷重点 |
|---:|---|
| 场景价值与行业复制 25% | AI 实验异常响应的通用风险；适配训练、评测、数据与部署流水线 |
| 多 Agent 协同 25% | 职责隔离、结构化 handoff、异常分支、审批和最终裁决权 |
| Skill 工程与生态复用 25% | 六类 Skill 的输入输出、调用条件、失败处理、安全边界与版本化 |
| 工程运行与安全审计 20% | 离线 Runner、三案例、Trace、Metrics、哈希、回滚和可迁移包 |
| 开放/开源贡献 5% | 标准 Schema、Runner 契约、可替换 Gateway、示例与复现文档 |

## 当前不做

- 不为凑技术数量增加 MCP、RAG、PolarDB、Nacos 或新 Agent；
- 不声称 Worker 内 Auditor 重新运行了 PyTorch；
- 不把 AT-003 的成功写回 AT-002；
- 不把证据回放表述为新的实时执行。
