# LabOps Guard v0.2.0-rc1

这是面向 GOAI Agent Infra 初赛展示与离线复现的首个 Release Candidate。

## 已验证能力

- 六角色 AgentTeams 真实协作和结构化交接；
- 人工审批后的专用 PyTorch CPU Runner；
- 无网络、非 root、只读根文件系统和资源限制；
- AT-002：依赖缺失时安全 `BLOCKED`；
- AT-003：`70.00% → 98.12%`，Auditor 复核后 `PASS / RESOLVED`；
- 非法 `metric.py` 篡改：`POLICY_VIOLATION / ROLLED_BACK`；
- ZIP、artifact、Runner manifest 与 Trace 哈希重验；
- AT-002 与 AT-003 在只读仪表盘中分开展示。

## 离线包内容

- `labops-guard-source.zip`：冻结提交导出的源码；
- `labops-pytorch-runner-0.1.0.tar`：固定 Runner 镜像；
- `labops-guard-dashboard-local.tar`：可离线加载的只读仪表盘镜像；
- `demo-fixture/LABOPS-AT-003-baseline-fixture.zip`：确定性 checkpoint fixture；
- `evidence/`：AT-002、AT-003 正式证据包和 manifest；
- `release_manifest.json` 与 `checksums.sha256`。

## 事实边界

Verification Auditor 不在 Worker 中重新运行 PyTorch。它独立复核隔离 Runner 的原始输出、三次指标、审批时序、文件完整性、执行范围、manifest 与 Trace。该版本不宣称支持任意模型、GPU、生产级多租户调度或任意外部数据集。
