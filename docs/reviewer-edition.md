# LabOps-Guard Reviewer Edition

Reviewer Edition 是供评委或第三方在本机检查 LabOps-Guard 的只读工作台。它复用正式
Evidence、Trust Contract、Skill Registry、Runner Gateway 和外部 AgentTeams 环境，不创建
第七个 Agent，不发送 Matrix 消息，也不提供审批、执行、重试或状态修改按钮。

## 1. 三种入口与真实性边界

| 入口 | 能看到什么 | 不能声称什么 |
|---|---|---|
| Quick Mode | 已验证 AT-002/003/004 Evidence、六角色流程、Approval、Runner、Trace、Audit | 不是当前实时 AgentTeams 执行 |
| Live Mode | 外部 HiClaw/AgentTeams 与 Matrix 的真实事件、当前非正式 session、Gateway/Runner 证据 | 前置条件缺失时不能显示为 Live，Observer 不能替代 AgentTeams |
| Public Evidence Replay | 脱敏、静态、可公开访问的历史证据摘要 | 不是本地服务，也不是实时运行 |

工作台的数据源状态由实际数据驱动：

- `LIVE`：Matrix observer 最近成功同步，并存在绑定当前 session 的允许列表事件；
- `STALE`：曾成功同步，但最后成功时间超过新鲜度窗口；
- `DISCONNECTED`：当前无法连接真实 Matrix 数据源；
- `REPLAY`：正在查看正式归档 Evidence。

所有模式均保持只读。`CONFIGURED` 只代表契约存在，不代表运行时调用已经发生。

## 2. 通用前置条件

- Python 3.9 或更高版本；
- 在解压后的仓库根目录运行命令；
- 如需安装 CLI：`python -m pip install --no-deps .`；
- 本地端口 `18787` 未被占用；
- 不要把 Token、真实 room ID 或本机绝对路径写入提交包、视频或 Git。

先执行版本锁和提交资产检查：

```powershell
python -B -m labops reviewer pack-check --mode quick
```

固定 AgentTeams v1.1.2、校验和安装辅助、脱敏环境模板和样例输出见
[`reviewer-reproducibility-pack.md`](reviewer-reproducibility-pack.md)。

先确认源码候选可读取：

```powershell
python -B -m labops reviewer preflight --mode quick
```

预期 `status=READY`、`available_modes` 包含 `QUICK`，并且 Trust Contract、AgentTeams Task、
Skill Registry 与三份正式 Evidence 均为 `PASS`。

## 3. Quick Mode：评委首选本地验证

Quick Mode 不要求 Matrix、HiClaw 或 Docker Runner 在线。它读取正式归档 Evidence，并明确标注
`REPLAY`。

### Windows PowerShell

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_reviewer_demo.ps1 -Mode quick
```

### Linux / macOS

```bash
chmod +x scripts/start_reviewer_demo.sh
./scripts/start_reviewer_demo.sh quick
```

浏览器打开：

```text
http://127.0.0.1:18787/reviewer
```

启动进程保持在前台并负责清理。可按 `Ctrl+C` 停止，也可以从另一个终端请求优雅停止：

```powershell
python -B -m labops reviewer status
python -B -m labops reviewer stop
```

Quick Mode 中应看到六角色流程、独立 Human Approval Gate、Tool Contract、Recovery 配置、
Timeline drill-down、Runner 和 Auditor 结果。完整 ID、event、artifact 与 hash 位于只读详情中。

## 4. 可选 Compose Quick 包装

`compose.reviewer.yaml` 只运行 Quick Replay，不假装容器内具备外部 AgentTeams 或宿主 Docker
执行权限。它将三份正式 Evidence 与 `demo/live-sessions` 以只读方式挂载，运行时状态仅写入
容器临时目录。

该包装在容器内部使用显式 bridge bind，但宿主端口固定发布到
`127.0.0.1:18787:18787`，不会监听宿主机全部网卡。原生 PowerShell/Shell 模式仍直接绑定
本机 loopback；`--container-bind` 仅供该 Compose 包装使用。

如果已经通过稳定 `compose.yaml` 构建过 `labops-guard:local`，可直接离线复用该镜像；当前
Reviewer 源码和契约目录仍以只读方式从仓库挂载：

```powershell
docker compose -f compose.reviewer.yaml up
```

首次使用且本机没有 `labops-guard:local` 时，可在能够访问基础镜像仓库的环境执行一次
`docker compose build labops-guard`。若不能访问镜像仓库，直接使用第 3 节原生启动方式，
Quick Mode 本身不要求 Docker。

停止并移除可选容器：

```powershell
docker compose -f compose.reviewer.yaml down
```

该 Compose 文件不接收 Matrix Token，也不提供 Live Mode。

## 5. Live Mode：真实 AgentTeams 观察

Live Mode 额外要求：

- Docker daemon 可用；
- 本地存在 `labops/pytorch-cpu-runner:0.2.0`；
- HiClaw / AgentTeams、Matrix、Element、Manager 与五个 Worker 已真实部署；
- 六个规范角色对应六个真实 Matrix room；
- 使用新的 `NON_FORMAL_LIVE_DEMO` session；
- Human Approval 由真人触发；
- Gateway、Runner Artifact 与 Verification Auditor 证据能够绑定同一 session。

复制本地 room map 模板并替换为当前部署的真实 room ID：

```powershell
Copy-Item config/reviewer-room-map.example.json config/reviewer-room-map.json
```

`config/reviewer-room-map.json` 已被 Git 忽略。不要修改或提交 `.example.json` 来保存真实 room。
模板中的 `example.invalid` 是故意不可运行的占位值，直接复制而不替换时，preflight 必须返回
`MATRIX_ROOM_MAP_INVALID`。在 Element 中依次打开六个真实会话的“房间信息 / 设置 / 高级”，复制
以 `!` 开头的 **Internal room ID**；不要填写 `#` 开头的 room alias，也不要填写浏览器 URL。

