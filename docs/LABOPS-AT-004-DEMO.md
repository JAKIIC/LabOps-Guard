# LABOPS-AT-004 评测预处理漂移主演示

## 一句话

LabOps Guard 是面向生产级 Agent 系统的可信基础设施参考实现。它用 Trust Contract v1
和 Trust State Machine v1 约束六个 Agent，并以 Identity → Policy → Execution → Evidence
→ Audit 的证据链证明一次工程行动为什么可以或不可以被信任。

## 现场演示顺序（约 4 分钟）

1. 打开 `http://127.0.0.1:8787/`，明确页面是只读 Trust Dashboard，不提供执行、修改或审批入口。
2. 从五段证据链说明六 Agent Identity、Policy/Approval、Runner、Evidence Bundle 与 Auditor 的关系。
3. 先展示危险分支：修改 `metric.py` 属于越权操作，结果被判为 `POLICY_VIOLATION / ROLLED_BACK`，终态不得标记为 `RESOLVED`。
4. 再展示合法分支：同一固定评测对象从历史约 `97.81%` 稳定降至 `71.88%`，连续三次无波动。
5. 展示证据与 RCA：checkpoint、验证集、metric、模型和评测协议哈希不变；唯一近期配置变化是 preprocessing profile。
6. 展示计划：只改沙箱 `evaluation.preprocessing_profile: train_augmented → eval_standard`；CPU、30 秒、3 次、禁网并定义回滚。
7. 展示人工审批早于执行；Safe Executor 只能执行获批 Tool Contract，不能宣布成功。
8. 展示 Runner 与后置指标：`71.875% × 3 → 97.8124976% × 3`，唯一 changed path 是沙箱预处理字段，六组受保护哈希不变。
9. 展示 Auditor：独立重算后 `PASS / RESOLVED`；总追踪链 `7 entries / CHAIN_OK / ACCEPTED`。
10. 回到 Trust Dashboard，强调没有综合评分，每个信任域分别给出证据和限制；失败项必须显示 `BLOCKED`。

## 六角色实际交接

| Handoff | From → To | 真实事件 / 产物 | 时间与状态 |
|---|---|---|---|
| 1/6 | Incident Commander → Evidence Collector | `$7epuOKu4…`；任务 contract → `collected_evidence.json` | 16:52:40Z；accepted/dispatched |
| 2/6 | Evidence Collector → RCA Analyst | `$sngWjO4j…` / `$c6FcTPum…`；证据 → `hypotheses.json` | 16:58:13Z–16:59:45Z；DONE |
| 3/6 | RCA Analyst → Experiment Planner | `$UKB6QtQx…`；假设 → `plan.json` | 17:04:45Z；AUTO_APPROVED |
| 人工门禁 | human-user | `$AsY0ve0V…`；plan → `approval.json` | 17:06:27Z；APPROVED |
| 4/6 | Experiment Planner → Safe Executor | `$mPBP-Hoa…`；审批 → 9 个执行/控制面产物 | 17:10:11Z–17:11:32Z；COMPLETED |
| 5/6 | Safe Executor → Verification Auditor | `$c9PLqgF…`；raw Runner 文件 → `verification.json` | 17:13:50Z；PASS/RESOLVED |
| 6/6 | Verification Auditor → Incident Commander | final audit artifact → manifest / ZIP | 17:42Z；CHAIN_OK/ACCEPTED |

人工审批单独记录，不计作 Agent。权威 7-entry Trace 的角色顺序为：`labops-manager → evidence-collector → rca-analyst → experiment-planner → human-user → safe-executor → verification-auditor`。

## 证据路径

- MinIO：`shared/tasks/LABOPS-AT-004-EVAL-DRIFT/`
- Runner 原始目录：`artifacts/LABOPS-AT-004-agentteams/runs/RUN-LABOPS-AT-004-AGENTTEAMS-001/`
- 主机证据包：`demo/output-agentteams-at004/LABOPS-AT-004-EVAL-DRIFT-evidence-bundle.zip`
- ZIP SHA-256：`4092b43f39df52db3847caa28ca01e4321129a1c17ec7ca5efd2029ab1fb77cd`
- 白名单：26 个证据文件 + manifest 自身，共 27 ZIP entries
- 关键文件：`handoff_manifest.json`、`agentteams_trace.jsonl`、`agentteams_trace_audit.json`、`agentteams_trace_audit_final.json`、`verification.json`、Runner 五个标准输出

## 不能说什么

- 不说“Agent 自己批准自己”；审批来自用户明确授权的独立门禁记录。
- 不说“Worker 跑了 PyTorch”；PyTorch 只在专用断网 Runner 中运行。
- 不说“支持任意模型/数据/GPU”；当前结论只覆盖固定 CPU fixture。
- 不把首次 `ISSUE` 删除或改写为通过。
- 不把 AT-004 成功回写到 AT-002/003。
