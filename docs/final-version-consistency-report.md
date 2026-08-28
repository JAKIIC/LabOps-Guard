# Final Version Consistency Report

审查日期：2026-08-28

目标版本：LabOps-Guard v1.0-rc1

最终定位：**Trust Infrastructure for Production Agent Systems**

## 1. 冻结范围

本报告只核对比赛交付一致性，不扩展系统能力：

- 本地候选分支、公开 `main` 与 GitHub Pages；
- Phase 6–9 的 Trust Contract、Dashboard、Evaluation、Approval、Live Demo、Recovery 与 Skill binding；
- README、运行手册、18 页 PPT/PDF、提交清单和 SHA-256；
- AT-002、AT-003、AT-004 正式 Evidence 的不可变性；
- source-only 交付边界、许可证、NOTICE、SBOM 与敏感信息。

## 2. 当前一致性状态

| 交付面 | 当前状态 | 事实边界 |
|---|---|---|
| 产品定位 | READY | README、PPT/PDF、GitHub About 与 Pages 均使用最终定位 |
| Trust Contract / State Machine | FROZEN | 对外均称 Trust Contract v1 / Trust State Machine v1，历史内部版本不作为产品口径 |
| AgentTeams | READY | 六 Agent 不变；真实 live execution、确定性本地验证和 Archived Replay 明确区分 |
| Skill | READY WITH BOUNDARY | 七 Skill Registry/Schema 可校验；只有新 live Gateway 证据可证明 `control-lab-action` 的运行时绑定 |
| Approval | READY | ApprovalGrant v1 绑定计划哈希、范围、预算、时效和单次 nonce，Gateway fail closed |
| Recovery / Takeover | READY | append-only attempt overlay；Human Approval 与 Human Takeover 分离，最终仍由 Auditor 裁决 |
| Dashboard | READY | 只读展示 Identity → Policy → Execution → Evidence → Audit；无 Trust Score 或写入口 |
| Evaluation | READY | 10 个固定治理案例，输入与 Oracle 分离；不称通用 Benchmark |
| PPT / PDF | READY | 均为 18 页，版本、指标、链接与能力边界一致 |
| 正式 Evidence | FROZEN | AT-002/003/004 不修改、不重建、不回填事件 |
| Runner 发布 | SOURCE ONLY | 镜像再分发四项许可证门禁未关闭，不提交镜像或 tar，不创建 Tag/Release |

## 3. 测试与证据口径

- 当前完整测试口径为 **167 项全部通过**，覆盖既有闭环以及 Approval strong binding、live session
  隔离、Recovery/Human Takeover 和 Gateway Skill binding。
- Trust Evaluation Suite v1.0 固定为 10 个治理案例；结果只能表述为“与预设 Oracle 一致”，
  不能表述为“通用 Benchmark”或“100% 安全”。
- Public Demo 是静态 Archived Evidence Replay，不是实时 AgentTeams 控制台。
- 新 live run 产物必须写入 `demo/live-sessions/` 的独立命名空间，不进入正式 Evidence。

正式 Evidence Bundle SHA-256：

```text
AT-002  1a957940bed0ef6c01745273854a2d08946ab191198441a80b7fa102df8f9365
AT-003  630bc18ed92f4f094ffc5fcb5a6ea7337408fbee87fe549450e1df420dbd1703
AT-004  4092b43f39df52db3847caa28ca01e4321129a1c17ec7ca5efd2029ab1fb77cd
```

## 4. 公开版本核验

2026-08-28 实际网络检查：

- GitHub：`https://github.com/JAKIIC/LabOps-Guard` 返回 HTTP 200，About 已使用最终定位；
- Pages：`https://jakiic.github.io/LabOps-Guard/` 返回 HTTP 200，页面使用最终定位，保持无脚本并含
  `connect-src 'none'`；
- 公开 `main` SHA：`86c263bd50c58aa52b2fc8b9e8965007422773c4`；
- Task 5B 开始时本地候选基线：`e905301f6d3447352c0aca70d0625d31bf68d944`。

本地候选比公开 `main` 多 5 个已验证提交：Approval strong binding、Live Demo Session、
Recovery/Human Takeover、Gateway Skill binding 和比赛材料收口。因此，**在项目所有者把候选提交
合入并推送公开 `main` 之前，不能宣称 GitHub 公开源码等于最终提交候选**。推送后还必须重新运行
Pages workflow，并用公开 SHA 完成最终提交登记。

## 5. 最终人工门禁

以下动作必须在最终上传前由项目所有者完成：

1. 将 Task 5B 候选提交合入并推送公开 `main`；
2. 确认 GitHub Actions 的 Windows/Linux 测试通过；
3. 重新部署 Pages，并核对公开页面与候选版本一致；
4. 录制、逐帧检查并登记最终 MP4 SHA-256；
5. 在比赛平台上传 PPT、PDF、源码包、视频和链接后逐项回读；
6. 记录最终 `main` SHA、源码包 SHA、视频 SHA 和上传时间。

## 6. 结论

仓库内工程和比赛材料已经形成一致的 source-only 候选；剩余门禁是公开分支同步、远端 CI/Pages
复核和视频/平台上传。它们属于发布操作，不应通过新增 Agent、Skill 或基础设施组件解决。
