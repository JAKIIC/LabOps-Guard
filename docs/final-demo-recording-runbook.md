# LabOps-Guard 最终逐镜头录制 Runbook

本 Runbook 以 2026-08-26 比赛机器实测为依据。推荐 **Strategy C：Verified Replay + Live
Verification**。目标成片 3:40–4:20，不超过 5 分钟。

## 录制前固定事实与当日门禁

- 历史 AgentTeams 实机环境使用 HiClaw v1.1.2；每次正式录制仍必须当日重新核对
  Matrix/Element、MinIO、Manager、五个 Worker、Gateway 和 Dashboard，不得把上次在线
  状态当成当前事实。
- 固定 AT-004 task/run ID 已在当前运行环境中 `RESOLVED`。再次发送 Prompt 会被 Manager 的
  防重复执行检查拦截，不应删除状态或换 ID 来制造新 run。
- 2026-08-04 真实 AgentTeams 运行的七条 Trace 从 16:52:40 至 17:13:50，约 21 分 10 秒。
- 2026-08-28 只读复核时，Docker daemon 和 Runner image 可用，Element 可打开
  `Worker: controlled-executor` 历史执行房间；Gateway `18103` 和 Dashboard `8787` 未启动，
  其他 AgentTeams/MinIO 状态仍需人工核对。这是本次复核快照，不是正式录制日的在线证明。
- 不预设 OBS 或其他录制器已安装。正式录制前必须完成 30 秒画面、声音、
  字体和编码试录；未通过时门禁保持 `BLOCKED`。

## 首先选择录制路线

### 推荐：Strategy C — Verified Replay + Live Verification

适用于当前冻结的 AT-004：展示 2026-08-04 真实 Matrix/AgentTeams 历史素材，同时在
录制日实时运行 Evidence verifier、Evaluation Suite 和只读 Dashboard。不重置
`RESOLVED` 状态，不更换固定 task/run ID，不重放历史审批。

### 可选：新的 NON_FORMAL_LIVE_DEMO

只有当 Manager、五 Worker、Matrix、MinIO、Gateway 和 Runner 全部在录制前彩排通过时
才使用。新 run 必须用 `live-demo prepare` 生成独立 session，并有新的真人 Approval、
Matrix events、Runner Artifact 和 Auditor 裁决。任何环节不稳定时立即回到 Strategy C，
不在正式录制中调试。

## 窗口与标签

1. PPT 全屏窗口：定位、Trust Layer、AgentTeams、AT-002、AT-004、Evaluation。
2. Element：只保留 Manager 和五个 Worker 演示房间，隐藏其他私人/管理房间；
   不录制地址栏和完整私有 room ID。
3. PowerShell A：仓库根目录，字体至少 20 pt，只运行白名单命令。
4. PowerShell B：Gateway/服务日志，只展示脱敏状态，不展示容器环境变量。
5. Trust Dashboard：`http://127.0.0.1:8787/`。
6. Public Demo：`https://jakiic.github.io/LabOps-Guard/`。

录制中禁止运行无字段过滤的 `docker inspect`；它会把容器环境变量和凭据带入画面。

## 正式录制日操作顺序

1. 关闭 Windows 通知、邮件、私人聊天和自动补全弹窗；在 Element 中只保留比赛房间。
2. 打开最终 PPT、Element、PowerShell、Dashboard 和 Public Demo，按 Shot 01–12 排序。
3. 在仓库根目录启动只读 Dashboard：

   ```powershell
   docker compose up -d --build
   Invoke-RestMethod http://127.0.0.1:8787/healthz
   ```

4. 运行当日预检：

   ```powershell
   python -B -m labops demo-readiness
   python -B scripts/verify_evidence.py
   python -B scripts/run_semifinal_eval.py
   ```

   Strategy C 允许 Gateway 不启动，但必须在视频中明确说明本次是 Archived Verified Run
   + Live Verification；Evidence verifier 必须 PASS。如果宣称当前 Gateway 可用，则先启动
   Gateway，再运行 `demo-readiness --service-checks`，且 `18103/healthz` 必须当日实际 PASS。
5. 完成 30 秒试录，回放检查声音、字幕、光标、字体及是否出现个人路径。
6. 依次录制 Shot 01–12；任何关键门禁失败时废弃该 take，不在成片中解释调试。
7. 录制后逐帧检查 Token、room ID、地址栏、用户名、本机路径和系统通知，然后
   计算 MP4 SHA-256。
