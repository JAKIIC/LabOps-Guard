# Reviewer Reproducibility Pack

本手册面向第一次拿到源码包的评委。目标是先在无凭据环境验证 Quick Replay，再在满足真实
AgentTeams 前置条件时启动 Live Observer。任何缺失项都必须显式降级，不能用脚本生成的消息
或归档数据冒充实时运行。

## 1. 固定版本与边界

机器可读锁位于 `config/reviewer-runtime-lock.json`，Schema 位于
`schemas/reviewer_runtime_lock.schema.json`。当前冻结组合为：

| 组件 | 固定值 | 说明 |
|---|---|---|
| AgentTeams | `v1.1.2` | 历史实机采用 legacy HiClaw deployment contract |
| LabOps Guard | `1.0.0rc1` | Python `>=3.9` |
| AT-004 Runner | `labops/pytorch-cpu-runner:0.2.0` | Python `3.11.15`、PyTorch `2.5.1+cpu`、运行时断网 |
| Matrix/Element/MinIO/Gateway | 随 AgentTeams v1.1.2 内置 | 不猜内部镜像版本；新 live session 记录实际 image ID |

AgentTeams 使用 Apache-2.0。源码包不复制 AgentTeams、LLM 凭据或 Runner image tar。

## 2. 干净环境最低要求

- Windows 10/11 + PowerShell 7，或 Linux/macOS + POSIX shell；
- Python 3.9–3.12；
- Quick Mode：约 1 GB 可用空间，不要求 AgentTeams、Matrix 或 Docker；
- Live Mode：Docker Desktop/Engine、至少 4 CPU/8 GB RAM、AgentTeams v1.1.2、Manager、五个
  Worker、六个 Matrix room、固定 Runner image 和本地授权的模型服务；
- Live 使用端口 `18080`、`18088`、`18103`、`18787`，不得暴露到公网。

## 3. 第一步：验证源码和 Quick Mode

从解压后的仓库根目录执行：

```powershell
python -m pip install --no-deps .
python -B -m labops reviewer pack-check --mode quick
python -B scripts/verify_evidence.py
```

`pack-check` 必须返回 `status=READY`。示例见
[`samples/reviewer-pack-check-quick.json`](samples/reviewer-pack-check-quick.json)。

启动只读工作台：

```powershell
pwsh -File scripts/start_reviewer_demo.ps1 -Mode quick
```

打开 `http://127.0.0.1:18787/reviewer`。Quick 页面必须显示 `REPLAY`，而不是 `LIVE`。

另一个终端可查看或停止：

```powershell
python -B -m labops reviewer status
pwsh -File scripts/stop_reviewer_demo.ps1
```

Linux/macOS 使用 `scripts/start_reviewer_demo.sh quick` 和
`scripts/stop_reviewer_demo.sh`。

## 4. 第二步：获取并核验 AgentTeams 安装器

安装辅助从机器可读锁读取版本、官方 URL 和 SHA-256。默认只下载并校验，不执行：

```powershell
pwsh -File scripts/install_agentteams_reviewer.ps1
```

预期返回：

```json
{"status":"VERIFIED_DOWNLOAD","version":"v1.1.2","executed":false,"source":"OFFICIAL_VERSIONED_URL"}
```

核对结果后，真人显式确认版本才允许进入官方交互安装器：

```powershell
pwsh -File scripts/install_agentteams_reviewer.ps1 -Execute -ConfirmVersion v1.1.2
```

安装器会交互读取模型与管理员凭据。不得把这些值放入命令历史、`.env.example`、Git、Evidence
或录屏。本辅助不代替官方安装器，也不自动卸载 AgentTeams 数据。

官方来源：

- <https://github.com/agentscope-ai/AgentTeams/releases/tag/v1.1.2>
- <https://github.com/agentscope-ai/AgentTeams/blob/v1.1.2/install/hiclaw-install.ps1>

## 5. 第三步：配置本地 Live 环境

复制模板；两个目标文件均不得提交：

```powershell
Copy-Item config/reviewer.env.example .env.reviewer.local
Copy-Item config/reviewer-room-map.example.json config/reviewer-room-map.json
```

将六个真实 room ID 写入 `config/reviewer-room-map.json`。在当前终端加载本地值：

