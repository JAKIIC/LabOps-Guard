# Toolchain, Compatibility and Resource Disclosure

本文件集中回答官方第 09、10、11 节对工具链、版本、调用关系、替代方案、权限和迁移成本的要求。
版本未知时不猜测：外部部署组件必须在每次 live session 录制实际版本。

## 1. 当前可核验工具链

| 组件 | 当前版本或兼容范围 | 调用方式 | 与 Agent / Skill 的关系 | 权限与证据边界 |
|---|---|---|---|---|
| AgentTeams（原 HiClaw） | 实机录制环境 `v1.1.2`；仓库通过 Prompt、Task Contract 和 Artifact Schema 集成 | Manager room 接收任务，Manager 向五 Worker 派发 | 多 Agent 编排基点；不替代 Skill、Policy 或 Auditor | 真实 Matrix event ID、handoff artifact 和 Trace 才算运行证据 |
| Matrix / Element | 部署提供；版本必须在新 live session 登记 | Manager/Worker room 消息与人工 Approval event | 上下文交接和真人操作界面 | Token、私有 room ID 不进入仓库、视频或提交包 |
| MinIO / shared object store | 部署提供；版本必须在新 live session 登记 | session 隔离 bucket/prefix 或共享路径 | Agent 间交换 Schema 化 Artifact | 不覆盖正式 Evidence；凭据由外部部署管理 |
| LabOps Guard control plane | `1.0.0rc1`；Python 3.9–3.12 CI | CLI、Schema、Policy、Verifier | 为六 Agent 提供确定性治理契约 | 标准库优先；源码可直接验证 |
| Runner Gateway | API `/v1/run`，Tool Contract v1 | 本地 HTTP/JSON POST | `control-lab-action` 的受控 Tool 入口 | 固定 allowlist、ApprovalGrant、幂等 run ID、结构化审计 |
| Sandbox Runner | 主线 `0.2.0`，备用 `0.1.0` | Gateway 启动短生命周期 Docker container | Safe Executor 不直接持有 Docker socket | CPU、non-root、read-only rootfs、`network=none`、资源预算 |
| Trust Dashboard | `1.0.0rc1`；Docker 使用 Python 3.11 slim | 本地 HTTP GET；Pages 为静态构建物 | 只读 Evidence projection | 写方法 `405`；无在线审批、执行或 Trust Score |
| Case Memory | 本地 JSON Schema `1.0` | CLI 本地查询 | Commander 在终态后发布；RCA 可读取历史上下文 | 历史案例不能替代新 Incident Evidence |
| Trust Evaluation Suite | `v1.0`，10 个固定治理案例 | 本地确定性执行，Oracle 独立评分 | 检查 Policy、Evidence、False Resolution 和 Audit | 不调用 AgentTeams 核心链，不称通用 Benchmark |

## 2. 外部模型、API 与数据披露

- AT-004 Runner 使用仓库自建合成 fixture 和固定本地 CPU 运行，不调用商业 API、外部数据集或
  闭源模型服务。
- AgentTeams 的 LLM provider/model 由具体 live 部署提供，不随源码包分发。录制人员必须在私有
  清单登记 provider、model、费用假设和替代方案，但不得公开 Token；最终裁决仍依赖结构化
  Evidence 和 Auditor，而不是模型自述。
- Matrix、MinIO 和 AgentTeams 的部署配置不随仓库硬编码；评审机使用自身获授权的实例与凭据。

## 3. 官方推荐工具的取舍

| 官方推荐项 | 当前决定 | 原因与等价能力 | 后续迁移成本 |
|---|---|---|---|
| 阿里云官方用云 Skills | 本轮未引入 | 当前场景不操作云资源；七个 repo-native Skill 聚焦证据、规划、受控执行和审计 | LOW：把云资源 Tool 依赖挂到现有 Skill contract，不改变 Agent 责任 |
| Nacos | 未引入 | Registry、Schema 和 Git 提供候选版资源版本治理，避免增加演示控制面 | MEDIUM：增加只读发布/发现 adapter，并保留 Git 版本为权威来源 |
| Higress | 未引入 | Gateway 仅在受信任本机短时运行，固定 allowlist 足够演示 | MEDIUM：在外层增加鉴权、路由、限流和观测，不改变 Tool Contract |
| PolarDB for PostgreSQL | 未引入 | Case Memory、Trace 和 Evidence 是本地文件/MinIO；固定案例无需向量数据库 | MEDIUM：映射现有 Schema 和索引，不改变证据引用语义 |
| RocketMQ | 未引入 | AgentTeams/Matrix 负责当前顺序交接；比赛版不宣称分布式并发调度 | HIGH：需定义投递语义、去重、持久化锁和故障恢复 |
| LoongSuite / AgentScope Studio / AgentLoop | 未引入 | 当前使用 hash-chained Trace、Log、Metrics、Artifact、Approval 与只读 Dashboard | MEDIUM：只读 exporter 转换既有事件；失败不能影响权威 Evidence |
| MCP | 未实现 Server | HTTP/JSON Tool Contract 已覆盖协议、Schema、权限、错误、幂等和审计 | LOW：增加 transport adapter；Approval、Runner、Audit 语义保持不变 |
| RAG | 明确不使用 | 采用 Shared State + Trace Observability 两项官方替代能力；Case Memory 仅作补充 | HIGH：若引入需新增向量化、授权、召回评测和证据对齐，不适合本轮 |
| OpenTelemetry backend | 未部署 | 文件型五信号可独立复核；已有只读 OTel 字段映射设计 | MEDIUM：增加异步 OTLP exporter，不进入审批和证据写入路径 |

官方推荐工具不按数量评分。本项目选择最小依赖，是为了保持 AT-004 可复现、断网执行和证据权威性；
未实现的组件均保留清晰 adapter 边界，不把路线图描述为已部署能力。

## 4. Live session 版本记录

录制新 live run 时至少记录以下非敏感字段：

```text
agentteams_version
matrix_server_product_and_version
element_version
object_store_product_and_version
docker_engine_version
runner_image_and_digest
python_version
labops_commit
llm_provider_and_model (no token)
```

缺少版本记录不会改变历史 Evidence，但会使新 live session 的“部署可复现性”检查保持
`LIMITED`，不得写成生产级完全复现。
