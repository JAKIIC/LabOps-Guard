# LabOps Guard Agent Mission Control 设计规格

## 1. 背景与目标

现有 Reviewer Edition 已经能只读展示六个 Agent、时间线、人工审批、Recovery、Runner、Auditor 与 Evidence，但主要采用纵向卡片和长文本详情。它适合工程复核，不足以在 16:9 复赛视频中让评委快速理解“谁在处理、为何暂停、如何恢复、谁批准、谁执行、谁最终裁决”。

本次升级把现有 Reviewer 改造成 `LabOps Guard · Agent Mission Control`：Reviewer 作为主叙事画面，Element 继续作为真实 Matrix 原始证据来源。升级只改变只读投影和 UI 层级，不改变 AgentTeams、Matrix、Runner、Approval、Recovery、Evidence、状态机或终态事实。

成功标准：

1. 评委在 15 秒内看懂当前事故、当前节点、六角色协作关系、人工门和最终状态。
2. 在 1920×1080 与 1366×768 视口中，首屏同时容纳事故总览、协作图、审批门和关键结果，不发生节点横向溢出。
3. 点击 Agent 或时间线事件，可以看到对应 Runtime identity、状态转换、Matrix event ID、Artifact 与 Hash；不存在的证据显示为“未观察”，不得补造。
4. 097 已验证数据必须显示六个真实 Handoff、Attempt 02 / Run 098、人工审批、0.71875×3 到约 0.978125×3、Auditor PASS，以及 `DEMO_PASSED_NOT_RESOLVED`，不得显示 `RESOLVED`。
5. Reviewer 继续完全只读；所有非 GET 请求仍返回 405。

## 2. 事实与安全边界

- `labops/reviewer_state.py` 是 UI 状态投影的唯一后端入口。
- `labops/reviewer.html` 只消费 `/api/reviewer/status` 与 `/api/reviewer/events`，不新增写 API。
- 动画只能由状态投影中 `OBSERVED` 或 `VERIFIED` 的事件触发；`CONFIGURED` 节点和边保持静态灰色。
- 不展示 Matrix Access Token、私有凭据、宿主机绝对路径或 Matrix room ID。
- 可以展示已验证的 Matrix event ID、脱敏 Artifact 引用、SHA-256 摘要、Attempt/Run ID 和角色 Runtime identity。
- 不删除或重命名任何 Matrix 房间；Element 侧栏整理属于录制环境操作，不属于本次代码改动。
- Human Approval 是独立责任主体，不计入六个 Agent，不允许 UI 暗示 Reviewer 可以批准、重试、接管或执行。
- `DEMO_PASSED_NOT_RESOLVED` 的中文显示固定为“演示验证通过（未解决）”；Auditor 节点显示“审计通过”，Commander 显示“结果已发布”。

## 3. 信息架构

页面按“总览 → 协作 → 结果 → 证据”的顺序组织。

### 3.1 顶部状态栏

保留：

- 产品名：`LabOps Guard · Agent Mission Control`
- 中文副标题：`面向生产级 Agent 系统的可信协作、人工治理与可验证执行`
- 数据源徽标：实时 / 部分实时 / 归档
- 模式徽标：Live / Quick 的中文视觉标签
- `完全只读`

顶部不展示重复的英文普通字段名。

### 3.2 事故总览带

使用一个主事故卡与四个紧凑 KPI：

- 当前事故与业务状态
- 当前责任人
- 真实 Handoff 完成数，例如 `6 / 6`
- Evidence 完整度，例如 `已验证`
- 人工审批状态
- 最终裁决

Session、Incident、Task、Attempt、Run ID 收进“运行绑定”折叠区，首屏仅保留短 ID 和当前 Attempt/Run。

### 3.3 多 Agent 协作图

六个 Agent 按真实职责顺序排列：

`Incident Commander → Evidence Collector → RCA Analyst → Experiment Planner → Safe Executor → Verification Auditor`

Human Approval 位于 Planner 与 Executor 之间，以独立琥珀色门节点显示。Recovery / Human Takeover 作为 Collector 的异常支路，回到新的 Attempt，不伪装成第七个 Agent。

每个 Agent 节点只显示：

- 序号、中文角色名和一次英文名
- 当前工作流状态
- Evidence 状态
- 当前/最后一次动作的短说明
- 可点击的证据状态指示灯

连线规则：

- 灰色虚线：配置路径，尚未观察
- 青色实线：真实 Matrix 事件已观察
- 绿色实线：Handoff 与绑定 Evidence 已验证
- 琥珀色：Human Approval / Human Takeover
- 红色：阻断、策略违规或校验失败

只对最新一次新增的真实事件使用轻量脉冲动画；`prefers-reduced-motion` 下禁用动画。

### 3.4 业务结果卡

首屏下半部显示可核验的 Before / After：

- 基线准确率及重复次数
- 候选准确率及重复次数
- 提升幅度
- 阈值
- 允许的唯一变化路径
- 模型、数据、Metric、Protocol、Checkpoint 的保护状态
- 网络和 Sandbox 边界

数据只能来自已存在的 Runner 与 Verification 产物。若未观察到 Metrics，则显示“等待 Runner 证据”，不显示演示占位数字。

### 3.5 证据检查器

右侧为常驻 Inspector；窄屏下变为页面内抽屉。点击 Agent、审批门或时间线事件后显示：