- 模板中的 `example.invalid` 只用于说明字段，不能直接运行；
- 在 Element 的“房间信息 / 设置 / 高级”中复制以 `!` 开头的 Internal room ID；
- 不要使用 `#` 开头的 room alias，也不要复制浏览器地址；
- 当前 Token 对应的 Matrix 账号必须已经加入这六个 room。

```powershell
$env:LABOPS_MATRIX_HOMESERVER = "http://127.0.0.1:18080"
$env:LABOPS_MATRIX_ACCESS_TOKEN = "<local-read-only-token>"
$env:LABOPS_MATRIX_ROOM_MAP = (Resolve-Path config/reviewer-room-map.json).Path
```

环境文件只是填写提示，项目不会自动读取并回显凭据。

## 6. 第四步：部署并核验七个 LabOps Skill

七个 Skill 随本仓库提供，但 AgentTeams 官方安装器不会自动把它们放进各角色的 OpenClaw
workspace。先执行只读计划，确认固定版本、六个 runtime identity、角色别名和七个 Skill 的
Owner 关系：

```powershell
python -B -m labops agentteams-skills plan
```

只有六个 AgentTeams 容器均以 `v1.1.2` 运行时，真人才显式确认部署：

```powershell
python -B -m labops agentteams-skills deploy --confirm-version v1.1.2
python -B -m labops agentteams-skills verify
```

部署器先检查全部容器、版本和已有 binding；任一目录存在不同 binding 时会在复制前整体阻断，
不会覆盖未知 Skill。每份部署副本包含 `LABOPS_RUNTIME_BINDING.json`，绑定 Skill ID、SemVer、
规范 Owner、runtime identity、`SKILL.md`/I/O Schema 哈希和部署清单哈希。`verify` 会从六个容器
重新读取 binding 与文件哈希，并通过 `openclaw skills list --json` 确认实际发现七个 Skill。

这里的 `discovery=VERIFIED` 只证明 Skill 已被目标 Agent runtime 发现，**不等于本次 incident
已经调用它**。报告必须继续显示 `invocation=UNVERIFIED` 和
`runtime_event_emission=NOT_IMPLEMENTED`；不得把安装/发现证据冒充调用 Trace，也不得回填历史
AT-002/003/004 Evidence。

## 7. 第五步：构建固定 Runner 并检查 Live

若本机尚无固定 Runner，在能够访问基础镜像和 PyTorch wheel 的准备环境构建：

```powershell
docker build -f runner/Dockerfile.at004 -t labops/pytorch-cpu-runner:0.2.0 runner
```

运行严格检查：

```powershell
python -B -m labops reviewer pack-check --mode live
python -B -m labops reviewer preflight --mode live
```

Live `pack-check` 核对：Docker、Runner 标签、AgentTeams Controller、Manager、至少五个 Worker、
Matrix URL、只读 Token、六角色 room map 及真实 joined-room membership。它只输出状态和数量，不输出 Token、room ID、容器
环境变量或绝对路径。

当前外部服务未运行时的真实降级样例见
[`samples/reviewer-pack-check-live-blocked.json`](samples/reviewer-pack-check-live-blocked.json)。

## 8. 第六步：启动真实 Live Observer

只有两个检查都为 `READY` 时执行：

```powershell
pwsh -File scripts/start_reviewer_demo.ps1 `
  -Mode live `
  -ReviewerArgs @("--session", "20260831-001")
```

真人仍必须在 Element 中发送任务并完成 Approval。Reviewer 只读观察 Matrix、Gateway、Runner、
Recovery 和 Auditor 证据，不发送消息、不批准、不执行、不补写事件。

### 8.1 答案盲测的动态异常会话

为证明 AgentTeams 会因证据缺口改变路径，而不是只重放 AT-004 固定成功链，可准备一条新的、
不可覆盖的 Reviewer incident：

```powershell
python -B -m labops reviewer-incident prepare --session 20260831-091
python -B -m labops reviewer-incident status --session 20260831-091
```

`prepare` 只生成初始事故包、Manager 任务和 operator-only 的 withheld evidence；Manager 任务中
不含缺失配置值或预期最终指标。它不发送 Matrix 消息、不接受接管、不批准计划，也不调用
Runner。真人把新 session 的 `manager_task.md` 发到真实 Manager room，并保持 Reviewer Live
Observer 运行。Evidence Collector 必须在真实 Matrix 中发出 session-bound
`LABOPS_EVENT_KIND: evidence_incomplete`；否则状态保持 `WAITING_FOR_AGENTTEAMS_GAP`。

