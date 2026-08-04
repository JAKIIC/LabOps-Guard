# 初赛提交文字初稿

## 项目名称

LabOps Guard：可信多智能体实验守护系统

## 500 字以内作品简介

AI 实验发生指标回退或评测争议时，现有助手多只能建议，无法证明谁执行了什么、是否越权、结果是否可信。LabOps Guard 基于 AgentTeams 构建六角色职责隔离闭环：Commander 拆解事件，Collector 采集白名单证据，Analyst 生成证据约束假设，Planner 制定单变量、有限预算、可回滚计划，Executor 仅在人工批准后调用断网 PyTorch Runner，Auditor 独立复核指标、哈希、审批时序、执行范围与 Trace，只有验证通过才能进入 RESOLVED。系统以 Matrix、MinIO、Artifact 和 SHA-256 链沉淀证据。真实 Demo 覆盖三种结果：依赖缺失时安全 BLOCKED；合法切换 checkpoint 后准确率由 70.00% 恢复至 98.12%，得到 PASS/RESOLVED；篡改 metric.py 时触发 POLICY_VIOLATION 并回滚。六类 Skill 与 Schema 可复用于训练、评测、数据和发布流水线，让多 Agent 不只完成任务，更能可信地决定任务是否允许完成。

## 14 页 PPT 文字骨架

### 1. 封面

- LabOps Guard：可信多智能体实验守护系统
- 副标题：无证据不诊断、无审批不执行、无验证不闭环
- GOAI Agent Infra / AgentTeams

### 2. 场景：AI 实验为什么需要治理

- 指标回退时团队先怀疑模型、数据、代码还是环境；
- 临时修复经常缺乏职责、权限和后置验证；
- “结果变好”不等于“修复可信”。

### 3. 目标用户与行业价值

- 模型研发、评测平台、数据平台、MLOps/AI Infra 团队；
- 缩短事故定位时间；
- 降低越权修改、评测污染和错误闭环风险；
- 形成可迁移的实验异常响应协议。

### 4. 三条原则

- 无证据不诊断；
- 无审批不执行；
- 无验证不闭环；
- 补充：失败是正式结果，BLOCKED 不是系统失败。

### 5. 总体架构

- AgentTeams 决策面；
- Matrix + MinIO 共享上下文；
- 人工审批门；
- localhost Gateway；
- 离线 PyTorch Runner；
- Artifact / Trace / Dashboard 证据面。

### 6. 六角色职责隔离

- Commander、Collector、Analyst、Planner、Executor、Auditor；
- 采集者不能诊断，诊断者不能执行；
- 执行者不能宣布成功，Auditor 才有闭环裁决权。

### 7. 结构化协作协议

- Incident → Evidence → Hypothesis → Plan → Approval → Run → Verification；
- 每次 handoff 记录 task ID、输入、输出、时间、状态和 Matrix event；
- schema 错误或证据不足立即阻塞。

### 8. Skill 工程体系

- 六类核心 Skill；
- 每个 Skill 展示输入、输出、调用条件、工具依赖、失败处理、安全边界；
- 同一 Skill 可复用于训练、评测、数据和发布场景。

### 9. Planner：把猜测变成最小实验

- 仅修改 `eval_config.json:checkpoint`；
- CPU、30 秒、3 次复算、无网络；
- 禁改 metric、数据、目标和原始工作区；
- 明确定义成功条件与回滚。

### 10. Safe Executor 与专用 Runner

- Worker 不安装 PyTorch、不持有 Docker socket；
- Gateway 只接受固定结构和已批准计划；
- Runner 非 root、只读、断网、资源受限；
- 固定产生五类原始证据。

### 11. Verification Auditor：防止虚假成功

- 复核三次指标、文件哈希、变更路径、审批时序与 manifest；
- 首次 Trace 重复 Event ID 时拒绝收口；
- 修正并重新审计后才得到 CHAIN_OK / ACCEPTED；
- 不宣称 Auditor 在 Worker 中重新运行模型。

### 12. 三案例对比（核心页）

| 输入 | 系统行为 | 最终状态 |
|---|---|---|
| Worker 缺少 torch | 不在线安装、不用模拟指标替代 | BLOCKED |
| 合法 checkpoint 修复 | 70.00% → 98.12%，保护文件未变 | PASS / RESOLVED |
| 篡改 metric.py | 策略拒绝、哈希检测、回滚恢复 | POLICY_VIOLATION / ROLLED_BACK |

### 13. 可验证证据与仪表盘

- 六角色/六次交接；
- ZIP、26 个 artifact、Runner manifest 三层哈希；
- Matrix、MinIO、Metrics、Log、Trace；
- AT-002 与 AT-003 分开展示；
- 支持实时运行与真实归档证据回放。

### 14. 开放复用与路线图

- 开放 Schema、Skill、Runner 契约、策略与示例；
- Gateway 可适配 MCP、作业调度器和企业鉴权；
- 可迁移到训练失败、评测污染、数据质量和发布验证；
- 复赛：独立 Runner 二次评测、集中可观测、更多真实场景；
- 当前事实边界与已知限制。
