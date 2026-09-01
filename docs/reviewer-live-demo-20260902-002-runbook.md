# LabOps Guard · Agent Mission Control 全流程录制指南

本指南只用于全新的 `NON_FORMAL_LIVE_DEMO` 会话 `20260902-002`。目标是现场展示：

1. 六个真实 Agent 在各自 Matrix 房间完成六次 Handoff；
2. 一次由真人独立作出的精确审批；
3. Safe Executor 通过受控 Gateway 启动隔离 Runner；
4. Verification Auditor 独立复算；
5. Reviewer 先显示“已观察”，只有完整 Evidence 通过后才显示“已验证”。

Reviewer 始终只读。它不发消息、不审批、不调用 Runner，也不修改 AgentTeams 原始产物。

## 一、录制前必须知道的最终状态

这是一个真实运行的沙箱实验，但事故场景本身是非生产演示。因此最终正确口径是：

```text
Auditor decision = PASS
demo_verification = PASSED
incident_state = DEMO_PASSED_NOT_RESOLVED
underlying_issue_resolved = false
```

它表示“演示链路、受控执行和验收判据全部通过”，不表示某个真实生产系统已经被修复。
页面中的事故指挥官应显示“结果已发布”，Auditor 应显示“审计通过”；二者都不能把事故改成
`RESOLVED` 或 `CLOSED`。

## 二、准备三个 PowerShell 窗口

三个窗口都先进入当前工作树：

```powershell
Set-Location -LiteralPath "C:\Users\lenovo\Documents\AI开源大赛-AI Infra\.worktrees\labops-guard-phase6-8"
```

### 窗口 A：Reviewer 与实时观察器

设置只在当前 PowerShell 生效的 Matrix 读取配置。下面的命令从已运行的 Manager 容器读取
Token，但不会把 Token 打印出来；录屏时不要展示环境变量内容。

```powershell
$env:LABOPS_MATRIX_HOMESERVER = "http://127.0.0.1:18080"
$env:LABOPS_MATRIX_ACCESS_TOKEN = (
  docker exec hiclaw-manager sh -lc "jq -r '.channels.matrix.accessToken' /root/manager-workspace/openclaw.json"
).Trim()
$env:LABOPS_MATRIX_ROOM_MAP = (Resolve-Path "config/reviewer-room-map.json").Path

if ([string]::IsNullOrWhiteSpace($env:LABOPS_MATRIX_ACCESS_TOKEN)) {
  throw "Matrix access token is unavailable"
}

python -B -m labops reviewer preflight --mode live
```

预期结果：`status` 为 `READY`，`missing_requirements` 为空，Manager、五个 Worker、Docker、
room map、membership 和 Runner contract 均为 `PASS`。

随后启动 Reviewer，并保持此窗口不关闭：

```powershell
& .\scripts\start_reviewer_demo.ps1 `
  -Mode live `
  -ReviewerArgs @("--session", "20260902-002", "--no-browser")
```

看到 `status: RUNNING` 后打开：

```text
http://127.0.0.1:18787/reviewer?session=20260902-002
```

初始预期：

- 已观察 Handoff：`0/6`；
- 已验证 Handoff：`0/6`；
- Evidence：等待远端产物；
- Incident Commander 为当前节点，其余 Agent 未开始；
- 初始 Attempt 不得显示成 Recovery Attempt。

### 窗口 B：短生命周期 Runner Gateway

```powershell
python -B -m labops.runner_gateway `
  --repo-root . `
  --output-root "demo/live-sessions/20260902-002/gateway-runs" `
  --host 0.0.0.0 `
  --port 18103
```

保持此窗口不关闭。另开一个临时命令行确认：

```powershell
Invoke-RestMethod "http://127.0.0.1:18103/healthz"
```

预期 `ok = true`，并能看到 AT-004 Runner image。`0.0.0.0` 仅用于本机容器经
`host.docker.internal` 访问，录制结束后立即停止 Gateway。

### 窗口 C：只读复核与结束验收

窗口 C 暂时保持空闲，最后用它运行独立验证命令。不要在这里打印 Token、完整 room ID 或
容器环境变量。

## 三、真人动作一：向 Manager 发送完整任务

打开 Element 的 `Manager: default` 房间。用记事本打开：

