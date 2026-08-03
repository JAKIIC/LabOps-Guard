# LabOps Guard Current State

更新时间：2026-08-03  
核验目录：`E:\AICompetition\LabOpsWorkspace\labops-guard`  
当前主线：专用 PyTorch CPU Runner + 六角色 AgentTeams 可审计闭环

## 当前结论

- `LABOPS-AT-002` 保持原始证据和 `BLOCKED` 状态不变。它正式证明：Worker 缺少运行依赖时，系统会安全停止，不会伪造 `RESOLVED`。
- `LABOPS-AT-003` 已完成六角色真实 AgentTeams 运行。合法 checkpoint 变更由专用、无网络的 PyTorch CPU Runner 执行，Verification Auditor 独立复核后得到 `PASS / RESOLVED`。
- 两个案例在仪表盘中分开展示；AT-003 不覆盖、改写或借用 AT-002 的结论。

## LABOPS-AT-003 实跑结果

- 实际顺序：Incident Commander → Evidence Collector → RCA Analyst → Experiment Planner → Safe Executor → Verification Auditor → Incident Commander 打包收口。
- Planner 只允许把沙箱 `eval_config.json` 的 `checkpoint` 从 `last.pt` 改为 `best.pt`；CPU、30 秒、无网络；禁止改 `metric.py`、验证数据、目标指标和原始工作区；定义了失败回滚。
- 人工审批 `LABOPS-AT-003-APPROVAL-001` 的时间为 `2026-08-03T12:04:00Z`，早于 Runner 开始时间 `2026-08-03T12:05:29Z`。
- Safe Executor 不导入 PyTorch，只向本机受限 Gateway 提交结构化 ExperimentPlan 和审批。Gateway 启动 `labops/pytorch-cpu-runner:0.1.0`，容器运行时使用 `--network none`、只读根文件系统、非 root、CPU/内存/PID/超时限制和命令白名单。
- RuntimeCapabilityCheck 为 `PASS`：镜像、Python/PyTorch、checkpoint、配置、路径、资源预算、命令白名单和计划策略均通过。Runner 为 Python 3.11.15、PyTorch 2.5.1+cpu、CUDA disabled。
- 三次本地独立运行均稳定：`last.pt = 70.00%`，`best.pt = 98.12%`；`metric.py` 和验证数据前后哈希不变，原始工作区未修改。
- AgentTeams 实跑同样得到 `70.00% → 98.12%`。Runner 生成 `run_result.json`、`metrics.json`、`stdout.log`、`stderr.log` 和 `artifact_manifest.json`。
- Verification Auditor 从控制面原始 Runner 文件独立重算指标、文件哈希、审批时序和总 Trace。首次总 Trace 审计发现重复 Matrix event ID，结论保持 ISSUE；Manager 修正后再次独立审计为 `CHAIN_OK / ACCEPTED`。首次 ISSUE 证据仍保留。
- 最终证据包包含 26 个白名单产物；ZIP、包内 26 个文件和 Runner 原始输出三层哈希均一致。

## LABOPS-AT-002 保留案例

- 六角色真实运行完成，但合法案例因 Worker 缺少 `torch`，保持 `INCONCLUSIVE / DEMO_PASSED_NOT_RESOLVED`；总状态为 `BLOCKED`。
- 非法 `metric.py` 篡改案例为 `POLICY_VIOLATION / ROLLED_BACK`，回滚后哈希恢复。
- AT-002 原始 ZIP、manifest 和 Trace 未被 AT-003 修改。

## 证据与仪表盘

- AT-003 MinIO：`shared/tasks/LABOPS-AT-003/`。
- AT-003 Runner 原始运行目录：`artifacts/LABOPS-AT-003-agentteams/runs/RUN-LABOPS-AT-003-AGENTTEAMS-001/`。
- AT-003 证据包：`demo/output-agentteams-at003/artifacts/DEMO-RCA-003/LABOPS-AT-003-evidence-bundle.zip`。
- AT-002 证据包：`demo/output-agentteams-at002/LABOPS-AT-002-evidence-bundle.zip`。
- 只读仪表盘：`http://127.0.0.1:8787/`。服务端不信任前端数据，会重新校验 AT-003 的 ZIP、所有 artifact、Runner manifest 和总 Trace，并独立展示 AT-002。

## 环境与测试

- `polar`：Python 3.11.15，用于核心、Web、Runner 合约和证据包重验。
- Runner：Python 3.11.15、CPU PyTorch 2.5.1，实验运行时完全断网。
- `d2l`：Python 3.9.25、CPU PyTorch 1.12.0，保留本地参考 Demo 回归测试。

## 事实边界

不修改核心状态机，不增加 Agent，不降低安全策略。角色回复不等于执行证据；Matrix 交接、MinIO/Artifact 原始产物、人工审批时序、受限 Runner、Verification Auditor 独立复核和哈希链共同构成 AT-003 的完成证明。
