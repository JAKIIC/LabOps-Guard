# Security model

## Trust boundary

```text
Human approval
  → AgentTeams decision plane (Incident Commander + five Workers)
  → allowlisted local Gateway
  → network-disabled PyTorch CPU Runner
  → immutable evidence + independent Verification Auditor
```

- Worker 不持有 Docker socket、宿主凭据或 PyTorch，也不能向 Runner 镜像写入密钥；
- Gateway 不是 Agent，只接受固定 Schema、任务、事件、镜像、命令、路径和 run-id；
- Runner 输入只读、输出目录唯一可写，非 root、只读根文件系统、drop capabilities、
  `no-new-privileges`、CPU/内存/PID 限额和 `network=none`；
- Auditor 不接受 Executor 的成功声明作为证明；只有独立验证才能闭环。

## Plan and approval controls

- 每个计划只允许一个被证据支持且可回滚的变量变化；
- AT-004 只允许沙箱评测预处理字段从已观察值恢复到历史登记值；
- AT-003 checkpoint 修改仅作为独立备用合同；
- metric、数据、checkpoint 内容、评测协议、目标阈值和原始工作区均受保护；
- 人工批准必须早于执行；禁止动作不能通过审批降级放行；重复 run ID 拒绝覆盖。

## Evidence integrity

- Runner 五文件由 `artifact_manifest.json` 记录哈希与大小；
- 外层 evidence manifest 校验 ZIP member set 和每个 allowlisted artifact；
- Trace 使用前向 SHA-256 链，首次失败和中间链原样保留；
- Dashboard 是只读投影，会重新校验证据但不改变事故状态；
- closure v2 和 case memory 使用独立包，绝不改写原始 AgentTeams 证据。

## Governance evaluation

- Trust Evaluation Suite 的执行阶段只读取案例输入，评分阶段才读取独立 Oracle；
- 两个保护资源越权案例必须在 Runner 启动前阻断，并由 Auditor 裁决
  `POLICY_VIOLATION / ROLLED_BACK`；
- 证据缺失、哈希不一致、审批缺失或过晚、多变量计划与 Executor 自证都不得进入
  `RESOLVED`；
- Suite 不调用 AgentTeams 核心执行链，不写正式 Evidence，也不把固定案例结果包装为生产
  安全保证。

## Credential and privacy controls

- `.env`、私钥、证书、Token、密码和用户凭据不得进入镜像、计划、证据或 Release；
- 发布前扫描跟踪与未跟踪文本，不输出环境变量值；
- Prompt、消息、工具参数和绝对宿主路径默认不进入未来遥测导出。

## Residual risk

当前 Gateway 依赖单机宿主边界和白名单，没有生产级 mTLS/OIDC、工作负载身份或外部调度；
SHA-256 只能发现归档后变化，无法自动证明源头可信；Auditor 不在 Worker 中重新运行
PyTorch。生产迁移仍需独立身份、可信来源、密钥管理、调度与集中可观测后端。
