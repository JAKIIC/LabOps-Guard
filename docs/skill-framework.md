# LabOps-Guard Skill Framework

## 1. 定位与事实边界

Skill 是版本化、可发现、可校验的能力契约；Agent 是责任与决策边界；Tool 是产生外部副作用
或读取外部执行结果的接口。权威来源是 `skills/registry.json`、各 Skill 的 `SKILL.md` 与
`references/io-schema.json`。Registry 验证版本、Owner、依赖和 I/O 合约，但不是远程
Marketplace，也不启动或调度 Skill。

历史 AT-004 Evidence 能证明角色、Matrix handoff、审批、Runner、Evidence 与 Auditor，但没有
独立 `skill_id` usage event。本文件不从角色执行反推历史 Skill 调用。

## 2. 七个正式 Skill

| Stage | Skill | Version | Owner Agent | Tool / dependency |
|---|---|---:|---|---|
| Evidence Collection | `collect-lab-evidence` | 0.2.0 | `evidence-collector` | allowlisted filesystem、SHA-256 |
| RCA | `diagnose-lab-incident` | 0.2.0 | `rca-analyst` | evidence store |
| Safe Planning | `plan-lab-experiment` | 0.2.1 | `experiment-planner` | policy engine |
| Controlled Execution | `control-lab-action` | 0.2.0 | `safe-executor` | Runner Gateway、sandbox Runner |
| Independent Verification | `verify-lab-result` | 0.2.0 | `verification-auditor` | Runner artifacts、Trace verifier |
| Evidence Packaging | `pack-lab-evidence` | 0.2.0 | `labops-manager` | artifact store、SHA-256 |
| Case Memory | `publish-case-memory` | 0.1.0 | `labops-manager` | local case-memory store |

数量固定为 7。后两个是 Incident Commander 的收口能力，不是新 Agent。

## 3. Agent / Skill / Tool

```text
Agent: responsibility and decision boundary
  └─ invokes → Skill: reusable, versioned capability contract
                  └─ may call → Tool: governed external interface
                                   └─ produces → Artifact / Trace / Evidence
```

例如 `safe-executor` 使用 `control-lab-action` 校验策略、审批和执行边界；Skill 调用 Runner
Gateway；Gateway 才能启动断网 Runner。Runner 输出交给独立 Auditor，Executor 不能自证。

## 4. Skill Pipeline

```text
Incident
  → collect-lab-evidence
  → diagnose-lab-incident
  → plan-lab-experiment
  → [Policy + Human Approval]
  → control-lab-action
  → verify-lab-result
  → pack-lab-evidence
  → publish-case-memory
```

即：Incident → Evidence Collection → RCA → Safe Planning → Controlled Execution →
Independent Verification → Evidence Packaging → Case Memory。

## 5. 五个核心 Skill 契约

### 5.1 Evidence Collector — `collect-lab-evidence`

- **Name / Version / Owner:** Collect Lab Evidence / 0.2.0 / `evidence-collector`
- **Purpose:** 把显式 allowlist 内的事实注册为可追踪 Evidence，不做诊断。
- **Invocation Condition:** incident contract 与只读 allowlist 已存在。
- **Input:** task/incident、snapshot、allowed list、audit dir、verification、workspace。
- **Output:** registry record、collected evidence、计数、gaps、拒绝项、handoff state。
- **Required Tool / Dependency:** allowlisted filesystem、SHA-256；绑定 `labops.registry`、
  `labops.evidence` 和 CLI `init/evidence`。
- **Failure Handling:** 缺字段、路径逃逸、hash/schema 错误或排除数据访问 → `BLOCKED`。
- **Security Boundary:** 只读 allowlist；不得读取秘密/私有数据、下载、训练或修改快照。
- **Validation Method:** 路径边界、SHA-256、Evidence Schema、`excluded_data_not_read`。
- **Reuse Scenario:** 替换快照、allowlist 和 Evidence workspace，用于评测或工程事故 intake。

```text
Input: verified snapshot + allowlist
Invocation: incident accepted && read scope exists
Output: registry_record + collected_evidence + gaps
Failure: path/hash/schema violation → BLOCKED
```

