# LabOps Guard Current State

更新时间：2026-08-03  
核验目录：`E:\AICompetition\LabOpsWorkspace\labops-guard`  
新路线：兜底 checkpoint regression Demo 优先，Polar 作为扩展案例

## 结论

项目不是空仓库。现有 Polar 证据缺口纵向切片已完整保留，新的 checkpoint regression
主 Demo 也已经跑通本地确定性闭环：合法 checkpoint 修复得到 `PASS / RESOLVED`，
篡改 `metric.py` 得到 `POLICY_VIOLATION / ROLLED_BACK`。当前主要缺口是把六角色
AgentTeams 编排接到这条新闭环，并完成参赛材料。

## 已实现

- 确定性核心：snapshot registry、evidence、diagnosis、approval、controlled action、verification、trace hash chain。
- 5 个可复用 Skill：证据采集、诊断、受控执行、验证、证据打包。
- AgentTeams 纵向切片：5 个不同职责 Agent、5 次 handoff、Matrix 通知、MinIO 产物。
- 安全门禁：默认 dry-run、危险动作模拟、禁止动作拒绝、路径边界、超时、审批拒绝和超时。
- 事实边界：模拟执行只能得到 `DEMO_PASSED_NOT_RESOLVED`，不得伪造 `CLOSED`。
- 展示：Docker 本地只读仪表盘，展示真实 AgentTeams 证据。
- checkpoint regression：错误 last accuracy `0.7000`，best accuracy `0.98125`，连续 3 次稳定。
- 正向案例 `DEMO-RCA-001`：沙箱内仅修正 checkpoint 选择，独立复算后 `PASS / RESOLVED`。
- 对抗案例 `DEMO-RCA-002`：篡改 `metric.py` 被哈希策略识别，自动回滚后 `POLICY_VIOLATION / ROLLED_BACK`。
- 8 个正式 JSON Schema、角色受限状态机、Experiment Planner、sandbox 快照/patch/rollback。
- 统一入口：`python -m labops run-incident --incident <path>`。
- 展示：Docker 仪表盘同屏显示旧 AgentTeams 记录与 checkpoint 双案例。
- 测试：`polar` 54 项通过（2 项因无 PyTorch 跳过）；`d2l` 54 项全部通过。

## 部分实现

- AgentTeams 当前是 Manager + 4 个专业 Worker，缺少独立 Experiment Planner。
- checkpoint 双案例目前由本地确定性编排器执行，尚未生成新一轮 AgentTeams/Matrix/MinIO 真实协作证据。
- Postmortem 和案例记忆仍需产品化输出。

## 未实现

- 新 checkpoint 案例的 1 Manager + 5 Worker AgentTeams 实跑。
- Postmortem、案例记忆与复用检索。
- 初赛 PPT、500 字简介、2—4 分钟视频和 Git tag。

## Git 状态

- 正式 E 盘项目已初始化独立 Git 仓库。
- 当前分支：`codex/checkpoint-demo`。
- checkpoint Demo 基线提交：`0b86398 feat: establish checkpoint regression LabOps Guard baseline`。
- `artifacts/` 为本地生成证据，不纳入 Git；仪表盘通过只读挂载读取摘要。

## 环境核验

- `polar`：Python 3.11.15，NumPy 可用，PyTorch/pytest 不可用。
- `d2l`：Python 3.9.25，CPU PyTorch 1.12.0 可用，无需下载依赖。
- 当前全部 LabOps Guard 核心测试使用标准库 `unittest`，不要求 pytest。

## 保留原则

保留现有确定性核心、测试、安全策略、Skill、AgentTeams 证据和仪表盘。新 Demo 在独立
`demos/checkpoint-regression` 目录开发，不覆盖现有 `demo/` Polar 纵向切片。

## 下一阶段最小修改清单

1. 将第六个角色 Experiment Planner 接入 AgentTeams 身份、任务和状态机。
2. 让 AgentTeams 对 checkpoint 双案例真实 handoff，并输出 Matrix/MinIO 证据。
3. 增加结构化 Postmortem 与案例记忆。
4. 固化一键 Demo、讲解脚本与失败兜底方案。
5. 产出初赛 PPT、500 字简介和 2—4 分钟演示视频脚本。