### Windows 环境变量

```powershell
$env:LABOPS_MATRIX_HOMESERVER = "http://127.0.0.1:18080"
$env:LABOPS_MATRIX_ACCESS_TOKEN = "<local-token>"
$env:LABOPS_MATRIX_ROOM_MAP = (Resolve-Path config/reviewer-room-map.json).Path
python -B -m labops reviewer pack-check --mode live
python -B -m labops reviewer preflight --mode live
```

只有 preflight 返回 `READY` 后才启动新的 session：

```powershell
& scripts/start_reviewer_demo.ps1 `
  -Mode live `
  -ReviewerArgs @("--session", "20260831-001")
```

### Linux / macOS

```bash
export LABOPS_MATRIX_HOMESERVER="http://127.0.0.1:18080"
export LABOPS_MATRIX_ACCESS_TOKEN="<local-token>"
export LABOPS_MATRIX_ROOM_MAP="$(pwd)/config/reviewer-room-map.json"
./scripts/start_reviewer_demo.sh live --session 20260831-001
```

Reviewer CLI 会创建或校验隔离的非正式 session，启动短生命周期 Gateway、只读 Matrix
Observer 与 Workbench。Helper 不会发送任务、不批准计划，也不会模拟 Worker 消息。

## 6. Live Mode 中必须由真人完成的步骤

1. 在 Element 中确认 `labops-manager` 和五个 Worker 在线；
2. 真人把当前 session 的 `manager_task.md` 发送到 Manager room；
3. 观察真实 Matrix handoff 与 AgentTeams 状态变化；
4. Planner 产出计划后，由独立真人检查并批准；
5. Safe Executor 通过 Gateway 调用受控 Runner；
6. Verification Auditor 读取原始产物并独立裁决；
7. Manager 只发布 Auditor 已给出的结果；
8. 执行 `live-demo verify`，不能用工作台状态替代 Evidence 验证。

完整 AT-004 与 AT-002 操作步骤见 [`final-demo-guide.md`](final-demo-guide.md)。

## 7. 预期输出与验证

工作台地址：

```text
http://127.0.0.1:18787/reviewer?session=20260831-001
```

终端验证：

```powershell
python -B -m labops live-demo verify --session 20260831-001
python -B scripts/verify_evidence.py
```

Live preflight 会通过 Matrix `joined_rooms` 接口确认当前 Token 已加入配置的六个 room；Observer
首次 `/sync` 会再次执行同一 fail-closed 门禁。配置格式正确但房间未加入时返回
`MATRIX_ROOM_MAP_UNJOINED`，不会显示 `LIVE`。

Live 验证只有在真实六角色 Matrix 事件、Approval、Gateway 请求、Runner Artifact 与 Auditor
结论全部存在且交叉绑定时才能通过。缺少任何一项都必须显示 `BLOCKED`。Recovery event 不能
替代 AgentTeams handoff，人工也不能直接写 `RESOLVED`。

## 8. 失败、降级与关闭

| 情况 | 正确处理 |
|---|---|
| Matrix/HiClaw 未配置 | 使用 Quick Mode，不称为 Live |
| Docker 或 Runner 镜像缺失 | Live preflight 返回 `BLOCKED`；不要绕过 |
| room map 不完整 | 修复本地配置；不要补写虚假 room/event |
| room map 仍是模板 | 用 Element 的 Internal room ID 替换全部 `example.invalid` 值 |
| `MATRIX_ROOM_MAP_UNJOINED` | 确认 Token 所属账号已加入六个真实 room，且未误填 alias/URL |
| Agent/证据不完整 | 保持 `BLOCKED`，按 Recovery/Human Takeover 流程处理 |
| 现场网络或 UI 故障 | 使用 Quick Replay、Public Demo、视频和 Evidence verifier |

录制或验证结束后停止 Reviewer，并清除当前终端中的 Token：

```powershell
python -B -m labops reviewer stop
Remove-Item Env:LABOPS_MATRIX_ACCESS_TOKEN -ErrorAction SilentlyContinue
```

Reviewer Edition 不修改 AT-002/003/004 正式 Evidence，也不把非正式 session 合并进正式包。
