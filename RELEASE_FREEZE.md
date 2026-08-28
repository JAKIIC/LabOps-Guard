# Phase 5 release freeze (historical baseline)

> Current addendum (2026-08-28): the active candidate is `v1.0-rc1` / `1.0.0rc1`. The frozen
> AgentTeams/Evidence boundaries below remain valid. Approval strong binding, non-formal live
> sessions, Recovery/Human Takeover and Gateway Skill binding were added without modifying the
> formal AT-002/003/004 Evidence. The candidate remains source-only; no Tag, Release or Runner image
> is published while the four image redistribution gates remain open.

冻结日期：2026-08-06
目标：保持 AT-004 真实闭环不变，只完成工程化、文档、开源治理和发布前审计。

## Frozen

- 六角色 Agent Identity 与核心状态机；
- Incident、Evidence、Hypothesis、Plan、Approval、Run、Verification 合同；
- 单变量、有限预算、人工审批、保护文件、回滚、工作区隔离与禁网策略；
- AT-004 主 Runner `0.2.0`、AT-003 备用 Runner `0.1.0` 和 Gateway 白名单；
- AT-002/003/004 原始证据、Trace、Verification 与 Dashboard 服务端校验模型。

## Allowed

- 缺陷修复、测试、离线复现、敏感信息清理；
- Skill 版本/复用说明、案例记忆、可观测性文档；
- README、PPT、视频、比赛映射和开源治理文件；
- 不覆盖原证据的独立派生 closure 包。

## Forbidden

- 新增 Agent 或核心状态；
- 降低审批、哈希、回滚、禁网或工作区隔离；
- 伪造角色执行、指标、Trace、实时状态或 `RESOLVED`；
- 覆盖正式证据、重写发布历史，或在 CI 与公开检查完成前创建正式 Tag。

候选 `v0.3.0-rc1` 只有在工作区干净、全量测试、证据、敏感信息、PPT 和 Release
manifest 均通过且 CI 与公开仓库检查完成后才能成为正式 Release。Apache-2.0、公开仓库
及首次推送已由项目所有者确认；自有 synthetic fixture 已解除旧 Polar 字节的源码再分发
风险。Tag 与 Release 仍保持冻结。
