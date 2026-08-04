# Security Model

## 信任边界

```text
Human approver
  → AgentTeams decision plane (Manager + Workers)
  → localhost allowlisted Gateway
  → network-disabled PyTorch Runner
  → immutable evidence + independent Auditor
```

- Agent Worker 不持有 Docker socket，不安装 PyTorch，不获得宿主机任意执行能力；
- Gateway 不是 Agent，只接受固定任务、事件、镜像和 run-id 结构；
- Runner 只接受 `evaluate_checkpoint`，输入只读，输出目录唯一可写；
- Auditor 不能复用 Executor 的成功声明作为证明；
- 只有 Auditor 验证通过才允许 Manager 收口为 `RESOLVED`。

## 执行控制

- 人工批准必须早于执行；
- 单变量 checkpoint 变更；
- CPU、30 秒计划预算、3 次复算；
- `--network none`、非 root、只读根文件系统；
- drop all capabilities、no-new-privileges、CPU/内存/PID 限制；
- 禁止修改 `metric.py`、数据、目标指标和原始工作区；
- 重复 run ID 返回 409，避免覆盖既有证据。

## 凭据

- Runner 镜像不写入 API Key、Token、密码或用户凭据；
- ExperimentPlan 不接受凭据字段；
- Release 构建前扫描 Git 跟踪文本文件；
- 环境检查只报告可疑环境变量名是否存在，不输出值；
- `.env`、私钥和证书文件默认不进入 Git/Release。

## 证据完整性

- Runner 五文件由 `artifact_manifest.json` 记录哈希和大小；
- 证据包 manifest 记录每个 artifact 与 ZIP 哈希；
- Trace 使用前向 SHA-256 链；
- AT-003 的首次 Trace ISSUE 被保留，修正后另行生成最终审计；
- 哈希只能发现归档后的修改，不能证明源头在进入系统前一定真实，因此仍需独立数据源、权限隔离和人工审批。

## 已知限制

- Gateway 当前依赖 localhost/宿主网络边界和白名单，没有 mTLS/OIDC 服务身份；
- Worker Auditor 不安装 PyTorch，不在 Worker 中二次运行模型；
- 本版本是单机 Demo，不是生产级多租户调度器；
- 生产迁移需要外部作业调度、持久化幂等键、服务鉴权、密钥管理和集中可观测后端。