### 5.2 RCA Analyst — `diagnose-lab-incident`

- **Name / Version / Owner:** Diagnose Lab Incident / 0.2.0 / `rca-analyst`
- **Purpose:** 从注册 Evidence 与 gaps 生成有引用、可证伪的候选假设。
- **Invocation Condition:** schema-valid Evidence 存在且含稳定 `evidence_id`。
- **Input:** task/incident、registry record、collected evidence。
- **Output:** diagnosis candidates、状态统计、Evidence links、gaps、handoff state。
- **Required Tool / Dependency:** evidence store；绑定 `labops.diagnosis`，AT-004 绑定
  `labops.at004.diagnose_eval_drift`。
- **Failure Handling:** Evidence 未就绪、悬空 ID、unsupported assertion → `UNKNOWN/BLOCKED`。
- **Security Boundary:** 不打开原始快照或排除数据，不执行命令。
- **Validation Method:** Evidence ID 解析、Hypothesis Schema、反证和证伪条件。
- **Reuse Scenario:** 提供项目 Evidence taxonomy，复用证据引用规则。

### 5.3 Experiment Planner — `plan-lab-experiment`

- **Name / Version / Owner:** Plan Lab Experiment / 0.2.1 / `experiment-planner`
- **Purpose:** 把一个有证据支持的假设转为单变量、有限预算、可回滚计划。
- **Invocation Condition:** 选定可证伪假设并有至少一个可解析 Evidence ID。
- **Input:** `hypothesis_id`、`evidence_ids`、`claim`。
- **Output:** plan、单一 change、command、success criteria、budget、risk、approval、rollback。
- **Required Tool / Dependency:** policy engine；绑定 `labops.planner` 与 Plan Schema。
- **Failure Handling:** 缺 Evidence、越权变化、预算/rollback/schema/policy 错误 →
  `REJECTED/BLOCKED`。
- **Security Boundary:** Planner 不执行；保护 metric、数据、协议和原工作区。
- **Validation Method:** Plan Schema、`check_plan_policy`、单变量/预算/禁网检查。
- **Reuse Scenario:** checkpoint、preprocessing profile 或其他显式 allowlist 可逆变更。

规划 Skill 自身是 `read_only_auto`；计划仍可设置 `approval_required=true`，必须经过后续 Policy
与 Human Approval，不能据此执行。

### 5.4 Safe Executor — `control-lab-action`

- **Name / Version / Owner:** Control Lab Action / 0.2.0 / `safe-executor`
- **Purpose:** 执行策略、审批与能力门禁，只在沙箱调用 allowlisted Runner。
- **Invocation Condition:** 具有动作上下文；真正执行必须有有效 Tool Contract 与绑定 Approval。
- **Input:** 通用 Skill 合约使用 task/incident/hypothesis/action、command intent、workspace 和
  postcondition；AT-004 Adapter 提交 `ExperimentPlan + Approval + Tool Contract`。
- **Output:** policy/approval、dry-run/执行状态、Runner Artifact、changed paths、handoff state。
- **Required Tool / Dependency:** `labops.runner_gateway`、`labops.runner`、Docker sandbox。
- **Failure Handling:** capability、审批、策略、run ID、timeout 或保护路径异常 → fail closed。
- **Security Boundary:** sandbox-only、CPU、`network=none`、非 root、只读 rootfs、资源预算；
  Worker 不持有 Docker socket/PyTorch。
- **Validation Method:** Skill I/O、Tool Contract、Gateway allowlist、审批时序、Runner manifest、
  changed paths 与保护哈希。
- **Reuse Scenario:** 绑定兼容离线 Runner，用于模型评测、数据处理或受控工程任务。

```text
Input: Approved ExperimentPlan + Approval + Tool Contract
Invocation: policy passed && approval exists && approval precedes run
Tool: Runner Gateway → restricted Runner
Output: Run Result + Metrics + Artifact Manifest + raw logs
Failure: capability / timeout / policy mismatch → fail closed
```

### 5.5 Verification Auditor — `verify-lab-result`

