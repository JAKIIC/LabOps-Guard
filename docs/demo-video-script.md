# LabOps Guard 初赛演示视频脚本

建议时长：3 分 30 秒。画面以只读 Dashboard、AgentTeams 交接证据和官方模板 PPT 为主；
不把提示词、口头结论或界面回放当作执行证据。

## 0:00–0:25｜问题与原则

画面：PPT 封面、AT-004 概览。

旁白：AI 实验指标回退时，给出建议并不等于完成可信修复。LabOps Guard 通过六角色职责
隔离，把一次异常变成可审批、可阻塞、可回滚、可复核的工程事件。原则是：无证据不诊断，
无审批不执行，无验证不闭环。

## 0:25–0:55｜真实异常

画面：Dashboard 的 AT-004 基线卡片、Evidence Collector 事实清单。

旁白：固定 checkpoint、验证数据、metric 与评测协议后，accuracy 连续三次为 71.875%，
历史基线约为 97.8124976%，两侧重复实验 spread 都是 0。Collector 只采集白名单事实和哈希，
不提前诊断。

## 0:55–1:25｜六角色交接与 RCA

画面：六角色时序与 handoff manifest。

旁白：Commander、Collector、Analyst、Planner、Executor、Auditor 依次交接，每次记录任务
ID、输入、输出、时间、状态和 Matrix 事件。Analyst 排除 checkpoint、数据、metric 和随机性，
把 evaluation preprocessing profile 漂移列为首要假设。

## 1:25–2:05｜审批与受限执行

画面：ExperimentPlan、人工审批记录、RuntimeCapabilityCheck 8/8、Runner 结果。

旁白：Planner 只允许在沙箱中把一个配置字段从 train_augmented 恢复为 eval_standard，预算
为 CPU、30 秒、三次复算、禁止联网。Safe Executor 只有在人工批准后才能调用 Runner 0.2.0；
Runner 非 root、network=none，不修改原始工作区。

## 2:05–2:40｜独立验证

画面：71.875% × 3 → 97.8124976% × 3、六组保护哈希、Trace 检查。

旁白：候选三次复算恢复到 97.8124976%，只有一个沙箱字段改变。Auditor 不接受 Executor
的成功声明，而是从原始日志、metrics 和 manifest 独立重算；第一次 Trace 审计失败被保留，
补齐真实事件后才得到 CHAIN_OK / ACCEPTED 与 PASS / RESOLVED。

## 2:40–3:10｜安全失败与经验沉淀

画面：AT-002 BLOCKED、非法 metric 修改 ROLLED_BACK、case memory 搜索结果。

旁白：依赖缺失不是失败旁白，而是正式 BLOCKED 结果；非法 metric 修改被拒绝并回滚。
Auditor 裁决后，Incident Commander 发布独立 postmortem 和可搜索 case memory，不覆盖原始
AT-004 证据包，也不增加第七个 Agent。

## 3:10–3:30｜收尾

画面：五类证据、开源边界、最终状态。

旁白：LabOps Guard 开放的是六角色、版本化 Skill、受限 Runner 和证据合同。当前是单机
CPU 演示；生产身份、外部调度和 OTel 后端属于后续路线，不冒充已完成能力。

## 录制前检查

- AT-004 是唯一主演示；AT-003 仅作快速兜底，AT-002 保持 BLOCKED；
- Dashboard、PPT、README 与证据包显示相同的指标、Runner 版本和最终状态；
- 画面不出现 Token、凭据、本机绝对路径或个人隐私；
- 任一哈希校验失败时停止录制闭环，不宣称 RESOLVED。
