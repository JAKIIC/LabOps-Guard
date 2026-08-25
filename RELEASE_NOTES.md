# LabOps Guard v1.0-rc1 semifinal candidate

这是面向 GOAI 2026 Agent Infra 复赛的 source-only 候选版。项目定位升级为：
Trustworthy Agent Execution & Governance Infrastructure for AI Engineering。Python 包版本
为符合 PEP 440 的 `1.0.0rc1`，对外材料口径为 `v1.0-rc1`。

本候选版增加 Trust Contract v1、Identity/Alias 兼容层、Trust State Machine v1、七 Skill
Registry、Tool Contract、结构化 Gateway 错误码与六信任域 Trust Snapshot。原始
AT-002/003/004 Evidence Bundle 不重新生成。

Phase 7 将本地 Dashboard 与 Public Evidence Replay 升级为只读 Trust Dashboard，重点展示
Identity → Policy → Execution → Evidence → Audit 的证据链，以及 AT-004 合法修复与
metric.py 越权修改的危险分支。页面不生成综合评分，不提供执行、修改或审批入口。
Phase 7 全量回归为 110 tests，三套正式 Evidence Bundle 与 Public Replay 陈旧检查通过。

由于 Runner 镜像许可证/NOTICE 门禁仍未关闭，本文档不表示已创建 Git Tag、
GitHub Release、Runner 镜像或镜像 tar。

## 历史初赛候选版记录

### LabOps Guard v0.3.0-rc1 draft

这是面向 GOAI Agent Infra 初赛的发布候选草案；源码采用 Apache License 2.0。尚未创建
GitHub Release 或 `v0.3.0-rc1` Tag。

Git Tag 使用 `v0.3.0-rc1`，`pyproject.toml` 使用符合 PEP 440 的 `0.3.0rc1`。源码包使用
项目自建的 synthetic compatibility fixture，不包含早期 Polar 快照文件。

## 验证结果

- 90 项全量单元与契约测试通过；
- AT-002、AT-003、AT-004 三条正式证据包及其审计哈希链独立复核通过；
- 官方模板 18 页 PPT 通过无溢出与母版一致性检查；PDF 18 页逐页复核；个人介绍页不含
  联系方式或无关简历信息。

## 主演示

- AT-004 六角色 AgentTeams 真实协作：评测预处理漂移
  `71.875% × 3 → 97.8124976% × 3`；
- 单变量沙箱修复、人工审批、Runner `0.2.0` 断网执行和 Auditor 独立重算；
- 27-entry 原始证据包与 7-entry Trace 通过多层 SHA-256 校验；
- Incident Commander 发布独立 postmortem、案例记忆和 closure v2 包，原证据不变。

## 保留安全案例

- AT-002：运行依赖缺失时安全 `BLOCKED`；
- AT-003：checkpoint 修复 `PASS / RESOLVED`，Runner `0.1.0` 仅为备用；
- 非法 metric 修改：`POLICY_VIOLATION / ROLLED_BACK`。

## 工程化

- 7 个 Skill 包加入版本、跨项目复用、生命周期、多 Agent 交接和结构化错误；
- 删除无引用模板 Skill，新增 Incident Commander 的 `publish-case-memory` Skill；
- 新增五类证据可观测模型和未来 OpenTelemetry 适配边界；
- 补齐开源治理、Python 包元数据与最小 CI；
- 统一 README、状态、比赛材料和官方模板 PPT 的 AT-004 口径。

## 事实边界

本候选仍是单机 CPU 演示，不包含生产级身份、调度、GPU、外部数据集、OTel 后端、MCP
Server 或 RAG。两张本地 Runner 镜像已生成 CycloneDX 1.5 SBOM；许可证/NOTICE 复核发现
基础镜像条款、Debian 对应源码、完整镜像 NOTICE 和最终 digest 四个未关闭门禁。远端 CI
和公开内容检查已通过，但正式 Tag、Release 与镜像分发继续冻结。
