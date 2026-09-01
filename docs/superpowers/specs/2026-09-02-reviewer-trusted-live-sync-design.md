# Reviewer 可信实时同步与渐进式协作状态设计

## 1. 目标

让 `LabOps Guard · Agent Mission Control` 在真实 AgentTeams Demo 中持续、直观且可验证地展示进度：

- Matrix 中真实发生的角色交接使 Agent 节点按阶段点亮；
- AgentTeams 共享存储中的原始产物以只读方式自动同步到 Reviewer 会话；
- 页面分开“已观察”与“已验证”，不把聊天声明当成完整 Evidence；
- Matrix 短暂抖动不再立即显示为永久断开；
- 新会话从 Manager 派发到 Auditor 和 Commander 收尾可无手工复制文件地完成页面同步。

本设计修复的是 Reviewer 观测链和 Demo 证据合同，不改变 Runner、Approval、Recovery 或 AgentTeams 的控制边界。

## 2. 现状与根因

`20260902-001` 中 Safe Executor 和 Verification Auditor 已在真实 AgentTeams 环境运行，但 Mission Control 仍显示 `0/6`、Evidence 阻断和仅第一个 Agent 点亮。根因是三条独立的断链：

1. **事件合同不一致**：Reviewer 只接受白名单中的 `LABOPS_EVENT_KIND`，当前 AgentTeams 使用 `manager_to_rca`、`evidence_ready`、`execution_complete` 等非规范值，或没有发送结构化标记。
2. **Evidence 存储不连通**：AgentTeams 产物在 Manager 容器的 `/root/hiclaw-fs/shared/tasks/live-demo/<session>/`，而 Reviewer 验证器只读本地 `demo/live-sessions/<session>/evidence/`。
3. **连接状态过度敏感**：单次 Matrix 请求失败会立即投影为 `DISCONNECTED`，忽略了最近成功读取时间。

此外，`001` 的远端最终产物存在合同冲突：`meta.json` 同时出现 `CLOSED` 与 `PLAN_READY`，`verification_report.json` 缺少会话绑定和规范决策字段，`trace.jsonl` 也未包含完整收尾链。因此 `001` 可作为真实排演和排障记录，不能被自动粉饰成已验证全链路。

## 3. 设计原则

1. **先观察，后验证**：Matrix 事件只能产生 `OBSERVED`；只有通过现有 `live-demo verify` 的规范 Evidence 才能产生 `VERIFIED`。
2. **失败封闭**：缺少绑定、发送者错误、路径越界、哈希冲突或 Schema 不合法时，保留原始产物并显示原因，不提升状态。
3. **原始产物不可变**：同步过程不修改 Matrix 历史或 AgentTeams 共享存储，不覆盖正式 AT-002/003/004 Evidence。
4. **无自然语言推断**：不根据“已完成”“PASS”等聊天文本猜测工作流；只处理结构化事件或精确标记。
5. **Reviewer 仍完全只读**：Reviewer 可读 Matrix 和共享存储，但不发送 Matrix 消息、不审批、不重试、不执行 Runner。
6. **中文优先的可观测性**：页面直接说明“正在等什么”和“为什么未验证”，原始机器状态保留在技术层。

## 4. 架构

### 4.1 Matrix 事件适配器

`labops/matrix_observer.py` 继续是 Matrix 观测的唯一入口。它接受两种等价输入：

- `content.labops_event` 结构化对象；
- 消息体中的精确 `LABOPS_EVENT_KIND: <kind>` 行。

每个事件必须同时满足：

- 事件 ID 为真实 Matrix `event_id`；
- room 在配置白名单内；
- sender 与角色绑定一致；
- `session_id`、`task_instance_id`、`incident_instance_id`、`attempt_id`、`run_id` 全部匹配当前或 Recovery 验证过的 Attempt；
- kind 位于白名单，且 actor 有权发出该 kind。

新会话使用下列六个交接事件作为页面主进度：

| 交接 | 发送者 | 规范 kind | 目标状态 |
| --- | --- | --- | --- |
| Manager → Evidence Collector | `labops-manager` | `manager_to_collector` | `EVIDENCE_COLLECTING` |
| Evidence Collector → RCA Analyst | `evidence-collector` | `collector_to_rca` | `DIAGNOSING` |
| RCA Analyst → Experiment Planner | `rca-analyst` | `rca_to_planner` | `PLANNING` |
| Experiment Planner → Safe Executor | `experiment-planner` | `approval_pending` | `APPROVAL_PENDING` |
| Safe Executor → Verification Auditor | `safe-executor` | `executor_to_auditor` | `VERIFYING` |
| Verification Auditor → Manager | `verification-auditor` | `verification_completed` | `VERIFYING` |

`approval_granted`、`runner_started`、`runner_completed`、`terminal_decided` 和 `commander_published` 保留为阶段事件，不重复计入六次交接。`evidence_incomplete` 仍进入 Recovery 分支。

