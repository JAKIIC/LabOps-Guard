# LabOps Guard current state

更新时间：2026-08-09
权威仓库：本文档所在 Git 仓库
当前阶段：Phase 6 初赛材料冻结；正式 Release/Tag 保持冻结

## 已验证主线

- `LABOPS-AT-004-EVAL-DRIFT` 已完成三次本地离线预演和一次六角色真实 AgentTeams
  运行，最终 `PASS / RESOLVED`，是唯一主演示。
- 基线 `71.875% × 3`，候选 `97.8124976% × 3`，两侧 spread 均为 0；只修改新建
  沙箱中的 `evaluation.preprocessing_profile`。
- Runner 为 `labops/pytorch-cpu-runner:0.2.0`，Python 3.11.15、PyTorch 2.5.1+cpu、
  CPU、`network=none`；宿主策略检查 `8/8 PASS`，容器内能力检查 `10/10 PASS`。
- 人工批准早于执行；六组受保护哈希 before==after；原始工作区未修改。
- Verification Auditor 从 raw stdout、manifest、审批时序、变更路径和哈希独立重算，
  最终审计为 `CHAIN_OK / ACCEPTED`。

## 六角色和证据

实际顺序为 Incident Commander → Evidence Collector → RCA Analyst → Experiment Planner →
Safe Executor → Verification Auditor。人工审批单独记录，不计作 Agent。权威总链 7 entries，
首次 canonical hash `ISSUE` 与缺 Manager 的 6-entry 中间证据均保留，最终修正链通过。

原始 AT-004 证据包保持不变：

- 路径：`demo/output-agentteams-at004/LABOPS-AT-004-EVAL-DRIFT-evidence-bundle.zip`
- 27 entries，39,328 bytes
- SHA-256：`4092b43f39df52db3847caa28ca01e4321129a1c17ec7ca5efd2029ab1fb77cd`

新增经验闭环不覆盖原包：

- `demo/output-agentteams-at004-closure/postmortem.json`
- `demo/output-agentteams-at004-closure/case_memory.json`
- `demo/output-agentteams-at004-closure/postmortem.md`
- `demo/output-agentteams-at004-closure/LABOPS-AT-004-closure-v2.zip`
- closure v2 SHA-256：`d5ea98a792f1f01080b1ae3fe212a86b45d8b9d5b22c7c9e12891a64fd314c23`

## 保留案例

- AT-003 checkpoint 修复保持 `PASS / RESOLVED`，Runner `0.1.0` 仅作为备用复现线。
- AT-002 保持 `BLOCKED`，证明 Worker 缺少依赖时不会在线安装或伪造结果。
- AT-002 非法 metric 修改保持 `POLICY_VIOLATION / ROLLED_BACK`，回滚哈希一致。

## Phase 5A 进度

- AT-004 核心实现与正式证据已形成独立本地 Git 提交。
- 六个角色 Skill 已增加版本、跨项目复用、多 Agent 交接、生命周期与结构化错误；无引用
  `execute-controlled-action` 模板已通过 Git 删除。
- Incident Commander 新增 `publish-case-memory` 能力；不新增 Agent、不修改核心状态机。
- 本地案例检索入口：`python -m labops.case_memory search`。
- `docs/observability.md` 已明确 Trace / Log / Metrics / Artifact / Approval 和未来 OTel 映射；
  当前没有声称部署 OTel 基础设施。
- README、赛事材料、PPT、开源治理和 CI 已统一；源码采用 Apache-2.0，公开远端和首次
  SSH 推送已完成。公开仓库：`https://github.com/JAKIIC/LabOps-Guard`。正式 Tag、Release
  与 Runner 镜像再分发仍保持冻结。
- 候选 Git Tag `v0.3.0-rc1` 对应 Python 包版本 `0.3.0rc1`。

## Phase 6 初赛定稿

- 500 字简介已固定为 429 个非空白字符，并使用精确指标
  `71.875% × 3 → 97.8124976% × 3`。
- 官方模板已重排为 18 页完整方案，团队页改为个人参赛者介绍；不公开电话、邮箱或无关
  简历信息。
- 新增六角色 Identity 矩阵、7 个 Skill 的集成矩阵，以及 MCP / RAG / OTel 的当前实现与
  等价边界说明。
- 两张本地 Runner 镜像已通过断网、只读枚举生成 CycloneDX 1.5 SBOM，共 171 个唯一组件。
  该清单用于复核，不代表允许分发镜像。
- Runner 许可证/NOTICE 复核结论为：源码与提交材料可发布；镜像、镜像 tar、Tag 和 GitHub
  Release 继续冻结，直至基础镜像条款、Debian 源码义务、完整 NOTICE 包和最终 digest 复核
  全部关闭。
- 视频脚本与录制检查表已定稿，支持 Dashboard、Docker 或 AgentTeams 临场不可用时的
  证据回放降级，但不得把回放称为实时执行。

## 最近验证

- Phase 5A 全量回归为 89 tests；仓库卫生契约加入后当前全量为 90 tests。
- 提交 `cff32ba0d16860fa42806d5353cca54337fd7a0a` 的 GitHub Actions 已通过：Windows/Linux
  × Python 3.9/3.12 四组均为 success，包含单元/契约、证据完整性和敏感模式扫描。
- AT-002、AT-003、AT-004 三条正式证据均重新校验为 PASS。
- AT-004 closure v2 与案例记忆检索通过；PPT 无溢出且母版一致性检查通过。
- 公开仓库卫生审计已归档两份早期文档、移除四个无引用旧提交二进制，并补充 `demo/`
  与 `demos/` 的用途说明。
- 许可不明的 Polar 13 文件快照已从当前 `main` 删除。AT-001 输出和 Git 历史保留原事件与
  哈希；活动兼容测试和仪表盘回退已迁移到项目自建的 Apache-2.0 synthetic fixture。

## 不变约束

不增加 Agent，不降低审批、哈希、回滚、隔离或禁网要求，不覆盖三条正式证据，不把角色
提示词或仪表盘回放当作真实执行证据。任何真实后置指标不足的案例必须保持
`INCONCLUSIVE` 或 `BLOCKED`。
