# LabOps-Guard 复赛最终 Demo 视频脚本

目标时长：**3:55**；硬上限：5:00。最终策略：**Strategy C — Verified Replay + Live Verification**。

## 真实性标识

- `LIVE CHECK · 2026-08-26`：当前机器的在线服务、Manager 防重复门禁、Evidence verifier 和只读 Dashboard。
- `ARCHIVED VERIFIED RUN · 2026-08-04`：真实发生的 AT-004 六角色 Matrix 交接、Runner 与 Auditor 记录。
- 不使用“实时重跑”描述历史素材，不把 Public Evidence Replay 称为 AgentTeams live execution。

选择 Strategy C 的依据：2026-08-26 16:33 向在线 Manager 发送冻结 AT-004 Prompt 后，Manager 在
16:34 独立复核到该固定 task/run ID 已于 2026-08-04 `RESOLVED`，因此拒绝重复执行并等待管理员
决定。未清理状态、未换 incident ID、未复用审批。历史真实运行从 16:52:40 到 17:13:50，约
21 分 10 秒，不适合四分钟一镜到底。

## 0:00–0:25｜真实实验室问题

**画面：** 标题页；随后展示“发现 → 找证据 → 讨论 → 审批 → 修改重跑 → 复核 → 分散归档”。

**旁白：**

> 一次评测漂移，往往要经过值班发现、工程师找证据、研究员讨论、负责人审批、修改重跑和独立
> 复核。成本来自人工接触、消息往返、重复运行和证据整理。当 Agent 开始承担这些动作，关键问题
> 不再只是它聪不聪明，而是：它是谁、谁批准、真正执行了什么，以及结果是否独立验证。

## 0:25–0:50｜项目定位

**画面：** PPT Trust Layer 架构页，依次高亮 Identity、Skill、Policy、Approval、Execution、
Evidence、Audit。

**旁白：**

> LabOps-Guard 是面向生产级 Agent 系统的可信基础设施。六个 Agent 通过版本化 Skill 协作；
> Policy 和人工审批限制动作；受控 Runner 隔离执行；Evidence 与独立 Auditor 决定是否闭环。
> 它不生成 Trust Score，也不是在线控制台。

## 0:50–1:25｜真实 AgentTeams 证据

**画面：** 左上角固定显示 `ARCHIVED VERIFIED RUN · 2026-08-04`。Element 中依次展示 Manager
和五个 Worker 房间；放大真实发送者、任务引用与 Matrix event ID。随后展示七条哈希链 Trace。

**旁白：**

> 这里不是脚本模拟。Manager 是 Incident Commander，五个 Worker 分别承担证据收集、根因分析、
> 实验规划、安全执行和独立审计。真实 AT-004 记录包含六次角色交接和一次人工审批；每个交接都
> 有时间、输入、输出和 Matrix event ID。Agent 是职责边界，Skill 是可复用契约，Tool 是外部
> 执行接口，三者相互独立。

**补充画面（2–3 秒）：** 显示新 live verifier 的 Skill runtime evidence 边界：
`control-lab-action = GATEWAY_CONTRACT_READY/VERIFIED`，其余六个为
`CONFIGURED / AGENTTEAMS_HOOK_REQUIRED`。只有真实新 live run 后才显示 `VERIFIED`。

## 1:25–1:55｜AT-002 异常治理路径

**画面：** Public Evidence Replay 的 AT-002 风险分支，突出 `POLICY_VIOLATION`、protected
resource、rollback verification。

**旁白：**

> 异常路径中，Agent 提出修改受保护 `metric.py` 的危险方案。Policy 和受保护资源边界拒绝对
> 真实资源执行；随后仅在隔离的 adversarial、tampered fixture 上验证检测能力，最终得到
> `POLICY_VIOLATION` 和 rollback verification。这里不是“生产 metric 已被越权修改后才发现”。

> 对证据不全、timeout、能力缺失、工具失败或审计不确定，系统不会覆盖原状态：它创建新 attempt，
> 受预算约束地 retry；没有真实备用 Worker 时记录 `REASSIGN_UNAVAILABLE`，再由真人接受 Human
> Takeover。接管者不能直接关闭事故，最终仍由 Auditor 裁决。

## 1:55–2:55｜AT-004 合法执行与独立裁决

**画面：** `ARCHIVED VERIFIED RUN · 2026-08-04`。依次展示 `plan.json`、`approval.json`、
Gateway request、Runner status/metrics/manifest、`verification.json`。用高亮框显示唯一变更路径、
`network=none`、三次重复指标和 Auditor verdict。

**旁白：**

> 合法路径只允许把沙箱中的预处理配置从 `train_augmented` 恢复为 `eval_standard`。Policy 通过后，
> Manager 请求独立真人审批；ApprovalGrant 强绑定计划哈希、范围、保护资源、预算、时效与 nonce，
> 任一不一致或重放都会 fail closed。Safe Executor 才能调用 Gateway。Runner 在 CPU、禁网、只读根文件
> 系统和 30 秒预算内执行。三次基线均为 71.875%，三次候选均为 97.8124976%。准确率恢复只是
> 验证载体：关键是只有批准的配置发生变化，checkpoint、数据、metric、protocol、模型和代码哈希
> 均保持不变。最终 `PASS / RESOLVED` 由 Verification Auditor 从原始输出独立重算，不由 Executor
> 自证。

## 2:55–3:30｜当前实时验证与只读 Dashboard

**画面：** 左上角切换为 `LIVE CHECK · 2026-08-26`。终端运行 Evidence verifier；随后打开当前
Dashboard，展示 Identity → Policy → Execution → Evidence → Audit，并短暂显示写请求为 `405`。

**旁白：**

> 当前机器上，三个正式 Evidence Bundle 的 SHA-256、成员清单和 Trace 均可独立验证。Dashboard
> 是 Read-only Evidence Projection：它从允许列表内的证据生成视图；证据缺失或篡改会显示
> `BLOCKED`，页面不能执行、修改或审批任何动作。

## 3:30–3:55｜Evaluation Suite 与开放价值

**画面：** Trust Evaluation Suite 报告，再切 GitHub README 与 Public Demo URL。

**旁白：**

> Trust Evaluation Suite 不是通用 Agent Benchmark。它用 10 个固定治理案例验证 Policy violation
> prevention、Evidence completeness、False resolution prevention 和 Independent audit。系统判定与
> 预设 Oracle 全部一致；8 个不应关闭的案例没有发生错误关闭。Identity、Skill Registry、Tool
> Contract、Runner 契约、Schema、Trace 和验证器均以 Apache-2.0 源码开放。
>
> LabOps-Guard does not make agents smarter. It makes agent execution verifiable and governable.

## 录制降级规则

1. Element 房间不可用：使用 2026-08-04 真实 Matrix 素材，并保持 `ARCHIVED VERIFIED RUN` 标识。
2. Dashboard 不可用：保留 Evidence verifier 与 Public Evidence Replay，不声称在线 Dashboard。
3. Docker 不可用：不现场修复，展示已有 Runner manifest、Gateway response 和独立验证结果。
4. 任一画面可能暴露 Token、密码、私有房间或主机绝对路径：立即停录并废弃该 take。
5. 没有实际产生新 live Recovery/Skill Evidence：只展示 verifier readiness 和历史事实，不把
   `CONFIGURED` 说成 runtime invocation，也不把设计图说成已经发生的事件。
