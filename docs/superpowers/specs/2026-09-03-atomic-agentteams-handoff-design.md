# LabOps Guard 原子化 AgentTeams Handoff 与单次触发 Demo 设计

**日期：** 2026-09-03

**状态：** 待用户确认

**适用范围：** `NON_FORMAL_LIVE_DEMO` 实时演示链路

**目标体验：** 用户发送一次 `manager_task.md`，六个 Agent 自动推进；用户只在 Human Approval 阶段作出一次真实审批，随后系统自动完成执行、审计与收尾。

## 1. 背景与问题陈述

Session `20260902-002` 暴露的核心问题不是模型没有产出业务结果，而是 AgentTeams 的业务产物与 Reviewer 的可信事件流没有形成可靠闭环：

- Evidence Collector 已生成 `collector-report.json`，且内容表明 Evidence 已就绪。
- Worker 在 Matrix 中输出了自然语言、流式片段和编辑消息，但没有稳定发出 Observer 所要求的单条、完整、可验证事件。
- Reviewer 严格校验 sender、room、session/task/incident/attempt/run 绑定、事件类型与 artifact 路径，因此正确拒绝了不完整或错误归属的消息。
- Manager 只能依赖后续 heartbeat/history 才看到部分结果，导致约二十分钟延迟，而不是完成一个阶段后立即调度下一阶段。
- 后续消息还出现事件类型沿用错误：Planner 没有以自己的身份发出 `approval_pending`，Manager 也不能代替 Planner 发出该事件。
- 当前 `agentteams-skills verify` 明确报告 `runtime_event_emission: NOT_IMPLEMENTED`，但 Reviewer preflight 仍可返回 `READY`。
- Manager 状态中保留多个过期 live-demo active task，且三位数 Run 序号可能跨日期碰撞。

因此，Session `20260902-002` 保留为失败演练证据，不继续审批，也不人为补写 Observer 记录。修复目标是让真实 Matrix 事件成为自动编排和 Reviewer 展示的共同事实来源。

## 2. 设计原则

1. **真实优先：** 每个 Handoff 必须由实际承担该角色的 Matrix/OpenClaw 身份发送。
2. **原子消息：** 一个完成事件必须一次发送完整，不依赖流式回复、编辑事件或自然语言推断。
3. **严格 Observer：** 不放宽 `matrix_observer.py` 的 sender、room、binding 和 artifact 校验。
4. **单次触发：** 初始任务发送后，除 Human Approval 外，不要求用户补发“继续”“检查一下”等消息。
5. **人工边界清晰：** 人只审批已生成的精确方案；Manager 和 Worker 不得自批。
6. **Evidence 不可伪造：** 不人工补写 `normalized_events.jsonl`，不构造虚假 Matrix `event_id`，不修改原始 Matrix 事件。
7. **正式证据隔离：** AT-002/003/004 Evidence Bundle 始终只读；所有新产物只进入独立 live-demo namespace。
8. **失败关闭：** 无法证明运行时事件能力、身份绑定或环境干净时，preflight 必须阻止录制。

## 3. 目标与非目标

### 3.1 目标

- 为现有 AgentTeams Skills 增加可部署、可校验的原子 Handoff Emitter。
- 将角色、事件类型、Matrix room、运行绑定和 artifact 路径在发送前强校验。
- 让 Manager 在收到合法阶段事件后立即调度下一角色。
- 将一次真实 Human Approval 作为唯一人工暂停点。
- 让 Reviewer 按真实事件逐步显示 1/6 → 2/6 → 3/6 → 4/6 → 5/6 → 6/6。
- 在正式录屏前识别运行时能力缺失、陈旧任务和 Run ID 冲突。
- 提供安全的失败演练归档方式，保留原始 Evidence。

### 3.2 非目标

