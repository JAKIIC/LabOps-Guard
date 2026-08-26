# AgentTeams Real Demo Runbook

本手册用于复赛录制和第三方复核。它复用现有 HiClaw / AgentTeams、Matrix、MinIO、Runner
Gateway、受限 Runner、Evidence 与 Verification Auditor，不实现新的 Agent，也不模拟六角色
对话。

## 1. 先区分三种运行方式

### A. AgentTeams live execution

由外部 HiClaw / AgentTeams 环境中的 `labops-manager` 接收 AT-004 Manager Prompt，并通过
Matrix 把工作依次交给五个 Worker。Safe Executor 向短生命周期 Runner Gateway 提交已批准
计划，Auditor 从原始 Runner 输出独立裁决。这是录制“实时六 Agent 协作”时唯一可使用的
方式。

### B. 本地确定性控制面 / 测试执行

`python -m unittest`、`scripts/run_local_demo.py`、Trust Evaluation Suite 和 Runner/Gateway
测试验证 Schema、Policy、执行与审计规则，但不启动 HiClaw、Matrix 或六个 Worker，不能称为
AgentTeams live execution。

### C. Archived Evidence Replay

Trust Dashboard、GitHub Pages Public Demo 和三个正式 Evidence Bundle 只读重放已经发生的
运行。它们可以证明历史 Matrix event、Runner Artifact、Trace 与 Auditor 结论，但不能描述为
当前正在实时执行。Dashboard 不会自动变成新一次 live run 的监控页。

```text
Live: Manager → Evidence Collector → RCA Analyst → Experiment Planner
             → human approval → Safe Executor → Runner Gateway → Runner
             → Verification Auditor → Manager publishes the audited result

Local deterministic: contracts / policy / runner / verifier tests (no six-Agent chat)
Archived replay: immutable ZIP + manifest + Dashboard projection (no live execution)
```

## 2. 当前真实运行链路

1. 参赛者把 `agentteams/prompts/eval_drift_task.md` 的完整文本发送到已配置的 AgentTeams
   Manager room；Manager 按 `agentteams/tasks/LABOPS-AT-004-EVAL-DRIFT.json` 接收任务。
2. `labops-manager` 派发给 `evidence-collector`。Collector 读取白名单 fixture、生成带 SHA-256
   的证据，不做 RCA。
3. `rca-analyst` 只消费结构化 Evidence，输出有支持、反证、置信度和证伪条件的候选假设。
4. `experiment-planner` 生成只改变沙箱 preprocessing profile 的单变量计划；策略检查保护
   metric、数据、checkpoint、协议、模型和原工作区。
5. Manager 请求独立人工批准。批准必须早于执行；它不是第七个 Agent。
6. `safe-executor` 将计划、批准和 Tool Contract POST 到
   `http://host.docker.internal:18103/v1/run`。Gateway 只接受 allowlist 内的 AT-004；专用
   Runner 使用 CPU、非 root、只读根文件系统和 `network=none`，写入新的非正式录制目录。
7. `verification-auditor` 读取计划、批准、Runner 五个原始输出、保护哈希和 Trace，独立重算
   三次指标与后置条件。只有它能给出 `PASS / RESOLVED`；Executor 和 Manager 均不能自证。
8. Manager 只在 Auditor 裁决后发布结果并打包当前 live run 的共享产物。

现有 AT-004 正式 Evidence 中可复核六个 Matrix event ID、独立 human approval、Runner 请求/
响应、五个原始输出、7-entry 哈希链和最终 `CHAIN_OK / ACCEPTED`。正式包没有单独的
`skill_id` 调用事件，因此录制时应在 AgentTeams UI 展示 Worker 实际使用的 Skill；不得仅凭
角色名称反推并宣称“Skill 调用已被 Trace 证明”。

## 3. 环境前置

- Python 3.9+；
- Docker Desktop / Docker Engine；
- 本地构建的 `labops/pytorch-cpu-runner:0.2.0`（项目不分发 Runner 镜像）；
- 已部署并配置好的 HiClaw / AgentTeams；
- Matrix homeserver 与 Element；
- 一个 Manager 和五个 Worker，身份分别映射为六个规范 Agent ID；
- MinIO 或当前 AgentTeams 部署所使用的共享对象存储；
- 本仓库 Runner Gateway；
- 只读 Trust Dashboard。

本仓库不包含 HiClaw、Matrix、Element 或 MinIO 的部署编排，容器名、Matrix room ID、Matrix
端口与对象存储地址由具体 AgentTeams 环境决定。不得在文档、视频或提交包中公开 Token、
密钥或私有 room ID。

## 4. 演示前检查

### 4.1 必须运行或可用的组件