对历史非规范 kind 不进行宽泛别名转换。`20260902-001` 中的 `manager_to_rca`、`manager_to_executor`、`manager_to_auditor`、`evidence_ready`、`diagnosis_ready`、`plan_ready`、`execution_complete` 保留为未接受的原始事件，不冒充其他 Agent 的交接。

### 4.2 只读 Evidence 同步桥

新增独立的 Evidence 同步组件，不将 Docker 读取逻辑混入验证器。组件提供一个源接口：

```text
snapshot(session_id, destination) -> EvidenceSnapshot
```

当前 Windows Demo 使用 `DockerEvidenceSource`，只读从：

```text
hiclaw-manager:/root/hiclaw-fs/shared/tasks/live-demo/<session_id>/
```

拉取到随机临时目录。同步源不接受用户输入的任意容器路径；`session_id` 必须通过现有 `YYYYMMDD-NNN` 校验。

每次快照按两层发布：

1. `observer/evidence-mirror/`：原样保留远端相对路径、文件大小和哈希，用于显示“已同步”。该层不会使 Reviewer 标记 `VERIFIED`。
2. `evidence/`：只有通过允许路径映射、绑定、Schema 和交叉哈希校验的文件才原子性发布到现有规范 Evidence 目录。

允许的原始映射是固定的：

| 规范目标 | 允许的原始位置 |
| --- | --- |
| `approval_grant.json` | `artifacts/DEMO-EVAL-DRIFT-004/approval_grant.json` |
| `gateway_request.json` | `runs/<bound-run-id>/gateway_request.json` |
| `gateway_response.json` | `runs/<bound-run-id>/gateway_response.json` |
| `runner/run_result.json` | `runs/<bound-run-id>/run_result.json` |
| `runner/metrics.json` | `runs/<bound-run-id>/metrics.json` |
| `runner/artifact_manifest.json` | `runs/<bound-run-id>/artifact_manifest.json` |
| `runner/stdout.log` | `runs/<bound-run-id>/stdout.log` |
| `runner/stderr.log` | `runs/<bound-run-id>/stderr.log` |
| `verification.json` | `verification/verification_report.json` |
| `trace.jsonl` | `trace.jsonl` |

`matrix_events.json` 由已接受的真实 Matrix 事件投影生成，每条保留原始 `event_id`。`handoff_manifest.json` 仅能由六个完整、有序、发送者正确的规范交接事件派生。这两个文件是对真实 Matrix 历史的确定性规范化，不是人工伪造事件。

同步器不会为缺少的 `decision`、`verified_by`、`resolution_status` 或任何安全绑定补值。如果原始文件不满足规范，它仅留在 mirror 层，页面显示精确的验证失败代码。

### 4.3 运行方式

Live Reviewer 启动时同时启动两个只读后台循环：

- Matrix Observer：保持现有 1 秒读取周期；
- Evidence Sync：默认每 3 秒快照一次，只在远端文件集合哈希变化时执行规范校验。

两个循环都只写当前 `NON_FORMAL_LIVE_DEMO` 会话下的 observer/evidence 投影，不会调用 Manager、Worker、Approval 或 Gateway。Reviewer 退出时必须在有界时间内停止两个循环，不留后台进程。

Docker 不可用、容器不存在或路径缺失时，Matrix Observer 仍可独立工作；页面显示 `EVIDENCE_SOURCE_UNAVAILABLE`，不终止 Reviewer HTTP 服务。

### 4.4 连接健康状态

Matrix 源状态使用最近成功时间而不是单次请求结果：

- 最近成功读取距现在 `<= 15s`：`LIVE`，即使当前一次请求失败；
- `15s < age <= 60s`：`STALE`，中文显示“连接波动”；
- `age > 60s` 或从未成功连接：`DISCONNECTED`，中文显示“已断开”；
- 加密房间仍是 `UNSUPPORTED_ENCRYPTED_ROOM`，不被降级为普通抖动。

失败快照保留上一次 `last_success_at` 和已接受事件，不因一次请求失败把页面清空。

## 5. Mission Control 状态语义

页面不再用一个 `0/6` 同时表示观察和验证。顶部分开显示：

- **已观察 Handoff `x/6`**：来自通过 sender、room 和五个绑定校验的 Matrix 事件；
- **已验证 Handoff `y/6`**：来自通过完整 `live-demo verify` 的 Evidence Bundle；
- **Evidence 同步**：`WAITING / SYNCING / MIRRORED / ERROR`；
- **Evidence 校验**：`NOT_READY / BLOCKED / VERIFIED`。

Agent 节点状态按置信度逐级提升：

```text
NOT_STARTED → OBSERVED → VERIFIED
```

- `OBSERVED` 使用青色轮廓和“已观察”；
- `VERIFIED` 使用绿色和“已验证”；
- 事件已观察但 Evidence 不合法时，保留青色并在 Evidence 区域显示阻断原因，不回退为“未开始”。

页面在每次轮询时保留用户已选中的 Agent/Evidence Inspector 项，只更新变化的状态，不闪回默认节点。