确认该事件后，归档 Manager 的 `CAPABILITY_MISSING` 决策。没有真实备用 Worker 时，系统只能
产生 `REASSIGN_UNAVAILABLE → HUMAN_TAKEOVER`：

```powershell
python -B -m labops recovery request `
  --session 20260831-091 `
  --failure-type CAPABILITY_MISSING `
  --failed-role evidence-collector `
  --failed-worker-id evidence-collector-primary `
  --requested-by labops-manager `
  --source-ref observer/normalized_events.jsonl
```

真人使用 `labops recovery accept` 接受返回的 takeover ID 后，只有同一人工 owner 可以释放缺失
证据。`--confirm` 必须逐字重复 takeover ID：

```powershell
python -B -m labops reviewer-incident release `
  --session 20260831-091 `
  --takeover-id TAKEOVER-20260831-091-01 `
  --released-by human-operator `
  --confirm TAKEOVER-20260831-091-01

python -B -m labops recovery resume `
  --session 20260831-091 `
  --takeover-id TAKEOVER-20260831-091-01 `
  --resumed-by human-operator `
  --resume-point EVIDENCE_COLLECTING `
  --confirm TAKEOVER-20260831-091-01
```

Evidence Collector 重新收集后，Manager 必须在真实 Matrix 中产生新的 session-bound
`manager_to_collector` redispatch，之后才继续 RCA、Plan、独立 Human Approval、Gateway/Runner
和 Auditor。`reviewer-incident status` 在流程尚未满足时有意返回退出码 `2`，表示真实性门禁尚未
通过，不代表它伪造后续步骤。调用状态始终保持事实分层：七个 Skill 的部署与发现可核验；没有
native invocation hook 的 Skill 仍为 `UNVERIFIED`，不得用角色消息替代 Skill 调用证据。

结束后：

```powershell
pwsh -File scripts/stop_reviewer_demo.ps1
Remove-Item Env:LABOPS_MATRIX_ACCESS_TOKEN -ErrorAction SilentlyContinue
```

## 9. 故障诊断

| 缺口/错误 | 处理 |
|---|---|
| `RUNTIME_LOCK_INVALID` | 恢复提交包中的锁和 Schema；禁止使用 `latest` |
| `RUNNER_IMAGE_MISSING` | 构建固定 0.2.0 image；不要改成未验证 tag |
| `RUNNER_CONTRACT_MISMATCH` | 检查 image labels、CPU PyTorch 和 `network-runtime=none` |
| `AGENTTEAMS_CONTROLLER_MISSING` | 检查固定版本安装和 Controller 日志 |
| `AGENTTEAMS_MANAGER_MISSING` | 检查 Manager 状态与模型连通性 |
| `AGENTTEAMS_WORKERS_INSUFFICIENT` | 确认五个现有角色 Worker 真实 Running；不要模拟 Worker |
| `Runtime Skill conflict` | 停止部署并人工核对目标 workspace；不要覆盖未知 Skill 或删除其证据 |
| `OpenClaw did not discover` | 核对固定版本、Owner 映射与 Skill 目录；不能把部署成功描述为调用成功 |
| `MATRIX_*_MISSING/INVALID` | 修复本地变量或脱敏 room map；不要提交真实值 |
| `MATRIX_ROOM_MAP_UNJOINED` | 用真实 Internal room ID 替换模板值，并确认 Token 账号已加入全部 room |
| `MATRIX_ROOM_MEMBERSHIP_UNVERIFIED` | 检查 Matrix 可达性、Token 权限和 `/joined_rooms` 响应后再启动 Live |
| Matrix/Agent 不稳定 | 停止 Live 口播，切换 Quick/Public Replay，并明确标注降级 |

可使用官方只读诊断命令检查服务名和日志；输出在公开前必须脱敏：

```powershell
docker ps --filter name=hiclaw
docker logs --tail 200 hiclaw-controller
docker logs --tail 200 hiclaw-manager
```

## 10. 模式真实性速查

| 模式 | AgentTeams 实时执行 | 可作为运行证据 |
|---|---:|---|
| Public Evidence Replay | 否 | 仅归档脱敏证据 |
| Reviewer Quick | 否 | 正式 Evidence 的本地重新验证 |
| Reviewer Live | 是，前提全部满足时 | 真实 Matrix + Gateway + Runner + Auditor |

任何模式均不得修改 AT-002/003/004 正式 Evidence。