| 组件 | 如何确认 | 固定边界 |
|---|---|---|
| Docker daemon | `docker version` 成功 | 仅宿主 Gateway 持有 Docker 能力 |
| AT-004 Runner image | `docker image inspect labops/pytorch-cpu-runner:0.2.0` | 本地构建，不分发 tar |
| Matrix / Element | 能打开 Manager room 并看到五个 Worker room | 地址和 room ID 由部署决定 |
| AgentTeams Manager | `labops-manager` 在线且能派发 | 只编排和发布，不执行/自证 |
| 五个 Worker | 五个规范 Agent ID 均在线 | 不新增 Agent，不用别名授权 |
| MinIO / shared state | Manager 与 Worker 可读写隔离的录制命名空间 | 不覆盖正式 Evidence |
| Runner Gateway | `http://127.0.0.1:18103/healthz` 返回 `ok=true` | 短生命周期、固定 allowlist |
| Trust Dashboard | `http://127.0.0.1:8787/healthz` 可用 | 只读 Archived Evidence Replay |

### 4.2 提前打开的窗口

1. Element 的 AgentTeams Manager room；
2. 能展示 Worker handoff 的 Matrix/AgentTeams 任务视图；
3. Runner Gateway 终端；
4. MinIO/shared task artifact 页面（隐藏 endpoint、access key 与私有信息）；
5. `http://127.0.0.1:8787/` Trust Dashboard；
6. 一个用于运行 readiness 与 Evidence 验证命令的终端。

### 4.3 启动只读 Dashboard

```powershell
docker compose up -d --build
```

### 4.4 启动短生命周期 Runner Gateway

为本次录制选择一个全新的、非正式输出目录；不得指向 `demo/output-agentteams-at002`、
`at003` 或 `at004`：

```powershell
python -B -m labops.runner_gateway `
  --repo-root . `
  --output-root artifacts/LABOPS-AT-004-recording-01 `
  --host 0.0.0.0 `
  --port 18103
```

`0.0.0.0` 用于让容器内 Worker 通过 `host.docker.internal` 访问 Gateway，只应在受信任的本地
网络和防火墙边界内短时使用，录制后立即停止。Gateway 没有 mTLS/OIDC，不应长期暴露。

### 4.5 运行只读 readiness helper

```powershell
python -B -m labops demo-readiness --service-checks --show-prompt
```

该命令只读取契约、调用正式 Evidence verifier、检查 Docker/镜像和两个健康端点，并打印完整
Manager Prompt。它不会启动服务、发送 Matrix 消息、运行 Agent、创建 Artifact 或修改正式
Evidence。`LOCAL_READY` 仍不代表 AgentTeams 已在线；Matrix、六身份和共享存储必须人工确认。

## 5. AT-004 正常路径

### 步骤 1：确认外部 AgentTeams 服务

按现有 HiClaw / AgentTeams 部署方式启动 Matrix、Element、MinIO、Manager 和五个 Worker。
本仓库没有这些外部组件的一键启动文件，不应猜测或伪造启动命令。确认以下六个身份在线：

```text
labops-manager
evidence-collector
rca-analyst
experiment-planner
safe-executor
verification-auditor
```

录制环境必须把逻辑路径 `shared/tasks/LABOPS-AT-004-EVAL-DRIFT/` 映射到新的 MinIO bucket、
prefix 或一次性共享命名空间，不能连接到 2026-08-04 正式运行所用的归档位置。由于 Task
Contract 和 run ID 已冻结，不允许通过改正式任务文件来解决冲突；应在部署层隔离本次录制。

### 步骤 2：在 Manager room 触发任务

打开配置给 `labops-manager` 的 AgentTeams Manager room。运行 readiness helper 的
`--show-prompt`，把 JSON 中 `task.manager_prompt` 的完整文本原样发送给 Manager。不要只发送
一句“运行 AT-004”，也不要发送正式 Evidence 的历史结论作为答案。

### 步骤 3：观察真实 handoff

预期顺序固定为：

```text
Incident Commander (labops-manager)
  → Evidence Collector
  → RCA Analyst
  → Experiment Planner
  → [separate human approval]
  → Safe Executor
  → Verification Auditor
  → Incident Commander publishes the audited decision
```

每次 handoff 应在 Matrix/AgentTeams UI 中显示真实发送者、接收者、时间、输入 Artifact、输出
Artifact 和 event ID。若某个 Worker 没有被唤醒，应按当前 AgentTeams 运维方式明确启动同一个
Worker；不得补写消息或伪造 event ID。

### 步骤 4：人工审批与 Runner

Planner 产出 `plan.json` 且策略检查通过后，Manager 才请求单独人工审批。批准记录必须包含
approver、decision 和时间，且时间早于 Runner start。随后 Safe Executor 才能调用
`POST /v1/run`。此时在 Gateway 终端展示真实 HTTP 请求日志，并在新的输出目录观察：

```text
gateway_request.json
gateway_response.json
artifact_manifest.json
metrics.json
run_result.json
stdout.log
stderr.log
```

