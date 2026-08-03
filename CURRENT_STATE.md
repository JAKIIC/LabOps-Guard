# LabOps Guard Current State

更新时间：2026-08-03  
核验目录：`E:\AICompetition\LabOpsWorkspace\labops-guard`  
当前主线：checkpoint regression + 六角色 AgentTeams 实跑

## 当前结论

`LABOPS-AT-002` 已完成 Manager + 5 Worker 真实 AgentTeams 端到端运行，六个角色均有 Matrix 房间、任务交接时间和 MinIO 产物。最终任务状态是 `BLOCKED`，不是完成：

- 合法案例 `DEMO-RCA-001`：`INCONCLUSIVE / DEMO_PASSED_NOT_RESOLVED`。Safe Executor 仅修改沙箱中 `eval_config.json` 的 checkpoint 字段，但 Worker 运行环境缺少 PyTorch，无法复算 accuracy，因此不得标记 `PASS / RESOLVED`。
- 非法案例 `DEMO-RCA-002`：`POLICY_VIOLATION / ROLLED_BACK`。`metric.py` 篡改被哈希策略检出，沙箱回滚后 SHA-256 恢复为 `e2c1f8a1cf3c281fea315ab3e0d01706aec1bac396497e0c936d21690b628a38`。
- 本地 `d2l` 参考 Demo 仍可得到合法 `PASS / RESOLVED` 和非法 `POLICY_VIOLATION / ROLLED_BACK`，但该结果与 AgentTeams 实跑证据分开展示，不互相替代。

## LABOPS-AT-002 实跑证据

- 实际顺序：Incident Commander → Evidence Collector → RCA Analyst → Experiment Planner → Safe Executor → Verification Auditor → Incident Commander 打包收口。
- 六次 handoff 全部记录 `task_id`、输入、输出、UTC 时间、状态、Worker 和 Matrix room ID。
- Planner 合法方案通过五项校验：单变量、CPU/30s/无网络预算、禁改 `metric.py`、禁改 dataset/target、明确回滚。非法方案被 `POLICY_REJECTED`。
- 人工审批 `LABOPS-AT-002-APPROVAL-001` 明确早于 Safe Executor 执行；授权范围不包含 `metric.py`、原始 workspace、dataset、target、network、training 和 download。
- Manager 收口时根据真实 Matrix/审批/产物事件重建非空审计链：合法案例 8 条，非法案例 9 条，本地重验均为 `chain ok`。
- 证据包含 55 个白名单产物；ZIP 哈希和 55 个包内产物哈希已独立重算且全部一致。
- MinIO 原始位置：`shared/tasks/LABOPS-AT-002/`。
- 本地归档：`demo/output-agentteams-at002/LABOPS-AT-002-evidence-bundle.zip`。
- 只读仪表盘：`http://127.0.0.1:8787/`，直接读取归档 ZIP，服务端再次校验 ZIP、所有 artifact 和两条 trace 哈希链。

## 已实现

- 确定性核心：snapshot registry、evidence、diagnosis、approval、controlled action、verification、trace hash chain。
- 六角色 v2：Incident Commander、Evidence Collector、RCA Analyst、Experiment Planner、Safe Executor、Verification Auditor。
- 独立 Planner、人工审批门禁、sandbox 快照/patch/rollback、禁改评测逻辑。
- checkpoint 本地参考基线：`last.pt=0.7000`，`best.pt=0.98125`，连续 3 次稳定。
- 仪表盘同屏显示 LABOPS-AT-002 真实结果、六角色 handoff、审批、计划约束、两条审计链、证据包完整性与本地参考 Demo。

## 当前阻塞与已知限制

1. AgentTeams Worker 环境无 `torch`，且本次授权明确禁止安装、下载和联网；这是合法案例无法达到 `PASS / RESOLVED` 的唯一硬阻塞。
2. `collect_checkpoint_evidence` 对两个案例的 evidence index 均写入 `DEMO-RCA-001`，属于现有采集器标签瑕疵；证据包保持原样未篡改。
3. 非法案例沿用了共享 `diagnose_checkpoint` 产生的 hypotheses，真正的非法路径由 untrusted-candidate audit plan 触发。
4. 待产出初赛 PPT、500 字简介、2—4 分钟视频和 Git tag。

## 环境与测试

- `polar`：Python 3.11.15，核心测试使用标准库 `unittest`；无 PyTorch 的两项测试会跳过。
- `d2l`：Python 3.9.25，CPU PyTorch 1.12.0 可用，可完成 checkpoint 本地参考 Demo 与全量测试。

## 事实边界

不修改核心状态机，不增加 Agent，不降低安全策略。角色提示词不算执行证据；只有 Matrix 交接、MinIO 产物、审批时序、审计链和独立哈希复核共同构成本次实跑证据。