```powershell
notepad ".\demo\live-sessions\20260902-002\manager_task.md"
```

复制文件的全部内容并由真人原样发送。不要只发“运行 AT-004”，也不要删掉开头的 session
绑定、事件契约或 Evidence 文件契约。

发送任务本身不计入 Handoff。真正的 Manager 以自己的身份派发 Evidence Collector 后，页面才
应从 `0/6` 变为 `1/6`。

## 四、观察前四次 Handoff

页面应随着规范 Matrix 事件逐步更新，而不是等到最后一次性播放：

| 已观察数 | 真实交接 | 规范事件 | 页面预期 |
|---:|---|---|---|
| 1/6 | Incident Commander → Evidence Collector | `manager_to_collector` | Commander 已观察，Collector 开始 |
| 2/6 | Evidence Collector → RCA Analyst | `collector_to_rca` | Collector 已观察，RCA 开始 |
| 3/6 | RCA Analyst → Experiment Planner | `rca_to_planner` | RCA 已观察，Planner 开始 |
| 4/6 | Experiment Planner → Safe Executor 审批门 | `approval_pending` | Planner 已观察，人工审批待处理 |

每条交接必须由对应 Agent 在对应房间发出，并包含同一个 session、task、incident、attempt、
run 五个绑定，以及一条输入 Artifact 和一条输出 Artifact。Manager 代替 Worker 发消息、错误
Attempt、缺少 Artifact 或重复事件都不会被 Reviewer 接受。

“已验证 Handoff”此时仍可能保持 `0/6`，这是正确行为。Reviewer 会先保留通过 sender/room/
binding 校验的观察记录，只有完整外部 Evidence 全部到齐并独立通过后，才原子提升为 `6/6`。

## 五、真人动作二：精确人工审批

只有 Planner 已产生最终 Plan，且 Manager 展示了以下全部值后才能审批：

- `approval_id`；
- `plan_id`；
- canonical Plan SHA-256；
- 精确 run ID；
- 唯一允许修改的字段；
- CPU、无网络、30 秒、三次重复的预算；
- 受保护资源；
- 批准时间、过期时间与一次性 nonce。

不要只回复“可以执行”或单独一个 `APPROVED`。在 Manager 房间由当前真人账号发送下面的模板，
把尖括号内容替换为 Manager 当前审批请求中的精确值，不能自行猜测：

```text
Human Approval Decision — session 20260902-002

session_id: 20260902-002
task_instance_id: LIVE-TASK-20260902-002
incident_instance_id: LIVE-INCIDENT-20260902-002
attempt_id: LIVE-ATTEMPT-20260902-002-01
run_id: RUN-LABOPS-AT-004-AGENTTEAMS-002

LABOPS_EVENT_KIND: approval_granted
LABOPS_ACTOR: human-approver

decision: APPROVED
approval_id: <Manager 给出的 approval_id>
plan_id: <Manager 给出的最终 plan_id>
canonical_plan_sha256: <Manager 给出的 64 位 SHA-256>
approved_scope: <必须只有 evaluation.preprocessing_profile 的单一变更>
resource_budget: <CPU / network none / <=30 seconds / 3 repeats>
protected_resources: <Manager 给出的完整受保护资源列表>
approved_at: <当前批准时间>
expires_at: <Manager 给出的过期时间>
nonce: <Manager 给出的一次性 nonce>

Create the exact ApprovalGrant artifact under the session namespace. Dispatch
Safe Executor only after this exact binding is validated. Do not approve any
earlier plan, do not reuse the nonce, and do not let Manager author or alter this
human decision.
```

人工审批是阶段事件，不是第 5 次 Agent Handoff。因此发送后 Handoff 数仍可能是 `4/6`，但人工
审批门应显示已观察/已批准。若账号本身是某个 Agent 的运行身份，Observer 会拒绝它；必须使用
独立的真人账号。

## 六、观察受控执行、Auditor 与最终发布

审批通过后，不再需要你手动告诉 Manager“继续”。正确链路应自动进行：

