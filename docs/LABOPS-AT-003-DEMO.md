# LABOPS-AT-003 专用 PyTorch Runner 演示说明

## 一句话结论

AT-002 证明“依赖缺失时安全阻塞”；AT-003 证明“经过审批的单变量修复可以交给专用、断网、受限的 PyTorch Runner，并且只有独立审计通过后才进入 `PASS / RESOLVED`”。

## 演示前检查

1. Docker Desktop 正在运行，镜像 `labops/pytorch-cpu-runner:0.1.0` 已存在。
2. AgentTeams Element、Manager 和五个 Worker 可访问。
3. 仪表盘地址为 `http://127.0.0.1:8787/`。
4. 不重跑或覆盖 AT-002；它应继续显示为 `BLOCKED`。

## 建议讲解顺序（2—4 分钟）

1. 在仪表盘顶部展示 AT-003 的 `PASS / RESOLVED`，同时指出下方 AT-002 仍是独立的 `BLOCKED` 案例。
2. 展示六角色顺序：Incident Commander、Evidence Collector、RCA Analyst、Experiment Planner、Safe Executor、Verification Auditor。
3. 展示 Planner 门禁：只修改 `eval_config.json:checkpoint`；CPU、30 秒、无网络；禁止修改 `metric.py`、验证数据、目标指标和原始工作区；失败时回滚沙箱。
4. 展示审批时序：人工批准发生在 Safe Executor 和 Runner 启动之前。
5. 解释边界：Safe Executor 不运行 PyTorch，只把结构化计划和审批提交给本机控制面；Runner 容器没有网络、没有密钥、非 root、只读并受资源限制。
6. 展示 RuntimeCapabilityCheck 全部通过，以及三次重复结果：`last.pt ≈ 70.00%`，`best.pt ≈ 98.12%`。
7. 展示受保护对象：`metric.py`、验证数据和原始工作区均未修改。
8. 展示 Verification Auditor 独立复核。首次总 Trace 审计因重复 Matrix event ID 返回 ISSUE，系统没有收口；修正后再次审计为 `CHAIN_OK / ACCEPTED`，才允许 Manager 标记 `RESOLVED`。
9. 最后展示三层完整性：证据 ZIP、包内 26 个 artifact、Runner 原始输出 manifest 全部哈希一致。

## 六角色实际交接

| 顺序 | 角色 | 主要输入 | 主要输出 |
|---|---|---|---|
| 1 | Incident Commander | AT-003 任务定义 | 任务建档与 Evidence Collector 派发 |
| 2 | Evidence Collector | incident、只读 Demo 工作区 | `collected_evidence.json`、`evidence_index.json` |
| 3 | RCA Analyst | evidence bundle | 独立 `hypotheses.json` |
| 4 | Experiment Planner | hypotheses、策略约束 | 修正后的单变量 `plan.json` |
| 5 | Safe Executor | plan、人工审批 | Runner 五文件和 Gateway 记录 |
| 6 | Verification Auditor | 原始 Runner 文件、审批、Trace | `verification.json`、最终 Trace 审计 |
| 7 | Incident Commander | 全部白名单产物 | manifest、ZIP、MinIO/host-share 同步、最终收口 |

## 证据定位

- Matrix：`handoff_manifest.json` 和 `agentteams_trace.jsonl` 保存 room/event/time。
- MinIO：`shared/tasks/LABOPS-AT-003/`。
- Runner 原始文件：`artifacts/LABOPS-AT-003-agentteams/runs/RUN-LABOPS-AT-003-AGENTTEAMS-001/`。
- 证据 ZIP：`demo/output-agentteams-at003/artifacts/DEMO-RCA-003/LABOPS-AT-003-evidence-bundle.zip`。
- 总清单：`demo/output-agentteams-at003/artifacts/DEMO-RCA-003/evidence_bundle_manifest.json`。
- 最终 Trace 审计：ZIP 内 `agentteams_trace_audit_final.json`。
- Dashboard：`http://127.0.0.1:8787/`。

## 不可越过的表述边界

- 不把 AT-003 的成功反写成 AT-002 成功；AT-002 永远按其原始证据保持 `BLOCKED`。
- 不把 Planner 文本或 Safe Executor 自述当作完成证明；以 Runner 原始文件和 Auditor 结论为准。
- 不隐去第一次 Trace 审计失败；它证明系统在证据链不完整时不会收口。
- 不宣称支持任意模型、GPU 或外部数据；AT-003 的结论只覆盖固定的 CPU PyTorch 镜像与内置确定性 fixture。