不得让 Worker 自己安装或运行 PyTorch，也不得向 Worker 暴露 Docker socket。

### 步骤 5：Auditor 裁决

Auditor 应从原始 stdout/metrics/manifest 重算：

- baseline：`0.71875 × 3`；
- candidate：约 `0.978124976 × 3`；
- 唯一 changed path：`sandbox/eval_config.json:evaluation.preprocessing_profile`；
- approval 早于执行；
- `network=none`、sandbox-only；
- 六组受保护哈希不变；
- Trace 非空、顺序正确且链完整。

全部满足时，Auditor 才能裁决 `PASS / RESOLVED`；任何缺口都应停在 `BLOCKED` 或
`INCONCLUSIVE`。Manager 只能发布 Auditor 的决定，不能改写终态。

### 步骤 6：查看 Evidence 与 Dashboard

- 当前 live run：查看本次隔离存储命名空间中的逻辑路径
  `shared/tasks/LABOPS-AT-004-EVAL-DRIFT/`、MinIO 页面和本次新的 Gateway 输出目录；
- 历史可复核证据：运行 `python -B scripts/verify_evidence.py`；
- Trust Dashboard：打开 `http://127.0.0.1:8787/`，明确口播“这是对已归档正式 Evidence 的
  只读投影，不是刚才 live run 的实时控制台”。

本次录制产物不得覆盖或替换三个正式 Evidence Bundle。若要归档新运行，应在本任务之外使用
新的 run ID/目录和独立审批流程。

## 6. AT-002 风险路径

AT-002 用于解释异常处理，建议重放正式证据而不是现场制造危险动作：

1. Planner 提议修改受保护的 `metric.py`；
2. Policy 将计划拒绝为 `POLICY_VIOLATION`，不能用人工批准降级放行；
3. 相关操作只发生在隔离的合成 fixture / sandbox 副本；
4. rollback 复核副本的 `metric.py` 哈希已恢复；
5. Auditor 给出 `POLICY_VIOLATION / ROLLED_BACK`，Manager 保持总任务 `BLOCKED`。

必须明确：这是隔离 fixture 的治理案例，不能描述为真实资源已被越权修改，也不能说系统先
篡改了生产指标再恢复。Archived Evidence Replay 不是当前 live execution。

## 7. 录制窗口与镜头顺序

1. **Matrix/AgentTeams Manager room**：任务接收、Manager 编排和角色交接；
2. **Worker/任务视图**：真实角色身份、Skill 使用界面（如部署提供）和结构化产物；
3. **审批事件**：突出 human approval 独立且早于运行；
4. **Runner Gateway 终端**：真实 `/v1/run` 请求和返回；
5. **MinIO / 新输出目录**：原始 Runner Artifact，不展示凭据或绝对主机路径；
6. **Auditor 输出**：独立重算与终态；
7. **Evidence verifier 终端**：三个正式包的 SHA-256、Trace 和 Artifact 校验；
8. **Trust Dashboard**：已归档证据链的只读投影，口播明确 Replay 边界。

不要在同一镜头中用 Archived Replay 替代缺失的实时 Matrix 交接。live 环境不可用时，应明确
切换为备用“已归档证据复核”，而不是继续声称正在运行六 Agent。

## 8. 失败与备用方案

| 失败 | 正确处理 |
|---|---|
| Matrix/Worker 不在线 | 停止 live 口播；明确切换 Archived Evidence Replay |
| Worker 唤醒失败 | 启动同一个 Worker 并保留真实事件；不伪造 handoff |
| Gateway 不健康 | 不批准执行；检查 18103 和新输出目录 |
| Runner image 缺失 | 保持 `BLOCKED`；本地构建后重新 preflight |
| approval 缺失或晚于运行 | Runner 必须拒绝；Auditor 不得 `RESOLVED` |
| Trace/Hash 失败 | 展示失败并保持 `BLOCKED / INCONCLUSIVE` |
| Dashboard 不可用 | 用 `scripts/verify_evidence.py` 和正式包复核；不影响 live Matrix 事实 |

## 9. 录制前最终检查

- [ ] 六个规范 Agent 身份在线；human approval 不计作 Agent；
- [ ] Manager Prompt 来自仓库当前文件；
- [ ] MinIO/shared state 指向隔离的录制命名空间，而非正式运行归档位置；
- [ ] Gateway 输出目录全新且不在三个正式 Evidence 目录中；
- [ ] Runner image 为 `0.2.0`，CPU、`network=none`；
- [ ] Matrix handoff、Gateway 请求、Runner Artifact、Auditor 结论均能入镜；
- [ ] Dashboard 被称为只读 Archived Evidence Replay；
- [ ] AT-002 被称为隔离 fixture 风险案例；
- [ ] 无 Token、密钥、私有 room ID、主机绝对路径或个人信息；
- [ ] 三个正式 Evidence Bundle 的 SHA-256 未变化。