8. 不手工编辑已生成的 ZIP。使用隐私复核后的 MP4 重新构建完整附件：

   ```powershell
   python -B scripts/build_submission_bundle.py --output-dir release `
     --video "C:\path\LabOps-Guard-final-demo.mp4"
   ```

   输出必须为 `WITH-VIDEO`，Manifest 必须为 `COMPLETE_WITH_VIDEO`，内部不得再有
   `VIDEO_PENDING.txt`。

## Shot 计划

| Shot | Duration | Window | Action | Expected Result | Voice | Score Point | Fallback |
|---|---:|---|---|---|---|---|---|
| 01 | 0:00–0:25 | PPT 标题 | 展示“Agent 获得执行权后的信任问题” | 观众理解问题不只是模型指标 | 使用最终脚本 0:00 段 | 场景价值、安全可信 | 保留静态页，不做动画 |
| 02 | 0:25–0:50 | PPT Trust Layer | 依次高亮七环节 | Identity → Skill → Policy → Approval → Execution → Evidence → Audit | 使用 0:25 段 | Agent Infra 定位 | 使用架构图截图 |
| 03 | 0:50–1:05 | Element / Manager | 显示 `ARCHIVED VERIFIED RUN · 2026-08-04`；展示任务分派消息 | 看到真实发送者、task ref、event ID | 解释 Manager/Commander | AgentTeams 编排 | 用冻结 Trace 的首事件画面 |
| 04 | 1:05–1:25 | Element / Worker rooms | 快速切换五 Worker，停留 3–4 秒/房间 | 看到真实 handoff 与 artifact 引用 | 解释五角色与 Skill | 多 Agent 协作、Skill | 用已录真实房间片段；不得模拟聊天 |
| 05 | 1:25–1:55 | Public Replay / AT-002 | 高亮 Policy 拒绝、隔离 fixture、rollback verification | `POLICY_VIOLATION`，真实资源未执行 | 使用 AT-002 准确口径 | 异常处理、安全边界 | 用 AT-002 Evidence 页面 |
| 06 | 1:55–2:15 | Archived AT-004 plan + approval | 展示唯一变更、审批时间 | Approval 早于 Runner | 合法动作如何获批 | HITL、Policy | 用 Evidence Bundle 中 JSON 截图 |
| 07 | 2:15–2:35 | Archived Gateway/Runner | 展示 request、status、metrics、manifest | `network=none`、三次重复、protected hashes unchanged | 强调工具隔离 | Tool calling、工程落地 | 用冻结 runner manifest |
| 08 | 2:35–2:55 | Archived Auditor | 展示 `verification.json` 与 Trace audit | Auditor 独立得出 `PASS / RESOLVED` | Executor 不能自证 | Independent audit | 用 Auditor Evidence 页面 |
| 09 | 2:55–3:10 | PowerShell A | 运行 `python -B scripts/verify_evidence.py` | 三个正式包全部通过 | 当前实时独立验证 | Evidence、可复核 | 使用预先录制但标明同日 live verifier 输出 |
| 10 | 3:10–3:30 | Trust Dashboard | 滚动五段证据链；展示只读说明 | Identity → Policy → Execution → Evidence → Audit，无 Trust Score | Read-only Evidence Projection | 可观测性 | Public Replay；明确不是 live control console |
| 11 | 3:30–3:45 | Evaluation 报告 | 高亮 10 固定案例与 8 个 non-closable 案例 | 与预设 Oracle 一致，false resolution 为 0 | 非通用 Benchmark | 评测可信度 | 用 PPT 第 15 页 |
| 12 | 3:45–3:55 | GitHub / 结尾 | 展示 README、仓库和 Demo URL | 开放入口可见 | 使用英文结尾 | 开放复用 | 用 PPT 二维码页 |

## 当前 live 防重复门禁素材（可选 10 秒插片）

如果需证明当前服务在线，可在 Shot 03 前插入不超过 10 秒的 `LIVE CHECK · 2026-08-26`：

1. Element Manager room 显示 16:33 收到冻结 AT-004 Prompt；
2. Manager 16:34 复核历史交付、Trace、approval 与 ZIP 后明确“无需重跑”；
3. 旁白：“固定任务已有审计闭环，系统拒绝重复执行。我们不会清理状态来制造新 run。”

该插片只证明当前 Manager 在线和防重复门禁，不宣称发生了新的六角色 handoff、Runner 或 Auditor。

## 录制命令与预期输出

```powershell
# Strategy C 的只读契约/Evidence readiness；不会运行 AgentTeams。
python -B -m labops demo-readiness

# 只有当 Gateway 和 Dashboard 都已启动、且要展示实时服务时才运行：
python -B -m labops demo-readiness --service-checks --show-prompt

# 三个正式 Evidence Bundle 独立验证。
python -B scripts/verify_evidence.py

# Trust Evaluation Suite 确定性重建；不要在录制时修改 Oracle。
python -B scripts/run_semifinal_eval.py
```

预期：不带 service checks 的 readiness 为 `LOCAL_READY`；带 service checks 时只有
Docker/Gateway/Dashboard 都通过才是 `LOCAL_READY`；Evidence verifier 三包 PASS；Evaluation Suite
报告 10 个固定案例结果。`LOCAL_READY` 不等于产生了新 AgentTeams run。

## 状态驱动等待点

- Manager：以 Element 新消息或 Matrix event 为准，不用固定 sleep。
- Gateway：以 `/healthz` 和新输出目录文件为准。
- Runner：以 `status.json` 终态和 `artifact_manifest.json` 为准。
- Auditor：以真实 `verification.json` 与 Matrix event 为准。
- 本次固定 AT-004 不再进入上述等待，因为 Manager 已正确终止重复执行。

## 失败处理

| Failure | Action | 可否继续录制 |
|---|---|---|
| OBS/录制器未安装或试录无声 | 停止正式录制；安装后做 30 秒画面+声音+字体试录 | 否 |
| Element 未登录 | 由用户本人登录；不在录屏中输入密码/Token | 登录后可继续 |
| Manager/Worker 离线 | 不声称 live；仅用带标识的真实历史素材 | 可，Strategy C |
| Gateway/Docker 离线 | 不现场安装；展示冻结 Runner Evidence 与 verifier | 可，Strategy C |
| Dashboard 写方法不是 405 | 停止录制并调查 | 否 |
| Evidence verifier 失败 | 停止录制，不展示绿色状态 | 否 |
| 画面出现凭据/私有房间/绝对路径 | 立即停录并删除该 take | 否 |

## AT-002 固定口径

危险动作方案 → Policy / protected-resource boundary → real resource execution rejected → isolated
adversarial/tampered fixture 验证检测能力 → `POLICY_VIOLATION` / rollback verification。

不得说“真实生产 `metric.py` 已被 Agent 越权修改后系统才发现”。
