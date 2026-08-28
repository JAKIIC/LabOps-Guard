# LabOps Guard current state

更新时间：2026-08-28
权威仓库：本文档所在 Git 仓库
当前阶段：Phase 9 Official Alignment Closure；工程候选已按官方 06/08/09/10/12 收口，等待
公开 `main`、远端 CI/Pages、视频与比赛平台上传的项目所有者门禁；正式 Release/Tag 保持冻结

## Semifinal Trust Contract

LabOps Guard 当前对外定位为“面向生产级 Agent 系统的可信基础设施（Trust Infrastructure for
Production Agent Systems）”。当前工程是单机参考实现，不宣称已经完成生产级多租户部署。
Python 包版本为 `1.0.0rc1`，材料版本为 `v1.0-rc1`。当前候选版已建立：

- Trust Contract v1，引用六 Agent 身份、Worker 历史别名、Trust State Machine v1、Skill Registry
  与 Tool Contract；
- 七 Skill 可查询、可校验 Registry，未授权 Agent 与 Registry 损坏均 fail closed；
- Gateway 旧 `/v1/run` 请求保持可用，同时归一化为含审批、副作用、预算和审计
  上下文的 Tool Contract；
- Trust Snapshot 以 `VERIFIED / CONFIGURED / LIMITED / BLOCKED` 表达 Identity、Skills、
  Policy/Approval、Execution、Evidence/Trace 和 Audit 六个信任域。

原 Phase 6 初赛证据、版本和发布冻结记录作为历史基线继续保留。

## Official semifinal alignment

- 复赛材料、AgentTeams 完整链路、样例 I/O、Trace/Log/Metrics、评测与 verifier 对齐官方 06；
- 六 Agent Identity、上下文交接、审批、恢复、工具调用和独立审计对齐官方 08；
- 七 Skill 生命周期、MCP 等价 Tool Contract、Shared State + Trace 非 RAG 路径和本地可观测
  边界对齐官方 09；
- 工具链版本、外部依赖、官方工具取舍、权限和迁移成本集中记录在
  `docs/toolchain-compatibility-matrix.md`；不以工具数量换取展示效果；
- 五个评分域均有明确源码、测试、Evidence 或材料入口。视频、公开 `main` 与平台上传仍是
  项目所有者门禁，不属于已完成事实。

## Phase 7 Trust Dashboard

- `/api/status` 增加只读 `trust_layer`，按 Identity → Policy → Execution → Evidence → Audit
  输出状态、检查项、证据引用和限制；不生成综合评分。
- 本地 Dashboard 已升级为 Trust Dashboard；POST、PUT、PATCH、DELETE 均返回 `405`。
- Public Evidence Replay 继续构建时静态生成、无脚本、无网络请求，并新增合法 AT-004 与
  危险 metric 修改双分支证据。
- 对外只使用 Trust Contract v1 与 Trust State Machine v1，不显示内部兼容文件版本。
- Agent 和 Skill 数量保持六个与七个，不增加运行时角色或能力包。

## Phase 8 Trust Evaluation Suite

- 10 个治理案例覆盖两项合法修复、证据缺失、保护哈希不一致、两项保护资源越权、审批缺失、
  审批晚于执行、多变量计划与 Executor 自证。
- 执行阶段只读取 `evaluation/cases/inputs/`；评分阶段独立读取
  `evaluation/cases/oracles/`，输入中不包含期望终态。
- Policy Violation Prevention Rate `100%`、Evidence Completeness Rate `100%`、False
  Resolution Rate `0%`、Independent Audit Accuracy `100%`。
- 该 Suite 只评估固定治理规则，不宣称覆盖全部 MLOps 场景或通用 Agent 推理能力。
- 复赛 README、PPT/PDF、视频脚本与提交清单统一使用 v1.0-rc1 口径；没有改动
  AgentTeams 核心执行链或三套正式 Evidence。

## Phase 9 Judge Feedback Patch

- ApprovalGrant v1 强绑定 incident、plan hash、run、范围、副作用、保护资源、预算、时效和 nonce；
  不一致、过期或重放均在 Gateway 前 fail closed，Agent 不能自行批准。
- 非正式 live demo session 为 task / incident / attempt / run 提供隔离命名空间；Helper 只做预检、
  任务文本生成与结果验证，不发送 Matrix 消息、不批准、不执行或模拟 Worker。
- Recovery / Human Takeover 使用 append-only attempt/ownership overlay；重试有预算，Reassign
  必须有真实备用 Worker 与 Matrix/capability 证据，接管后仍由 Auditor 最终裁决。
- 新 live run 只有 `safe-executor → control-lab-action → labops.runner.execute` 可由 Gateway
  Tool Contract 独立证明 runtime binding；其余六 Skill 保持
  `CONFIGURED / AGENTTEAMS_HOOK_REQUIRED`，历史 Trace 不回填事件。
- 真实实验室 Before/After、责任、返工来源和受控收益已同步到 README、18 页 PPT/PDF、FAQ 与
  演示脚本；不把受控结果宣传为生产 ROI。
- Final Submission Freeze 使用 source-only 清单和 Git 归档约束提交包；公开 `main` 未包含最终
  候选提交时明确保持未完成状态，不用 Pages Replay 代替源码同步。

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

## Phase 5A 历史进度（已由 v1.0-rc1 取代）

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
- 当时的候选 Git Tag 为 `v0.3.0-rc1`，对应 Python 包版本 `0.3.0rc1`；该口径已被当前
  `v1.0-rc1` / `1.0.0rc1` 取代。

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

- 最终收尾门禁为 167 项原有测试 + 2 项提交附件测试；Approval、Session、
  Recovery/Takeover、Skill binding 与 commit-bound source-only 打包回归均通过。
- 最新 18 页 PPT 通过无溢出与模板保真检查；PDF 18 页由 PowerPoint 导出并逐页渲染复核。
- Trust Evaluation Suite 10/10、Public Replay stale check、敏感信息扫描与三套正式 Evidence
  均通过；AT-002/003/004 SHA 保持冻结值。
- Phase 9 Task 1 全量回归为 119 tests，其中 117 通过、2 个可选 PyTorch 测试跳过；失败为 0。
- Phase 8 全量回归为 117 tests，其中 115 通过、2 个可选 PyTorch 测试跳过；失败为 0。
- 三套正式 Evidence、Public Replay stale check、18 页 PPT/PDF 渲染与提交文件校验通过；
  正式发布动作仍等待项目所有者确认。
- Phase 7 全量回归为 110 tests，其中 108 通过、2 个可选 PyTorch 测试跳过；失败为 0。
- Trust Dashboard 的 GET/API/健康检查通过；POST、PUT、PATCH、DELETE 均返回 `405`。
- Public Trust Evidence Replay stale check、无脚本/无网络/无表单检查和 390px–1280px
  响应式渲染检查通过。
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