- **Name / Version / Owner:** Verify Lab Result / 0.2.0 / `verification-auditor`
- **Purpose:** 从原始数据独立重算后置条件、哈希、审批顺序和 Trace，并独占终态裁决。
- **Invocation Condition:** 原始 Runner 输出、计划、审批、运行前哈希与 Trace 可用。
- **Input:** task/incident、workspace、action result、postcondition、Trace；AT-004 还读取
  metrics、stdout、manifest 和 protected hashes。
- **Output:** verification checks、Trace result、incident state、是否真实解决、handoff。
- **Required Tool / Dependency:** Runner artifacts、Trace verifier；绑定 `labops.verify`、
  `labops.at004.verify_run` 和 Evidence verifier。
- **Failure Handling:** 缺 Artifact、hash/Trace/路径/重算异常 → `BLOCKED/ROLLED_BACK`。
- **Security Boundary:** 不修改或重生成审计对象，不接受 Executor 自述分数。
- **Validation Method:** 原始指标重算、manifest SHA-256、审批时序、保护哈希、Trace chain。
- **Reuse Scenario:** 注入项目 postcondition 与 protected manifest，复用独立审计规则。

## 6. Commander Skills

### `pack-lab-evidence`

- **Name / Version / Owner:** Pack Lab Evidence / 0.2.0 / `labops-manager`
- **Purpose / Invocation:** Auditor 终态与有效 Trace 后打包 allowlisted Artifact。
- **Input / Output:** workspace、verification、Trace、output → ZIP、SHA-256、manifest、exclusions。
- **Tool:** artifact store、SHA-256、`skills/pack-lab-evidence/scripts/build_bundle.py`。
- **Failure / Security:** 缺 Artifact、Trace invalid、越界或 disallowed content → 不生成最终包；
  不打包数据集、秘密、checkpoint 或环境文件。
- **Validation / Reuse:** allowlist、member hash、路径边界；可替换项目 Artifact allowlist。

### `publish-case-memory`

- **Name / Version / Owner:** Publish Case Memory / 0.1.0 / `labops-manager`
- **Purpose / Invocation:** terminal verification、有效 Trace 和 immutable bundle 后发布 Case Memory。
- **Input / Output:** verification、Trace、source bundle/hash、closure workspace → postmortem、
  case memory、独立 closure bundle、index record。
- **Tool:** `labops.case_memory` local JSON store。
- **Failure / Security:** 非终态、hash/Trace/path/content 错误 → `BLOCKED`；排除凭据、私有数据、
  绝对路径和原始聊天。
- **Validation / Reuse:** bundle hash、terminal authority、搜索回读；历史记忆不能替代新 Evidence。

## 7. I/O 校验

```powershell
python -B -m labops skills list
python -B -m labops skills describe control-lab-action --caller-agent-id safe-executor
python -B -m labops skills validate <skill-id> <input.json> --caller-agent-id <agent-id>
python -B -m labops skills validate-output <skill-id> <output.json> --caller-agent-id <agent-id>
```

Registry 验证 Owner、版本、依赖和必填字段；Evidence、Hypothesis、Plan、Tool Contract、Run、
Verification 与 Trace 另由领域 Schema、Policy 或 hash validator 深度验证。I/O 合约是结构化字段
契约，不宣称完整静态类型系统。

## 8. Future live Skill usage observability

已实现：

- `schemas/skill_usage_event.schema.json`：只验证未来真实 live event；
- `python -B -m labops skills validate-event <event.json>`：校验 Registry 版本、Owner、I/O
  version、时间顺序、相对 Artifact 路径与 SHA-256；不写文件；
- `demo-readiness`：显示七 Skill 的预期 pipeline、版本、Owner 与可见性门禁。

未实现：仓库没有 HiClaw/Matrix Worker runtime hook，因此没有自动 emitter、后台服务或历史
回填。状态明确为 `runtime_event_emission=NOT_IMPLEMENTED`、
`live_visibility=AGENTTEAMS_HOOK_REQUIRED`。