- 不把 Reviewer 改成控制台；Reviewer 保持只读。
- 不让 Reviewer 发送 Matrix 消息、审批方案、重试任务或修改状态。
- 不弱化现有事件合同来兼容自由文本。
- 不声称模拟执行已经修复真实生产事故；终态语义仍遵守现有 LabOps 合同。
- 不修改 Gateway、Runner、正式 AT-002/003/004 Evidence 的业务语义。
- 不通过硬编码 Token、伪造 event ID 或直接改投影文件来制造“亮灯”效果。

## 4. 目标用户流程

### 4.1 录制前

1. 启动 AgentTeams、Matrix 与所需容器。
2. 设置当前 PowerShell 会话的 Matrix homeserver、访问凭据和 room map。
3. 执行 live preflight。
4. 只有 preflight 返回 `READY` 才创建新 session 并启动 Reviewer。
5. Reviewer 在任何 Manager 任务发送前已经开始实时观察。

### 4.2 自动阶段

1. 用户向 Manager 发送一次由系统生成的 `manager_task.md`。
2. Incident Commander 原子派发 Evidence Collector，Reviewer 显示 1/6。
3. Evidence Collector 校验并交接给 RCA Analyst，显示 2/6。
4. RCA Analyst 输出根因排序并交接给 Experiment Planner，显示 3/6。
5. Experiment Planner 输出单变量方案及绑定，并发出 `approval_pending`，显示 4/6。
6. 系统暂停在 Human Approval，不再自动向前执行。

### 4.3 唯一人工动作

用户检查 Plan ID、Plan Hash、Approval Binding、执行范围和有效期，在 Element 中发送一次系统给出的完整审批块。该消息必须来自非 Agent 的人工账号，并包含 `LABOPS_ACTOR: human-approver` 与原始决策枚举 `APPROVED` 或 `REJECTED`。

### 4.4 审批后自动阶段

1. Manager 校验审批与方案的精确绑定后自动调度 Safe Executor。
2. Safe Executor 经 Gateway/Runner 执行，并原子交接 Verification Auditor，显示 5/6。
3. Verification Auditor 独立复算、校验产物和审计链，发出 `verification_completed`，显示 6/6。
4. Incident Commander 根据 Auditor 裁决发布最终结果。
5. Reviewer 显示可信终态；不再要求用户发送收尾消息。

## 5. 核心架构

```text
用户一次发任务
      │
      ▼
Manager ──原子事件──► Matrix ──严格读取──► Reviewer
  │                       ▲
  ├─► Evidence Collector ─┤
  ├─► RCA Analyst ────────┤
  ├─► Experiment Planner ─┤──► Human Approval（唯一人工暂停）
  ├─► Safe Executor ──────┤
  └─► Verification Auditor┤
                          │
                 MinIO/共享目录中的真实产物
```

架构由四部分组成：

1. **原子 Handoff Emitter：** Worker/Manager 在自己的运行环境中调用，发送一条完整 Matrix 消息。
2. **部署时运行绑定：** 将该容器可发送的角色、事件类型和目标 room 写入不含凭据的 sidecar。
3. **Manager 编排合同：** 明确每个阶段应调用的 Skill、预期输入/输出、合法完成事件和下一责任人。
4. **录制前门禁：** preflight 验证 emitter、Skills、Matrix 身份、状态清洁度和 Run ID 唯一性。

## 6. 原子 Handoff Emitter

### 6.1 形态

仓库保存一份 canonical standalone Python emitter。部署流程将其与角色对应的现有 Skill 一起安装到 Manager/Worker 容器。Worker 不依赖仓库中的 `labops` 包即可运行它。

Emitter 通过已经配置在容器中的 OpenClaw Matrix channel 发送消息：

```text
openclaw message send --channel matrix --target room:<room-id> --message <body> --json
```

Token 由容器既有 OpenClaw 配置读取；命令行、sidecar、日志和 Reviewer API 都不回显 Token。

### 6.2 输入

Emitter 接收结构化参数，而不是让 Agent 自由拼接整条消息：

- `session_id`
- `task_instance_id`
- `incident_instance_id`
- `attempt_id`
- `run_id`
- `event_kind`
- `input_artifact`
- `output_artifact`
- 可选的事件专属字段文件，如 approval binding 或 terminal decision

