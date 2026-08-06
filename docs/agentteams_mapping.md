# AgentTeams integration mapping

AgentTeams 负责六角色编排、Matrix 任务交接和 MinIO 共享状态；LabOps Guard 的 Skill、
Schema、Policy、Gateway、Runner 和 Auditor 负责确定性执行与验证。当前通用角色定义位于
`agentteams/agent_identities_v2.json`，不绑定 checkpoint 或单一 Demo。

| 阶段 | Agent | Skill | 结构化产物 |
|---|---|---|---|
| Receive / route / close | Incident Commander | `pack-lab-evidence`, `publish-case-memory` | task、state、bundle、case memory |
| Evidence | Evidence Collector | `collect-lab-evidence` | registry、evidence、immutable hashes |
| RCA | RCA Analyst | `diagnose-lab-incident` | evidence-ID-bound hypotheses |
| Plan | Experiment Planner | `plan-lab-experiment` | one-variable ExperimentPlan |
| Execute | Safe Executor | `control-lab-action` | approval、run、changed paths、raw outputs |
| Verify | Verification Auditor | `verify-lab-result` | independent decision、trace audit、rollback |

每次 handoff 必须包含 `task_id`、`incident_id`、当前/下一状态、输入输出相对路径、哈希、
时间、状态、生产者和未解决缺口。自然语言结论不代替文件证据；Manager 不执行或自证；
Executor 不宣布闭环；只有 Auditor 能裁决 `RESOLVED` 或 `ROLLED_BACK`。

AT-004 的真实顺序和六次交接位于正式证据包 `handoff_manifest.json`。人工批准作为独立
门禁事件记录，不计入 Agent 数量。
