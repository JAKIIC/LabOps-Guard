# LabOps Guard

LabOps Guard 是面向生产级 Agent 系统的可信基础设施（Trust Infrastructure for Production
Agent Systems）。它通过 Trust Contract v1 与
Trust State Machine v1，把六个职责隔离角色的身份、策略、执行、证据和审计统一成可复核链路：

**无证据不诊断，无审批不执行，无验证不闭环。**

- 🌐 **Public Evidence Demo**：<https://jakiic.github.io/LabOps-Guard/>
- 💻 **Source**：<https://github.com/JAKIIC/LabOps-Guard>
- 📋 **Official requirement mapping**：[`docs/competition-mapping.md`](docs/competition-mapping.md)
- 🔧 **Toolchain and compatibility disclosure**：[`docs/toolchain-compatibility-matrix.md`](docs/toolchain-compatibility-matrix.md)
- 📦 **Reviewer Reproducibility Pack**：[`docs/reviewer-reproducibility-pack.md`](docs/reviewer-reproducibility-pack.md)

一个模型昨天的评测准确率是 97.8%，今天降到 71.9%。值班工程师需要判断问题来自模型、
数据、评测代码还是配置。LabOps Guard 让六个权限隔离的 Agent 收集证据、提出可证伪假设、
申请最小修改，并在断网沙箱中执行获批方案。独立 Auditor 检查原始运行产物和保护文件哈希，
通过后才允许关闭事故。

真实实验室通常需要值班人员发现异常、工程师跨系统找证据、研究员讨论根因、负责人审批、
工程师修改重跑、独立人员复核，再把分散记录归档。返工成本来自人工接触、消息往返、重复运行、
等待审批、证据整理和错误关闭后的再次调查。LabOps Guard 不替代这些责任，而是把它们转成
可核验的结构化交接与证据链；完整 Before/After、责任矩阵和受控收益口径见
[`docs/lab-workflow-value.md`](docs/lab-workflow-value.md)。

```text
Identity → Policy → Execution → Evidence → Audit
   Trust Contract v1 · Trust State Machine v1 · read-only Trust Dashboard
```

Dashboard 不生成综合评分，也不提供执行、修改或审批操作；每个信任域分别展示状态、检查项、
证据来源和已知限制。Skill Registry 仍保持七个现有 Skill，不新增 Agent 或 Skill。

## Trust Evaluation Suite v1.0

复赛候选版提供 10 个固定治理案例，输入与 Oracle 分目录保存。执行阶段只读取
`evaluation/cases/inputs/`，评分阶段再读取 `evaluation/cases/oracles/`。评测聚焦四项：

- Policy Violation Prevention Rate：`100%`（2/2）；
- Evidence Completeness Rate：`100%`（10/10）；
- False Resolution Rate：`0%`（0/8）；
- Independent Audit Accuracy：`100%`（10/10）。

该结果只证明当前策略、证据与审计规则在这 10 个确定性案例中的行为，不衡量开放式诊断、
模型质量或生产规模。完整方法与逐案例结果见 `docs/trust-evaluation-report-v1.0.md`。

## 已验证的主演示

`LABOPS-AT-004-EVAL-DRIFT` 是当前主线。固定模型评测从历史约 `97.81%` 稳定回退到
`71.88% × 3`。系统采集 10 条带哈希事实，排除 checkpoint、验证数据、metric 和随机
波动后，将预处理配置漂移列为最高置信度假设。人工批准后，Safe Executor 仅在新建的
断网 CPU 沙箱中把 `evaluation.preprocessing_profile` 从 `train_augmented` 恢复为
`eval_standard`。三次复算达到 `97.81% × 3`，六组保护文件哈希不变；Verification
Auditor 不采信 Executor 的成功声明，而是根据 Runner 原始输出、metrics、artifact
manifest、保护文件哈希、审批时序和 Trace 重算验收结论，最终给出 `PASS / RESOLVED`。

- 六个 Agent 真实参与，角色顺序和交接均有 Matrix 事件与 artifact 记录；
- 执行镜像为 `labops/pytorch-cpu-runner:0.2.0`，实验期 `network=none`；
- 权威 Trace 为 7 entries，最终审计 `CHAIN_OK / ACCEPTED`；
- 原始证据 ZIP 共 27 entries，SHA-256 为
  `4092b43f39df52db3847caa28ca01e4321129a1c17ec7ca5efd2029ab1fb77cd`；
- AT-002 依赖缺失安全阻塞、AT-003 checkpoint 修复和非法 metric 篡改案例均独立保留。

## 六角色闭环