五个运行绑定以 session contract 为准。Agent 不得通过参数覆盖 contract 中的值。

### 6.3 运行绑定 sidecar

每个已部署 Skill 旁存在 `LABOPS_HANDOFF_RUNTIME.json`，至少包含：

```json
{
  "schema_version": "1.0",
  "canonical_agent_id": "evidence-collector",
  "runtime_agent_id": "evidence-collector",
  "matrix_room_id": "<deployment-specific room id>",
  "coordinator_matrix_id": "<manager matrix user id>",
  "allowed_event_kinds": ["collector_to_rca", "evidence_incomplete"]
}
```

该文件：

- 由本地受信 room map 与部署配置生成。
- 不包含 access token。
- 参与部署验证和 hash 校验。
- 禁止一个容器声明另一个 Worker 的身份或事件类型。

### 6.4 原子消息格式

Emitter 生成单条纯文本消息。字段顺序固定，恰好一个事件类型行，artifact 路径均为 session-relative：

```text
@<coordinator-matrix-id>
session_id: <session>
task_instance_id: <task>
incident_instance_id: <incident>
attempt_id: <attempt>
run_id: <run>
LABOPS_EVENT_KIND: <event-kind>
LABOPS_INPUT_ARTIFACT: <relative-path>
LABOPS_OUTPUT_ARTIFACT: <relative-path>
```

事件专属字段追加在固定 envelope 后。Emitter 禁止：

- 绝对路径、`..`、host-private 路径和 session 外路径。
- 缺失或额外的运行绑定。
- 当前角色不允许的事件类型。
- 空 artifact 路径。
- 将 Markdown 粗体或代码块作为机器字段的必要组成部分。

### 6.5 成功、失败与幂等

- 只有 OpenClaw 返回成功且能解析真实 Matrix `event_id` 时，Emitter 才返回成功。
- 成功结果保存为 session namespace 下的发送回执，包含 event kind、绑定摘要、消息 hash、event ID 和发送时间，不包含凭据。
- 幂等键由 `session_id + attempt_id + event_kind + output_artifact` 组成。
- 已有成功回执时再次调用返回 `ALREADY_EMITTED`，不得重复发送。
- 明确的发送失败可有限重试；响应状态不确定时不得盲目重发，以免产生重复事件。
- Emitter 不写 `normalized_events.jsonl`；该文件仍只能由 Observer 基于真实 Matrix history/live sync 生成。

## 7. 角色与事件合同

六个计数 Handoff 固定如下：

| 序号 | 真实发送角色 | Runtime identity | 事件类型 | 下一责任人 |
|---|---|---|---|---|
| 1 | Incident Commander | `labops-manager` | `manager_to_collector` | Evidence Collector |
| 2 | Evidence Collector | `evidence-collector` | `collector_to_rca` | RCA Analyst |
| 3 | RCA Analyst | `rca-analyst` | `rca_to_planner` | Experiment Planner |
| 4 | Experiment Planner | `experiment-planner`（运行别名可为 `researcher`） | `approval_pending` | Human Approver |
| 5 | Safe Executor | `safe-executor`（运行别名可为 `controlled-executor`） | `executor_to_auditor` | Verification Auditor |
| 6 | Verification Auditor | `verification-auditor` | `verification_completed` | Incident Commander |

Human Approval 是单独的治理事件，不计入 6 个 Agent Handoff：

- `LABOPS_EVENT_KIND: approval_granted`
- `LABOPS_ACTOR: human-approver`
- 必须来自非 Agent Matrix 账号。
- 必须绑定 approval ID、plan ID、canonical plan SHA-256、run ID、nonce、decision、scope 与 validity window。

现有 `executor_to_gateway`、`runner_started`、`runner_completed`、`terminal_decided` 和 `commander_published` 等阶段事件继续遵循现有 schema；它们不能代替六个 Handoff。

