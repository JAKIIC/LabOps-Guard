# v0.2.0 Release Freeze

冻结日期：2026-08-04
冻结目标：初赛提交前保持核心闭环稳定，只优化可复现性、文档与展示。

## 冻结范围

- 六角色 Agent Identity 与职责边界；
- AgentTeams v2 状态机；
- Incident、Evidence、Hypothesis、Plan、Approval、Run、Verification Schema；
- Planner 单变量、有限预算、禁止修改评测与原始工作区策略；
- Safe Executor、Runner Gateway、`labops/pytorch-cpu-runner:0.1.0`；
- Verification Auditor、Trace/hash chain 与证据包格式；
- LABOPS-AT-002、LABOPS-AT-003 正式证据；
- 仪表盘服务端数据模型。

## 冻结后允许修改

- P0/P1 缺陷；
- 启动、验证、离线复现与故障排查脚本；
- 文档、PPT、视频与仪表盘展示文字；
- 敏感信息清理、许可证与提交材料。

## 冻结后禁止修改

- 新增 Agent、状态或执行框架；
- 降低审批、哈希、回滚、无网络或工作区隔离要求；
- 覆盖 AT-002/AT-003 证据；
- 为展示效果伪造角色执行、指标、Trace 或 `RESOLVED`；
- 在主分支增加 RAG、向量数据库、自动调参或新前端栈。

正式 `v0.2.0-rc1` 标签只能在工作区干净、全量测试通过、离线 Release 校验通过后创建。
