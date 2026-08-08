# LabOps Guard v0.3.0-rc1 draft

这是面向 GOAI Agent Infra 初赛的发布候选草案；源码采用 Apache License 2.0。尚未创建
GitHub Release 或 `v0.3.0-rc1` Tag。

## 验证结果

- 90 项全量单元与契约测试通过；
- AT-002、AT-003、AT-004 三条正式证据包及其审计哈希链独立复核通过；
- 官方模板 18 页 PPT 通过无溢出与母版一致性检查，团队介绍页保持空白。

## 主演示

- AT-004 六角色 AgentTeams 真实协作：评测预处理漂移 `71.88% × 3 → 97.81% × 3`；
- 单变量沙箱修复、人工审批、Runner `0.2.0` 断网执行和 Auditor 独立重算；
- 27-entry 原始证据包与 7-entry Trace 通过多层 SHA-256 校验；
- Incident Commander 发布独立 postmortem、案例记忆和 closure v2 包，原证据不变。

## 保留安全案例

- AT-002：运行依赖缺失时安全 `BLOCKED`；
- AT-003：checkpoint 修复 `PASS / RESOLVED`，Runner `0.1.0` 仅为备用；
- 非法 metric 修改：`POLICY_VIOLATION / ROLLED_BACK`。

## 工程化

- 六个角色 Skill 加入版本、跨项目复用、生命周期、多 Agent 交接和结构化错误；
- 删除无引用模板 Skill，新增 Incident Commander 的 `publish-case-memory` Skill；
- 新增五类证据可观测模型和未来 OpenTelemetry 适配边界；
- 补齐开源治理、Python 包元数据与最小 CI；
- 统一 README、状态、比赛材料和官方模板 PPT 的 AT-004 口径。

## 事实边界

本候选仍是单机 CPU 演示，不包含生产级身份、调度、GPU、外部数据集、OTel 后端、MCP
Server 或 RAG。源码许可证与公开仓库已确认；Runner 镜像再分发仍需镜像级 SBOM/NOTICE
复核。远端 CI 和公开内容检查已通过，正式 Tag 与 Release 仍等待发布时间确认。