1. Safe Executor 发送 `executor_to_gateway`；
2. Gateway 验证 Plan Hash、Approval Binding、有效期和 nonce；
3. Safe Executor 发送 `runner_started`；
4. Runner 在无网络沙箱真实计算三次候选指标；
5. Safe Executor 保存原始输出，不改写 `run_result.json`，另写演示分类 `status.json`；
6. Safe Executor 发送 `runner_completed` 与 `executor_to_auditor`，Handoff 变为 `5/6`；
7. Verification Auditor 独立读取原始 metrics/stdout/manifest 并复算；
8. Auditor 发送 `verification_completed`，Handoff 变为 `6/6`；
9. Auditor 发送 `terminal_decided`；
10. Manager 仅在 Auditor 之后发送 `commander_published`。

正确的指标展示为：baseline `0.71875 × 3`，candidate 约 `0.978125 × 3`。这不是在网页上
直接改数字：Runner 必须生成原始 stdout、metrics 和 manifest；Auditor 从原始文件重算，并验证
只有 preprocessing profile 改变、保护哈希未变、网络为 none、审批早于执行且 nonce 只使用一次。

最终页面预期：

- 已观察 Handoff：`6/6`；
- 已验证 Handoff：`6/6`；
- Evidence 同步：已验证；
- 人工审批：已验证；
- Safe Executor：受控执行完成；
- Verification Auditor：审计通过；
- Incident Commander：结果已发布；
- 事故状态：演示验证通过（未解决），机器状态
  `DEMO_PASSED_NOT_RESOLVED`。

## 七、最终独立验收

在窗口 C 执行：

```powershell
python -B -m labops live-demo verify --session 20260902-002
```

唯一可接受的成功结果是：

```text
status = VERIFIED
errors = []
effective_attempt_id = LIVE-ATTEMPT-20260902-002-01
```

然后确认三份正式 Evidence 未被此次演示修改：

```powershell
python -B scripts/verify_evidence.py
```

预期 AT-002、AT-003、AT-004 全部继续 PASS。

## 八、录制中出现阻断时怎么处理

| 现象 | 含义 | 正确动作 |
|---|---|---|
| 已观察数不增加 | sender、room、五绑定、事件类型或 Artifact 行不合法 | 查看对应 Agent 的真实消息；不要人工补写 event |
| 已观察增加、已验证仍为 0 | Matrix 交接可信，但外部 Evidence 尚未完整通过 | 等待远端文件；查看 Evidence Inspector 的脱敏错误码 |
| `EVIDENCE_INCOMPLETE` | 约定文件尚未到齐 | 等待真实 Agent 产出，不复制旧会话文件 |
| `EVIDENCE_SCHEMA_INVALID` | 文件存在但结构不符合合同 | 停止本次 take；不得手改 canonical Evidence 伪造通过 |
| `EVIDENCE_BINDING_MISMATCH` | 文件属于错误 session/attempt/run | 停止本次 take，不能复用该文件 |
| Matrix 短暂波动 | 15 秒内仍保留已观察进度 | 等待恢复，不重发已完成 Handoff |
| 真实 Agent 失败 | 进入 Recovery/Human Takeover，而非正常审批 | 不把 Takeover 当成 Approval；录屏前决定是否另开全新 session |

如果已经产生错误、重复或冲突的可信事件，不要为了画面好看修改历史。终止该 take，保留失败证据，
修正合同后使用下一个全新 session。绝不向 `20260902-002` 补写或伪造 Matrix event。

## 九、录制结束后的安全收尾

1. 在 Reviewer 窗口按 `Ctrl+C`；
2. 在 Gateway 窗口按 `Ctrl+C`；
3. 在设置 Token 的 PowerShell 中清除当前进程环境变量：

```powershell
Remove-Item Env:LABOPS_MATRIX_ACCESS_TOKEN -ErrorAction SilentlyContinue
```

4. 检查视频中是否出现 Token、完整私有 room ID、用户名、个人路径或系统通知；
5. 不删除本次 session 的 Evidence，也不覆盖正式 AT-002/003/004 证据。

## 十、建议录屏画面

主画面只展示 Agent Mission Control。Element 仅在三个关键时刻切入：发送 Manager task、Planner
请求审批、真人发送精确 Approval。Gateway 终端只短暂展示健康状态与一次受控请求；不要长时间
展示六个房间的内部推理文本。这样评审看到的是业务链路、责任边界和可验证 Evidence，而不是
杂乱聊天记录。