## 8. Skills 与 Manager 编排

### 8.1 Skill 输出合同

现有 Skills 保持业务职责不变，但各自增加确定性的完成步骤：

1. 校验输入 artifact。
2. 执行业务工作并落盘 canonical output artifact。
3. 重新读取输出并完成 schema/hash 校验。
4. 调用角色绑定的 emitter 发出唯一完成事件。
5. 只有 emitter 成功后，才向本地运行时报告阶段完成。

自然语言总结可以保留给人阅读，但不能作为 Handoff 成功依据。

### 8.2 Manager 行为

生成的 `manager_task.md` 必须为每个阶段给出：

- 当前责任角色与必须调用的 Skill。
- 精确 input/output artifact 路径。
- 当前角色允许发出的 outgoing event kind。
- 事件合法时的下一责任人。
- 事件非法或 artifact 未通过校验时的自动纠正路径。

Manager 的关键规则：

- 收到合法完成事件后立即派发下一阶段，不等待 heartbeat。
- 不把收到的 incoming kind 原样复制给下一 Worker。
- 不代替 Worker 发送 Worker 事件。
- Worker 产物存在但事件无效时，Manager 自动要求原 Worker 使用 emitter 重发正确事件；该内部纠正不需要用户介入。
- 在 `approval_pending` 前不得请求用户审批；未收到合法 `approval_granted` 前不得启动 Executor。
- Auditor 完成后自动发布最终结论，不要求用户发送“收尾”。

## 9. Human Approval 交互

Planner 发出合法 `approval_pending` 后，Manager 在用户可见房间输出：

1. 纯中文方案摘要。
2. 风险、范围、回滚条件和有效期。
3. Plan ID、Plan Hash、Approval ID、Run ID、nonce 等技术绑定。
4. 一个可以直接复制发送的完整审批块。

用户只发送该审批块一次。仅回复“可以执行”不作为机器审批事件，避免审批人与方案绑定不明确。UI 可把审批块折叠展示，但底层消息必须保留完整原始枚举和绑定。

如果用户选择 `REJECTED`，系统记录拒绝并停止；不会自动修改方案或执行。

## 10. Preflight 与录制状态门禁

`reviewer preflight --mode live` 只有在以下条件全部成立时返回 `READY`：

- Docker、AgentTeams Manager 与五个 Worker 正常运行且版本匹配。
- Matrix homeserver、凭据、room map 和房间成员关系有效。
- 六个角色的 room 与 sender 绑定无歧义。
- 已部署 Skills 的版本、SKILL.md、runtime binding 和 emitter hash 与仓库一致。
- emitter `--dry-run` 能为每个角色生成符合合同的消息。
- `runtime_event_emission` 状态为 `VERIFIED`，而不是 `NOT_IMPLEMENTED` 或 `UNVERIFIED`。
- 正式 Evidence Bundle、Runner image、Trust Contract 和 Skill Registry 均通过现有校验。
- 不存在会污染本次录制的旧 live-demo active task。
- 当前 session 的 task/incident/attempt/run ID 未与历史 session 或已有 Runner output 冲突。

失败时输出明确、可行动的错误码，但不打印 access token、私有 room ID 全量或 host-private 路径。

## 11. Run ID 唯一性

现有 Run ID 只使用三位序号，跨日期 session 可能碰撞。为保持 Gateway 合同兼容，本次不扩大 Run ID schema，而在 prepare/preflight 阶段增加全局冲突检查：

- 扫描已有 live session manifest。
- 扫描 live-demo Runner output namespace。
- 若目标三位序号已被使用，则拒绝 prepare 或返回下一个可用序号建议。
- 不覆盖旧 run 目录，不复用旧 Approval nonce。

后续若要改变 Run ID schema，应作为独立版本迁移，不混入本次修复。

## 12. 失败演练清理与证据保留

提供显式确认的录制状态归档操作，默认只读预览。执行时：

