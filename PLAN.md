# LabOps Guard execution plan

当前计划以 AT-004 已真实 `PASS / RESOLVED` 为起点，不再增加 Demo 功能。

## Phase 5A — release readiness

- [x] 将 AT-004 核心实现、真实 AgentTeams 证据和测试形成独立本地提交。
- [x] 清理无引用 Skill 模板，补齐六个角色 Skill 的版本、复用、交接、生命周期和错误。
- [x] 为 Incident Commander 增加案例记忆发布 Skill；生成 AT-004 postmortem、case memory
  和独立 closure v2 包，不覆盖原始证据。
- [x] 文档化五类可观测信号与未来 OpenTelemetry 映射，不虚构已部署组件。
- [x] 统一 README、状态、限制、Release、赛事简介、演示稿、PPT 与 Agent Identity。
- [x] 补齐正式 Apache-2.0、贡献、安全、第三方声明、行为准则、包元数据和 CI。
- [x] 运行全量测试、证据/敏感信息/路径/PPT/Release manifest 审计并形成最终报告。

## Phase 5B — user-confirmed publication

已由项目所有者确认并进入首次公开流程：

- [x] 确认 Apache-2.0 并替换 LICENSE 占位；
- [x] 确认公开远端、公开权限与 SSH 推送授权；
- [ ] 推送 `main` 并等待 GitHub Actions；
- [ ] 复核 GitHub README、License 识别和公开内容；
- 选择 Release/Tag 版本并生成离线包；
- 创建 Release/Tag，最后提交比赛材料。

首次推送不创建 Tag/Release，不重写远端历史，也不把镜像 tar、视频或离线包放进普通 Git
历史。