| 角色 | 主要 Skill | 权限边界 |
|---|---|---|
| Incident Commander | `pack-lab-evidence`, `publish-case-memory` | 只编排、验收交接、封包并发布 Case Memory，不执行、不自证、不覆盖 Auditor 裁决 |
| Evidence Collector | `collect-lab-evidence` | 只读取白名单证据，不诊断、不修改实验 |
| RCA Analyst | `diagnose-lab-incident` | 只基于 `evidence_id` 生成可证伪假设 |
| Experiment Planner | `plan-lab-experiment` | 只生成单变量、有限预算、可回滚计划 |
| Safe Executor | `control-lab-action` | 只消费已批准计划并调用受限 Runner，不宣布成功 |
| Verification Auditor | `verify-lab-result` | 从原始产物独立重算，独占闭环与回滚裁决权 |

```text
Incident → Evidence → Hypothesis → Plan → Human Approval → Sandbox Run → Verification
               Matrix handoffs + MinIO artifacts + Runner evidence + hash-chained trace
```

AgentTeams 负责角色编排和上下文交接；LabOps Guard 的 Schema、Policy、Gateway、Runner
与 Auditor 负责确定性验证和安全门。自然语言回复不是执行证据。

七个版本化 Skill 的 I/O、失败处理、安全边界、复用方式及 runtime evidence 事实边界见
[`docs/skill-framework.md`](docs/skill-framework.md)。

## 安全不变量

- Planner 每个计划只允许一个被证据支持的变量变化，并定义预算、成功条件与回滚；
- 人工批准时间必须早于 Runner 启动；禁止动作不能因人工批准而降级放行；
- ApprovalGrant v1 强绑定 incident、计划哈希、run、批准范围、副作用、保护资源、预算、时效与
  nonce；哈希、范围、预算、时效或重放不一致时 Gateway fail closed；
- Agent Worker 不安装 PyTorch、不持有 Docker socket；Runner 非 root、只读根文件系统、
  限制 CPU/内存/PID 且实验期断网；
- metric、数据、checkpoint、评测协议和原始工作区受保护；
- Executor 的结论不能作为验证证据；Verification Auditor 独占 `RESOLVED / ROLLED_BACK / BLOCKED` 终态裁决权；
- Incident Commander 只能在 Auditor 裁决后发布状态、封包证据并沉淀 Case Memory，不得改变终态；
- 证据不足、运行依赖缺失或链路异常都必须显式 `BLOCKED`。

异常恢复与正常审批严格分离：Recovery 使用 append-only attempt/ownership overlay；自动重试有
预算，Reassign 必须有真实备用 Worker 与 Matrix/capability 证据，否则转入真人 Human Takeover。
接管者不能直接写终态，恢复后的新 attempt 最终仍由 Verification Auditor 裁决。

## 快速验证

要求 Python 3.9+；完整 Runner 复现另需 Docker Desktop 和已构建或离线加载的固定镜像。
源码目录可直接运行下列命令；如需安装 CLI，使用标准 PEP 517 命令
`python -m pip install --no-deps .`。完全离线安装时需预先提供 `setuptools>=68`，项目不在
source-only 提交包中复制构建工具。
Skill Registry、Trust Contract、Demo readiness 和 Evidence verifier 属于仓库原生能力，
必须从解压后的源码根目录运行，使其能读取随代码包提供的 `skills/`、`schemas/`、
`agentteams/` 与 `demo/` 资产；不宣称脱离这些资产的孤立 wheel 可独立复现完整比赛链路。

```powershell
python -B -m unittest discover -s tests -p "test_*.py" -v
python -B scripts/verify_evidence.py
python -B -m labops.case_memory search "evaluation drift"
python -B scripts/run_semifinal_eval.py
```

启动只读仪表盘：

```powershell
docker compose up -d --build
```

Trust Dashboard 只投影已归档证据，服务端会重新验证 Identity、Policy/Approval、Runner、
ZIP member set、artifact manifest 和 Trace。页面不提供执行、修改或审批入口；所有写方法
统一返回 `405`。公网 Public Evidence Replay 仍是无脚本、无网络请求的构建时静态页面。

### Reviewer Edition：第三方本地验证

Reviewer Edition 提供只读动态工作台和明确的 Quick/Live 两级入口。Quick Mode 读取已验证的
归档 Evidence，适合评委首次本地验证；Live Mode 只在真实 HiClaw/AgentTeams、Matrix、六角色、
Docker Runner 与本地凭证全部可用时启动，不会用脚本模拟 Agent 消息。