1. 备份 Manager 的 `state.json`，记录备份 hash 和时间。
2. 只处理 ID 符合 live-demo 命名规则的过期 active task。
3. 将 Session `20260902-002` 标记为 `ABORTED_REHEARSAL`。
4. 从 active queue 移出旧 rehearsal，但保留原始 Matrix history、MinIO/共享目录产物、Observer 投影和日志。
5. 不删除、不移动、不改写正式 AT-002/003/004 数据。
6. 任一步校验失败则停止，不进行部分清理。

该清理不是制造成功状态，而是防止陈旧任务干扰下一次录制。

## 13. Reviewer 行为

Reviewer 继续作为只读可信投影：

- 从真实 Matrix live sync/history 读取事件。
- 保存真实 `event_id`、room、sender 和 source timestamp。
- 先显示 `OBSERVED`，只有对应 artifact/schema/hash 校验通过后显示 `VERIFIED`。
- 不根据 MinIO 文件存在直接推断某个 Agent 已完成 Handoff。
- 不把 Manager 代发的 Worker 事件算入进度。
- 不因页面刷新或进程重启重复计数。
- 断开连接时明确显示数据源已断开，不维持虚假“实时”。

页面逐步亮起是事件链正确运行的结果，而不是前端计时动画。

## 14. 错误处理

| 场景 | 系统行为 | 是否需要用户介入 |
|---|---|---|
| Worker 输出 artifact 合法，但未发事件 | Manager 要求同一 Worker 使用 emitter 补发 | 否 |
| Worker 发错 event kind | Emitter 本地拒绝；若绕过则 Observer 拒绝，Manager纠正 | 否 |
| sender/room 不匹配 | Observer 拒绝并记录原因 | 否，除非部署配置错误 |
| Matrix 明确发送失败 | Emitter 有限重试并报告失败 | 通常否 |
| Matrix 结果不确定 | 不盲目重发，进入可诊断阻塞 | 是，若自动恢复超时 |
| artifact schema/hash 失败 | 阻断交接，保持当前责任人 | 否，除非数据本身需人工补充 |
| 等待审批 | 停在 `APPROVAL_PENDING` | 是，仅此一步 |
| Approval binding 不匹配 | 拒绝执行并显示差异 | 是，需要重新审批正确方案 |
| Run ID 已存在 | prepare/preflight 失败 | 是，选择建议的新 session |
| Reviewer 重启 | 从 Matrix history/backfill 恢复真实事件 | 否 |

## 15. 测试策略

实现遵循测试驱动：先写失败测试，再实现最小修复。

### 15.1 Emitter 单元测试

- 使用 fake `openclaw` 可执行文件验证命令参数和消息正文。
- 验证六种角色—事件映射。
- 拒绝跨角色事件、绑定不一致、绝对路径、`..` 和空 artifact。
- 成功响应必须提取真实格式的 Matrix event ID。
- 验证回执不包含 Token。
- 验证相同幂等键只发送一次。
- 验证 `--dry-run` 不发送消息且输出可供 preflight 校验的摘要。

### 15.2 Skill 部署测试

- 每个目标容器包含正确版本的 Skill、emitter 与 sidecar。
- deploy/verify 能发现 emitter 缺失、hash 漂移和错误 room/role 绑定。
- `runtime_event_emission` 仅在全部角色通过时为 `VERIFIED`。

### 15.3 Manager task 测试

- 六个 Handoff 均出现且与角色一一对应。
- 每阶段包含 Skill、input/output、outgoing event 和 next actor。
- Planner 必须发 `approval_pending`，Manager 不得代发。
- 审批前 Executor 不可运行。
- 用户除初始任务和一次审批外无需额外消息。

### 15.4 Preflight 与 session 测试

- emitter 未部署或未验证时返回 `BLOCKED`。
- 旧 live-demo active task 存在时返回 `BLOCKED` 并给出归档提示。
- Run ID 碰撞时 prepare/preflight 拒绝继续。
- 正式 task 不得被清理逻辑选中。

### 15.5 Observer 回归测试

