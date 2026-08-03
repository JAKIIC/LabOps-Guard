# LABOPS-AT-002 六角色实跑演示说明

## 演示目标

这次演示验证的不是“Agent 会不会说出正确步骤”，而是六个角色是否真实交接、安全门禁是否真正生效、执行后是否有可复核产物。

## 演示前检查

1. AgentTeams Element 和 Manager 房间可用。
2. Docker Desktop 正在运行。
3. 项目目录为 `E:\AICompetition\LabOpsWorkspace\labops-guard`。
4. 仪表盘地址为 `http://127.0.0.1:8787/`。

## 讲解顺序

1. 打开 AgentTeams Manager 房间，展示 `LABOPS-AT-002` 任务、人工审批 `LABOPS-AT-002-APPROVAL-001` 与 Manager 最终 `BLOCKED` 结论。
2. 在仪表盘“LABOPS-AT-002 · 六角色真实 AgentTeams”中展示六个角色和六次 handoff。
3. 展示 Planner 门禁：合法计划只改一个 checkpoint 字段，预算为 CPU/30s/无网络，明确禁改 `metric.py`、dataset 和 target，并定义回滚。
4. 展示 Safe Executor 仅在人工审批后运行，并且仅在沙箱内操作。
5. 展示合法案例的事实边界：修改路径合法、`metric.py` 哈希未变，但 AgentTeams Worker 缺少 `torch`，因此结论是 `INCONCLUSIVE / DEMO_PASSED_NOT_RESOLVED`，不是 `PASS / RESOLVED`。
6. 展示非法案例：篡改被检出，非法计划被 `POLICY_REJECTED`，沙箱回滚后 `metric.py` 哈希与冻结基线一致，结论为 `POLICY_VIOLATION / ROLLED_BACK`。
7. 展示审计链和包完整性：8 + 9 条真实事件，55 个 artifact，ZIP 和包内哈希均由仪表盘服务端独立重验。
8. 最后下滚到“本地参考 Demo”，说明 `d2l` 环境可完成确定性 `PASS / RESOLVED`，但不把它当作 AgentTeams 真实执行成功证据。

## 证据定位

- Matrix：每次 handoff 的 `matrix_room` 记录在 `artifacts/handoff_manifest.json`。
- MinIO：`shared/tasks/LABOPS-AT-002/`。
- 本地 Artifact：`demo/output-agentteams-at002/LABOPS-AT-002-evidence-bundle.zip`。
- 总清单：`demo/output-agentteams-at002/evidence_bundle_manifest.json`。
- Trace：ZIP 内 `artifacts/DEMO-RCA-001/trace.jsonl` 和 `artifacts/DEMO-RCA-002/trace.jsonl`。
- Dashboard：`http://127.0.0.1:8787/`。

## 一键启动展示

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\docker-start.ps1 -Rebuild
```

若只需重跑本地 checkpoint 参考 Demo：

```powershell
conda run -n d2l python -B -m labops run-incident --incident demos\checkpoint-regression\incident-valid.json
conda run -n d2l python -B -m labops run-incident --incident demos\checkpoint-regression\incident-unsafe.json
```

## 不可越过的表述边界

- 不说“LABOPS-AT-002 全部通过”；总状态是 `BLOCKED`。
- 不说“合法 AgentTeams 案例已修复”；它缺少真实 accuracy 后置条件。
- 不把 Planner 提示词或文本回复当作执行证据。
- 可以说“六角色真实运行、安全门禁生效、非法篡改完整阻断与回滚”。