```powershell
# 先验证固定版本、源码、Evidence 与运行前置条件
python -B -m labops reviewer pack-check --mode quick

# Windows：Quick Replay
powershell -ExecutionPolicy Bypass -File scripts/start_reviewer_demo.ps1 -Mode quick

# 仅检查 Live 前置条件
python -B -m labops reviewer pack-check --mode live
```

启动后打开 `http://127.0.0.1:18787/reviewer`。可选
`compose.reviewer.yaml` 仅包装 Quick Replay；完整 Live Mode 必须使用宿主环境。安装、真实 room
map、人工操作、状态标签和降级步骤见
[`docs/reviewer-edition.md`](docs/reviewer-edition.md)；固定版本、校验安装辅助、样例 I/O 和干净环境
故障诊断见 [`docs/reviewer-reproducibility-pack.md`](docs/reviewer-reproducibility-pack.md)。

## 证据与复现入口

第三方快速验证从 `docs/reviewer-edition.md` 开始；复赛录制与完整人工操作从
`docs/final-demo-guide.md` 开始。两份 Runbook 均明确区分真实
AgentTeams live execution、本地确定性控制面和 Archived Evidence Replay，并提供只读
`python -B -m labops demo-readiness` 预检入口。最终四分钟视频按
`docs/final-demo-recording-runbook.md` 执行；它根据实机彩排明确采用 Strategy C，并要求画面标注
`LIVE CHECK` 或 `ARCHIVED VERIFIED RUN`。

最终收尾 commit 完成且工作树干净后，可使用
`python -B scripts/build_submission_bundle.py --output-dir release` 生成 commit-bound、自验证、
不含视频和 Runner 镜像的复赛附件。该附件显式标记 `VIDEO_PENDING`，不是最终视频成片。
最终 MP4 通过隐私复核后，使用同一命令加 `--video <MP4>` 重建校验和，不手工改写 ZIP。

| 案例 | 角色 | 结果 | 入口 |
|---|---:|---|---|
| AT-004 评测预处理漂移（主） | 6 | `PASS / RESOLVED` | `docs/LABOPS-AT-004-DEMO.md` |
| AT-003 checkpoint 修复（备） | 6 | `PASS / RESOLVED` | `docs/LABOPS-AT-003-DEMO.md` |
| AT-002 Worker 缺依赖 | 6 | `BLOCKED` | `docs/LABOPS-AT-002-DEMO.md` |
| 非法修改 metric | 安全分支 | `POLICY_VIOLATION / ROLLED_BACK` | AT-002 证据包 |

AT-004 的复盘、可搜索案例记忆和独立 closure v2 包位于
`demo/output-agentteams-at004-closure/` 与 `memory/cases/`。原证据包从不被覆盖。

## 项目结构

```text
agentteams/   六角色 Identity、状态机、任务与 Manager 提示
skills/       可复用 Skill、I/O Schema 与版本记录
labops/       CLI、Policy、Gateway、Runner 协议、Dashboard 与案例记忆
runner/       固定 PyTorch CPU Runner 镜像与入口
demos/        确定性评测漂移及 checkpoint fixture
demo/         三个 AgentTeams 案例的正式证据与 closure 包
memory/       本地轻量案例索引
evaluation/   Trust Evaluation Suite 输入、独立 Oracle 与结果
docs/         安全、可观测、部署、赛事映射和演示说明
submission/   复赛清单、讲解稿和最终 PPT/PDF
tests/        合约、策略、Runner、证据与 Web 回归测试
```

## 当前事实边界

这是单机、确定性 CPU 演示，不是生产级多租户调度器。Runner 镜像构建可能访问官方
Python/PyTorch 仓库，但实验容器运行时禁止联网。当前没有部署 OTel Collector、MCP
Server、mTLS/OIDC 服务身份、GPU 调度、外部数据集或 RAG；相关迁移边界见
`KNOWN_LIMITATIONS.md`、`docs/observability.md` 与 `docs/competition-mapping.md`。

源码采用 Apache-2.0，公开仓库为 `https://github.com/JAKIIC/LabOps-Guard`；候选材料版本
`v1.0-rc1` 对应 Python 包版本 `1.0.0rc1`。`main` 已通过
Windows/Linux、Python 3.9/3.12 的 GitHub Actions。正式 Release/Tag 仍需确认发布时间，
Runner 镜像级 SBOM、许可证和 NOTICE 复核已完成：源码与初赛材料可提交，但基础镜像
再分发条款、Debian 对应源码义务、完整镜像 NOTICE 包和最终 digest 对比尚未关闭。
因此不分发镜像/tar，也不创建 Tag/Release；详见 `docs/compliance/runner-license-review.md`。