- 现有 strict sender/room/binding/artifact 测试全部保持通过。
- 原子消息能被 Observer 接收并保留真实 event ID。
- 流式碎片、编辑残片、错误 actor 和 Manager 冒充事件继续被拒绝。
- Reviewer 重启 backfill 不重复计数。

### 15.6 集成验收

先进行不录屏 rehearsal，再开始正式录制：

- preflight 为 `READY`，并明确显示 `runtime_event_emission: VERIFIED`。
- 用户发送一次 manager task。
- 四个审批前 Handoff 自动完成，Reviewer 依序显示 1/6 至 4/6。
- 系统准确停在 `APPROVAL_PENDING`。
- 用户发送一次完整审批事件。
- 5/6、6/6 和最终发布自动完成。
- 每个 Handoff 都有真实 Matrix event ID、正确 sender/room 和对应 artifact。
- 全程不需要用户发送“继续”“再检查”“请转交下一步”等推动消息。

## 16. 验收标准

以下条件必须全部满足，才能宣布修复完成并允许重新录制：

1. `agentteams-skills verify` 将运行时事件能力报告为 `VERIFIED`。
2. Live preflight 能阻止缺少 emitter、旧任务污染和 Run ID 冲突。
3. Session `20260902-002` 被保留并标记为失败演练，不被伪装成成功。
4. 新 session 使用全新的 task、incident、attempt、run 和 approval nonce。
5. 一次 manager task 触发审批前完整自动链路。
6. Human Approval 是唯一一次中途人工输入。
7. 审批后 Executor、Auditor 和 Manager 收尾自动完成。
8. Reviewer 逐阶段同步更新，而不是最后一次性变化。
9. 六个计数事件均由正确真实角色发送，且绑定和 artifact 均通过验证。
10. `normalized_events.jsonl` 只由真实 Matrix 事件生成。
11. AT-002/003/004 Evidence hash 与修复前一致。
12. 全部新增测试与现有测试通过。

## 17. 安全与可审计性

- 不把 access token 写入源码、Skill、sidecar、测试 fixture、报告或终端摘要。
- 用户此前暴露过的 Token 不在任何新文件中复述；录制前应使用当前有效凭据，并在必要时轮换。
- 只在用户明确执行 Human Approval 时形成审批事件。
- Emitter 回执、Observer 记录、artifact hash 和 Manager 状态共同形成可追溯链，但任何一项都不能单独替代真实执行证据。
- 所有清理操作先备份、再精确匹配、后验证；不执行递归删除。

## 18. 实施顺序与回滚

实施按以下顺序进行：

1. 为 emitter、部署验证、Manager task、preflight、session 冲突和归档逻辑添加失败测试。
2. 实现 canonical emitter 与 runtime sidecar。
3. 更新现有 Skills 的完成合同并部署到对应容器。
4. 更新 Manager task 生成器和 Human Approval 模板。
5. 扩展 preflight、Run ID 门禁和安全归档命令。
6. 运行单元、集成和完整回归测试。
7. 备份并归档失败 rehearsal 状态。
8. 部署 Skills，执行 live preflight 和非录制 rehearsal。
9. rehearsal 通过后，生成全新 session 的录屏操作指南。

若部署后验证失败：

- 停止新 rehearsal，不触碰正式 Evidence。
- 使用已记录的部署 manifest 恢复上一版 Skills。
- 使用备份恢复 Manager 状态。
- 保留失败日志和 Matrix 事件用于诊断，不补写成功记录。

## 19. 最终产品含义

本设计完成后，Demo 展示的不只是“多个聊天窗口依次回复”，而是一条可验证的多 Agent 治理链：每个角色独立产出、原子交接、身份可证、Evidence 可追、审批不可越权、执行受控、审计独立。页面上每一步亮起都来自一条真实且通过约束校验的 Matrix 事件。

这能证明 LabOps Guard 对一次模拟事故的治理流程和受控实验验证成功；它仍不会把模拟验证错误表述为真实生产事故已经解决。
