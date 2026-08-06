# Known limitations

## Scope of evidence

- AT-004 是确定性、合成、单机 CPU fixture。它证明该事件的闭环和安全边界，不证明任意
  模型、GPU、外部数据集、分布式任务或生产调度能力。
- AT-003 是旧 checkpoint 备用案例；AT-002 刻意保持 `BLOCKED`。三者的状态和证据不能
  相互覆盖或外推。
- 案例记忆只提供历史上下文。新事故必须重新采集证据、诊断、审批、执行和验证。

## Runtime and control plane

- `labops/pytorch-cpu-runner:0.2.0` 是主演示的本地 CPU 镜像；构建镜像可能访问官方仓库，
  但每次实验容器均使用 `network=none`，不会在线安装依赖。
- Safe Executor 不持有 Docker socket、凭据或 PyTorch；它向短生命周期 Gateway 提交结构化
  已批准计划，由宿主控制面启动受限 Runner。
- Gateway 是单机演示适配层，不是生产级多租户服务。它依赖固定白名单和宿主网络边界，
  还没有 mTLS/OIDC、工作负载身份、外部队列或持久化幂等存储。

## AgentTeams and audit

- Matrix 自动唤醒曾不稳定；需要明确启动 Worker 的情况均保留真实 Gateway/Auditor 产物，
  不伪造 Matrix event。
- 首次 Trace canonicalization `ISSUE` 和缺 Incident Commander 的 6-entry 中间链刻意保留；
  权威链是最终 7-entry `CHAIN_OK / ACCEPTED` 版本。
- Worker 侧 Auditor 不运行 PyTorch。它从 Runner 原始 stdout、metrics、manifest、审批时序和
  保护哈希独立重算；执行本身由断网 Runner 证明。
- SHA-256 能发现归档后的变化，不能证明进入系统前的数据源天然可信。生产环境仍需可信
  身份、来源签名和独立数据管理。

## Observability and ecosystem

- 当前 Trace、Log、Metrics、Artifact、Approval 为本地文件与 Matrix/MinIO 证据，没有部署
  OpenTelemetry Collector 或观测后端。`docs/observability.md` 只定义未来适配边界。
- Runner Gateway 具备结构化工具契约，但不声称已经实现 MCP Server。
- 当前没有 RAG、向量数据库、自动调参或新 Agent；经验检索是轻量本地 JSON 搜索。

## Release boundary

- Apache-2.0 尚待用户确认；在确认前 LICENSE 为明确占位，不代表已经完成许可证授予。
- 远端仓库、公开权限、Release 版本和 Tag 时机尚待用户确认；当前只创建本地分组提交。