## 6. AgentTeams 输出合同

`live-demo prepare` 生成的 Manager 任务必须明确要求：

1. 六次角色交接分别由真实交付角色在对应房间发出，不允许 Manager 代替 Worker 冒充交接；
2. 每次交接包含完整五个会话绑定和唯一规范 `LABOPS_EVENT_KIND`；
3. Approval、Gateway、Runner 和 Verification 文件使用现有 Schema 所需的结构化字段；
4. Verification 至少包含 `session_id`、`task_instance_id`、`incident_instance_id`、`attempt_id`、`run_id`、`decision`、`verified_by`、`resolution_status` 和完整 checks；
5. 每个事件只发一次，不重复消费 Approval nonce，不重跑 Gateway；
6. Commander 只在 Auditor 交付后发布结果。

该合同只约束新 Demo 会话，不编辑历史 Matrix 消息。

## 7. 会话策略

- `20260902-001` 保留为 **rehearsal**：保留实际 Matrix 事件和远端产物，允许页面显示 mirror 中已存在的原始 Evidence，但不补写六次交接，不标记全链验证通过。
- 修复完成后创建新会话 `20260902-002`，必须先启动 Reviewer 并确认 Matrix/Evidence 两个读取器正常，再由人类在 Element 向 Manager 发送新任务。
- `002` 使用新的 task/incident/attempt/run ID，不复用 `001` 产物。

## 8. 错误处理与安全

同步器和 Reviewer API 只返回经过脱敏的代码，不返回 token、私有 room ID、容器内绝对路径或主机绝对路径。核心错误代码包括：

- `EVIDENCE_SOURCE_UNAVAILABLE`
- `EVIDENCE_SNAPSHOT_TOO_LARGE`
- `EVIDENCE_PATH_REJECTED`
- `EVIDENCE_BINDING_MISMATCH`
- `EVIDENCE_SCHEMA_INVALID`
- `EVIDENCE_HASH_CONFLICT`
- `EVIDENCE_INCOMPLETE`
- 现有 Matrix 错误代码。

快照设置总字节上限和单文件上限，拒绝符号链接、绝对路径、`..` 路径、超出允许映射的文件。临时快照只能原子性替换当前会话的 mirror，失败时保留上一个成功快照。

## 9. 测试策略

所有行为变更都使用 TDD，每个测试先在当前实现上按预期原因失败。覆盖：

1. **Matrix 事件**：六个规范交接通过；错误 sender、room、binding、attempt/run 和非白名单 kind 被拒绝；历史非规范 kind 不被冒充。
2. **Evidence 快照**：在临时源目录上使用真实文件逻辑测试；验证原子替换、不变快照跳过、路径越界、超限、绑定错误、Schema 错误和哈希冲突。Docker CLI 仅在最外部适配层隔离。
3. **状态宽限**：连续成功、短失败、15秒、60秒边界和从未成功连接的手工时钟测试。
4. **Reviewer 投影**：观察计数与验证计数不互相污染；已观察事件在 Evidence 校验失败时仍可见；不存在任何证据时不显示假进度。
5. **Web 页面**：两组 Handoff 指标、同步/校验状态、Agent 逐步点亮、中文错误说明和轮询后选中项保持；页面仍无任何写入控件。
6. **端到端**：对本地临时 Matrix 快照和 Evidence 源运行 Reviewer，验证从 `0/6` 到 `6/6 observed`、再到 `6/6 verified` 的状态序列。

## 10. 验收标准

### 自动化验收

- Matrix 短暂失败不在 60 秒内变为 `DISCONNECTED`；
- 非规范历史事件、错误发送者和错误绑定全部失败封闭；
- 原始快照可同步，但不合法 Verification 不能进入规范 Evidence；
- 完整合法快照可让现有 `live-demo verify` 返回 `VERIFIED` 且 `errors=[]`；
- 聚焦测试和全量测试通过。

### 人工 Demo 验收

1. 启动新 `20260902-002` 时页面显示 Matrix 与 Evidence 源就绪；
2. 人类只需在 Element 发送 Manager task 以及执行真人 Approval，不手工复制 Evidence；
3. 六个 Agent 节点随规范 Matrix 交接逐步显示“已观察”；
4. 远端产物出现后，Evidence 同步状态在一个 3 秒周期内更新；
5. 只有完整规范 Evidence 通过后，页面才显示 `6/6 已验证`和终态；
6. 断开一次 Matrix 读取不会清空已观察进度；
7. Reviewer 不发送消息、不审批、不执行、不修改任何原始 AgentTeams 产物。

## 11. 非目标

- 不修复或改写 `20260902-001` 的历史 Matrix 事件和原始产物；
- 不将自然语言聊天转换为可信终态；
- 不将 Demo 结果宣称为真实生产事故已解决；
- 不修改正式 AT-002/003/004 Evidence；
- 不新增 Reviewer 写 API，不让 Reviewer 成为工作流控制器；
- 不在本阶段开发 P0-3 PPT/PDF/视频提交包。