新 live run 有一个更窄且可核验的例外：Runner Gateway 在成功执行前会规范化并归档
`gateway_request.json#tool_contract`。`live-demo verify` 会对完整契约做 fail-closed 核验，只有
`safe-executor → control-lab-action → labops.runner.execute` 以及 task / incident / run /
approval 全部一致时，才把 `control-lab-action` 标记为 `VERIFIED`。这证明的是
Safe Executor Skill 与受控工具的实际绑定，不是通用 Skill telemetry，也不能外推为七个
Skill 都有 runtime event。其余六个仍为 `CONFIGURED / AGENTTEAMS_HOOK_REQUIRED`。

未来 event 必须由实际执行 Skill 的 Worker/AgentTeams hook 在调用时产生，使用真实时间、真实
Matrix/AgentTeams event ID 和 Artifact SHA-256。Manager 事后补写或从角色名推断都不是证据。

以下只是字段模板，不是执行证据：

```json
{
  "schema_version": "1.0",
  "run_mode": "LIVE_AGENTTEAMS",
  "event_id": "<real-event-id>",
  "task_id": "<new-live-task-id>",
  "incident_id": "<new-live-incident-id>",
  "skill_id": "control-lab-action",
  "skill_version": "0.2.0",
  "owner_agent": "safe-executor",
  "input_schema_version": "1.0",
  "output_schema_version": "1.0",
  "started_at": "<runtime-start-UTC>",
  "completed_at": "<runtime-end-UTC>",
  "status": "COMPLETED",
  "input_artifact_refs": [{"path": "<relative-path>", "sha256": "<real-sha256>"}],
  "output_artifact_refs": [{"path": "<relative-path>", "sha256": "<real-sha256>"}],
  "trace_reference": {"source": "matrix", "event_id": "<real-event-id>"}
}
```

若 live 部署没有 hook，除上述 Gateway 绑定外，其余 Skill 只能表述“Registry 与 Skill
契约已配置”，不得说 runtime usage 已被证明。历史 AT-004 仍不含 `skill_id`
event，不回填。

## 9. PPT / README 可复用位置

- 第 6 页 Identity + Skill Registry：七 Skill 总览、Agent/Skill/Tool 三层图。
- 第 8 页 Tool Contract + Runner：Safe Executor 契约示例，可引用新 live run 的
  `gateway_request.json#tool_contract`，标注“仅 control-lab-action runtime binding”。
- 第 10 页 Trace + Evidence：usage event 字段，标注“new live run only”。
- 第 11 页 Trust Dashboard：Registry valid、7 Skills、hook required。
- 答辩口径：历史 AT-004 无 `skill_id` event；新 live Gateway 证据可证明
  `control-lab-action` 的工具绑定；其余六个的真实 event 发射仍依赖 live hook。

## 10. 成熟度结论

当前达到仓库原生、版本化、Owner 受控、输入输出可校验、失败安全、可复用的工程级 Registry；
核心 Skill 与 Policy/Gateway/Runner/Auditor 有代码绑定。尚未达到自动 runtime instrumentation、
远程 Marketplace 或统一遥测平台，应表述为“Skill contract engineering + live-hook-ready
validation”，不是“已部署 Skill telemetry”。

## 11. Version, release, rollback and quality gates

| Lifecycle concern | Current gate |
|---|---|
| Version | Each Registry entry and `SKILL.md` has an explicit version; I/O versions are validated |
| Release | Registry, Owner, dependency and Schema references must resolve; unit/contract tests and sensitive-data checks must pass |
| Rollback | Revert to the most recent verified Git commit and Registry version; there is no unreviewed dynamic rollback in a live incident |
| Compatibility | The Trust Contract references the Registry; aliases are read-only compatibility metadata and never grant permission |
| Quality evaluation | Schema/Policy/security tests, the 10-case Trust Evaluation Suite and Evidence verifier are independent gates |
| Distribution | Seven repository-native Skills are open-source packages; this candidate does not claim a remote Marketplace |

The AT-004 chain has no cloud-resource action, so adding an official cloud Skill would introduce
credentials and reproducibility risk without improving the governed execution proof. A future
official Skill is treated as a Tool dependency adapter: it must preserve the same I/O, permission,
Approval and audit boundaries and cannot bypass the Verification Auditor. Toolchain versions and
migration costs are recorded in [`toolchain-compatibility-matrix.md`](toolchain-compatibility-matrix.md).
