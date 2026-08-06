# LabOps Guard execution plan

当前计划以 AT-004 已真实 `PASS / RESOLVED` 为起点，不再增加 Demo 功能。

## Phase 5A — release readiness

- [x] 将 AT-004 核心实现、真实 AgentTeams 证据和测试形成独立本地提交。
- [x] 清理无引用 Skill 模板，补齐六个角色 Skill 的版本、复用、交接、生命周期和错误。
- [x] 为 Incident Commander 增加案例记忆发布 Skill；生成 AT-004 postmortem、case memory
  和独立 closure v2 包，不覆盖原始证据。
- [x] 文档化五类可观测信号与未来 OpenTelemetry 映射，不虚构已部署组件。
- [ ] 统一 README、状态、限制、Release、赛事简介、演示稿、PPT 与 Agent Identity。
- [ ] 补齐许可证占位、贡献、安全、第三方声明、行为准则、包元数据和 CI。
- [ ] 运行全量测试、证据/敏感信息/路径/PPT/Release manifest 审计并形成最终报告。

## Phase 5B — user-confirmed publication

仅在用户确认后执行：

- 确认 Apache-2.0 并替换 LICENSE 占位；
- 配置公开远端，复核公开权限与敏感信息；
- 选择 Release/Tag 版本并生成离线包；
- 推送当前分支或经审阅合并后的主分支；
- 创建 Release/Tag，最后提交比赛材料。

不在 Phase 5A 执行远端推送、公开发布、正式 Tag、历史重写或备份删除。