- 中文业务说明
- Actor / Runtime identity
- Workflow transition
- Evidence state 与来源
- Matrix event ID
- Artifact refs
- Hash refs
- Attempt / Run 绑定
- 权限边界

不提供审批、执行或状态修改按钮。Event ID 提供复制能力，但不构造包含私有 room ID 的 Element permalink。

### 3.6 运行时间线

时间线只显示关键业务事件，格式统一为：

`中文事件描述`  
`MACHINE_STATE_A → MACHINE_STATE_B`

默认紧凑显示；选中后在 Inspector 中展示完整原始字段。重复 Matrix 投递不重复绘制同一个业务阶段，仍可在 Evidence 详情中保留原始事件事实。

### 3.7 工程证据区

Tool Contract、Recovery、Runner、Auditor 与 Evidence 边界移到首屏之后的“工程证据”分区，默认显示结论，详细 JSON 使用折叠面板。这样既保留评委复核能力，也避免主画面被长 JSON 占满。

## 4. 数据投影

### 4.1 保持现有顶层状态结构

不新增 API 路由。现有字段继续作为来源：

- `incident`
- `agents`
- `approval`
- `timeline`
- `tool_contract`
- `recovery`
- `runner`
- `audit`
- `limitations`

### 4.2 扩展 Runner 只读投影

`runner` 在对应产物存在时增加：

- `baseline_accuracy: number | null`
- `candidate_accuracy: number | null`
- `baseline_repeats: number | null`
- `candidate_repeats: number | null`
- `minimum_accuracy: number | null`
- `accuracy_improvement: number | null`
- `changed_paths: string[]`
- `protected_hashes_unchanged: boolean | null`

这些值从 `evidence/runner/metrics.json`、`run_result.json` 与 `verification.json` 读取和交叉检查。任何来源不一致时字段返回 `null`，并在 `limitations` 添加错误；UI 不选取更好看的值。

### 4.3 前端派生值

Handoff 计数、Agent 完成数和当前活动边由 `agents` 与 `timeline` 在浏览器内派生，不重复在后端维护第二套状态。

Inspector 使用现有状态对象的白名单字段生成，不直接渲染未过滤的任意 HTML。所有文本通过 `textContent` 写入。

## 5. 视觉与交互规范

- 中文约 70%，英文约 30%；英文只保留产品名、角色名、技术原语和机器枚举。
- 深蓝黑背景沿用当前 Reviewer；青色代表观察，绿色代表验证，琥珀色代表真人门，红色代表阻断。
- 不使用头像拟人聊天气泡作为主要视觉；角色以职责节点呈现。
- 不引入 D3、React、外部字体、CDN 或网络资源；使用当前单文件 HTML、CSS、原生 JavaScript。
- 1920×1080 下不需要浏览器缩放即可完成主叙事；1366×768 下允许页面纵向滚动，但协作图不横向滚动。
- 触控与键盘均可选择 Agent 和时间线事件；选中状态具有清晰焦点。
- 颜色不是唯一状态信号，所有状态同时具有中文文字和图标/线型。
- 动画周期不小于 1.2 秒，不使用持续快速闪烁。

## 6. Element 录制侧栏规范

代码不修改 Element。录制前由操作员创建 `LabOps Guard · Live Demo` Space，仅保留：

1. Manager
2. Evidence Collector
3. RCA Analyst
4. Researcher（对外口径为 Experiment Planner）
5. Controlled Executor（对外口径为 Safe Executor）
6. Verification Auditor

Admin Room、POLAR-AUDIT、重复 Evidence Collector 和旧 Session 房间移出录制 Space，但不删除、不改 Room ID、不清理历史消息。

## 7. 测试与验收

### 7.1 后端单元测试

- 已验证 097 Runner 产物正确投影 Before / After、重复数、阈值与唯一变化路径。
- 缺失或冲突 Metrics 时返回 `null` 并产生限制信息。
- `DEMO_PASSED_NOT_RESOLVED` 永不投影为 `RESOLVED`。
- 恢复后使用 Attempt 02 / Run 098。
- 六个 Handoff 只有真实 Matrix event 和 Manifest 绑定后才显示已验证。

### 7.2 前端结构测试

- 页面包含 Mission Control、协作图、Human Approval、Recovery 分支、结果卡、Inspector 和工程证据区。
- 不包含写操作按钮或写 API 调用。
- 状态标签、中文文案和 `prefers-reduced-motion` 规则存在。
- 所有 API 数据通过安全文本节点渲染。

### 7.3 浏览器验收

使用 097 Live 状态完成：

- 1920×1080 截图
- 1366×768 截图
- 390×844 窄屏截图
- 点击六个 Agent、Human Approval、Recovery 和关键时间线事件
- 验证未出现横向页面滚动、文字遮挡、空白主卡或错误终态
- 验证 Reviewer 轮询更新不会清除当前 Inspector 选择

### 7.4 回归测试

运行 Reviewer、Reviewer State、Live Demo、Recovery 与完整 Python 测试套件；任何失败不得以录屏模式绕过。

## 8. 非目标

- 不重构或替换 HiClaw / AgentTeams。
- 不实现新的 Agent、Skill、MCP、RAG 或 OTel 后端。
- 不把 Element 嵌入 Reviewer iframe。
- 不允许 Reviewer 发送 Matrix 消息。
- 不修改正式 AT-002/003/004 Evidence。
- 不删除旧 Matrix 房间。
- 不把本次演示结果包装为真实生产事故已解决。

