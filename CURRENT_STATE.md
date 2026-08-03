# LabOps Guard Current State

更新时间：2026-08-03  
核验目录：`E:\AICompetition\LabOpsWorkspace\labops-guard`  
新路线：兜底 checkpoint regression Demo 优先，Polar 作为扩展案例

## 结论

项目不是空仓库。现有实现已经完成一条安全、可审计的 Polar 证据缺口纵向切片，
并真实跑通 AgentTeams、Matrix、MinIO、人工审批、独立验证和证据打包。但新的
`DEMO-RCA-001` checkpoint 回退主 Demo 尚未实现，不能将旧演示等同于新计划完成。

## 已实现

- 确定性核心：snapshot registry、evidence、diagnosis、approval、controlled action、verification、trace hash chain。
- 5 个可复用 Skill：证据采集、诊断、受控执行、验证、证据打包。
- AgentTeams 纵向切片：5 个不同职责 Agent、5 次 handoff、Matrix 通知、MinIO 产物。
- 安全门禁：默认 dry-run、危险动作模拟、禁止动作拒绝、路径边界、超时、审批拒绝和超时。
- 事实边界：模拟执行只能得到 `DEMO_PASSED_NOT_RESOLVED`，不得伪造 `CLOSED`。
- 展示：Docker 本地只读仪表盘，展示真实 AgentTeams 证据。
- 测试：45 项标准库单元测试通过。

## 部分实现

- Evidence Collector 能处理白名单证据和缺口，但尚未针对 checkpoint、metric 哈希、Git commit 做专用提取。
- RCA 有规则诊断器，但没有 best/last checkpoint 不一致规则。
- Executor 有命令白名单、路径限制、dry-run 和超时，但没有完整 sandbox 副本、patch、Git 快照和 rollback。
- Verifier 能阻止模拟结果闭环，但没有合法 checkpoint 修复和篡改 `metric.py` 的双案例。
- AgentTeams 当前是 Manager + 4 个专业 Worker，缺少独立 Experiment Planner。

## 未实现

- `DEMO-RCA-001` checkpoint regression Demo。
- `CURRENT_STATE.md` 之前不存在；本文件为首次现场核验记录。
- 8 个正式 JSON Schema。
- `python -m labops run-incident` 统一入口。
- Experiment Planner。
- 完整沙箱快照与回滚。
- `PASS` / `POLICY_VIOLATION` 两个端到端案例。
- Postmortem 与案例记忆。
- 初赛 PPT、500 字简介、2—4 分钟视频和 Git tag。

## Git 状态

- 正式 E 盘 `labops-guard` 目录当前不是独立 Git 仓库。
- Codex 工作副本位于一个上层工作区 Git 仓库内，但项目文件尚未跟踪。
- 在建立 checkpoint Demo 基线并完成敏感文件检查后，应为正式项目初始化独立 Git。

## 环境核验

- `polar`：Python 3.11.15，NumPy 可用，PyTorch/pytest 不可用。
- `d2l`：Python 3.9.25，CPU PyTorch 1.12.0 可用，无需下载依赖。
- 当前全部 LabOps Guard 核心测试使用标准库 `unittest`，不要求 pytest。

## 保留原则

保留现有确定性核心、测试、安全策略、Skill、AgentTeams 证据和仪表盘。新 Demo 在独立
`demos/checkpoint-regression` 目录开发，不覆盖现有 `demo/` Polar 纵向切片。

## 下一阶段最小修改清单

1. 实现 CPU、离线、确定性的 checkpoint regression 合成 Demo。
2. 连续运行三次，确保 best accuracy ≥ 0.88，错误 last checkpoint 稳定回退。
3. 为新事故补齐 Schema、Evidence、RCA 和最小 Experiment Plan。
4. 在 sandbox 中只修改 checkpoint 路径并重新评测。
5. Verifier 同时验证合法修复和修改 metric 的非法修复。
6. 最后将第六个角色 Experiment Planner 接入 AgentTeams。

