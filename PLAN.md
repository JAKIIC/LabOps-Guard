# LabOps Guard execution plan

## Phase 6B — Trust Contract Convergence

- [x] 冻结 `v1.0-rc1` / `1.0.0rc1` 版本口径；保留原 Phase 6 初赛冻结记录。
- [x] 建立 Trust Contract v1、六 Agent 唯一身份、历史 Worker Alias 和 v3 状态机。
- [x] 建立七 Skill 运行时 Registry、可查询 CLI 与 fail-closed 校验。
- [x] 统一 Tool Contract、结构化错误码与六信任域 Trust Snapshot。

`v1.0-rc1` 是复赛源码与材料候选版。Runner 镜像四个许可证门禁关闭前，
不创建 Tag/Release，不发布镜像或镜像 tar。

## Phase 7–8 — 等待项目所有者确认

- [ ] 将 Dashboard 与 Public Evidence Replay 升级为只读 Trust Dashboard。
- [ ] 完成合法修复 / 非法 metric 修改双分支故事。
- [ ] 完成 10 案例 Trust Benchmark v1 与真实评测报告。
- [ ] 统一 README、18 页复赛 PPT/PDF、视频脚本和提交清单。
- [ ] 完成全量回归、证据、静态页、隐私、许可证与提交包冻结检查。

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
- [x] 推送 `main` 并等待 GitHub Actions；
- [x] 复核 GitHub README、License 识别和公开内容；
- 选择 Release/Tag 版本并生成离线包；
- 创建 Release/Tag，最后提交比赛材料。

首次推送不创建 Tag/Release，不重写远端历史，也不把镜像 tar、视频或离线包放进普通 Git
历史。

## Phase 5C — public repository hygiene

- [x] 归档 P0 self-check 与 v0.2 Codex 内部背景文档；
- [x] 移除无引用的旧 PPT/预览二进制，保留当前 v0.3 草案；
- [x] 为 `demo/` 和 `demos/` 增加证据归档与可复现场景边界说明；
- [x] 收紧 README 首屏场景和 Verification Auditor 的事实表述；
- [x] 完成公开仓库卫生与 Polar fixture 来源审计；
- [x] 删除当前 `main` 中许可不明的 Polar fixture 字节，以自有 Apache-2.0 synthetic fixture
  迁移兼容测试和仪表盘回退；历史证据与哈希保持不变；
- [x] 完成最终 PPT/PDF、个人参赛者介绍、视频脚本和 Runner 镜像级 SBOM/NOTICE 复核；
  复核发现四个镜像再分发门禁，故不创建 Tag/Release。

## Phase 6 — preliminary submission freeze

- [x] 固化 429 个非空白字符的作品简介与 AT-004 精确指标；
- [x] 完成 18 页官方模板 PPT、PDF 及逐页渲染检查；
- [x] 补齐 Agent Identity、Skill、MCP/RAG 等价边界和个人介绍文档；
- [x] 生成两张 Runner 镜像的离线 CycloneDX 1.5 SBOM；
- [x] 完成许可证/NOTICE 决策记录与 4 分钟演示脚本；
- [ ] 录制并人工剪辑演示视频；
- [ ] 关闭基础镜像条款、Debian 源码、镜像 NOTICE、最终 digest 四个门禁后，再决定
  是否发布 `v0.3.0-rc1`。
