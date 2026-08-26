# Automated Recording Feasibility Review

审查日期：2026-08-26。目标不是建设录屏平台，而是用最低风险完成一条 3:40–4:20 的比赛视频。

## 结论

**推荐自动化等级：Level 1。** 自动化录制后的剪切、拼接、字幕、响度归一化和导出；窗口切换、
Element 房间选择、素材真实性确认和最终开始/停止录制由人操作。

不建议在提交前实施独立 Phase 10。当前固定 AT-004 已 `RESOLVED`，再次触发被正确阻断；历史真实
run 约 21 分 10 秒。高度自动化既不能缩短 Agent 推理时间，也会增加登录、凭据、窗口焦点和误触
风险。若比赛后继续产品化，可把 Level 2 作为独立工程任务。

## 当前机器事实

| 项目 | 2026-08-26 实测 |
|---|---|
| OS | Windows；存在远程/虚拟显示适配器 |
| GPU | NVIDIA GeForce RTX 4060 Laptop GPU，约 4 GB 显存 |
| OBS Studio | 未发现 |
| FFmpeg / ffprobe | 未发现 |
| pywinauto | 当前 Python 环境未安装 |
| Playwright Python | 当前 Python 环境未安装 |
| obs-websocket Python client | 当前 Python 环境未安装 |
| Docker / AgentTeams | 在线，可运行；固定 AT-004 防重复门禁生效 |

因此自动录制不是代码阻塞，但正式视频当前有一个操作性 P0：先安装录制器并完成 30 秒试录。

## 动作分类

### A. Deterministic

- 启动/停止 Gateway 与 Dashboard；
- 检查 `/healthz`、`/health`、`/api/status`；
- 运行 readiness、Evidence verifier、Evaluation Suite；
- 打开固定 URL、PPT 页和只读 Evidence；
- OBS 开始/结束、Scene 切换；
- FFmpeg 剪切、拼接、混音、字幕和 MP4 导出。

这些动作适合 PowerShell、HTTP、OBS WebSocket 与 FFmpeg，不需要视觉 Agent。

### B. State-driven

- 等待 Manager/Worker handoff：监听 Matrix event 或 Element 明确的新消息；
- 等待 Gateway：轮询健康端点；
- 等待 Runner：监听 `status.json` 和 `artifact_manifest.json`；
- 等待 Auditor：监听真实 `verification.json` 与 Matrix event；
- 等待录制输出：监听 OBS 状态和文件大小稳定。

禁止用固定 sleep 代替状态判断。本次 Strategy C 不触发新的固定 AT-004 run，因此只需对 verifier、
Dashboard 和录制文件使用状态检测。

### C. Human Required

- Element 登录与任何凭据输入；
- 独立人工 Approval；
- 开始正式录制前的画面隐私检查；
- 确认 archived/live 标签与当前素材匹配；
- 最终成片事实复核和上传。

自动流程只能暂停等待用户，不能代替审批或安全确认。

### D. Not Recommended

- 让视觉 Agent 自由点击整个 Windows 桌面；
- 自动批准计划或危险动作；
- 自动填写/读取 Token、密码、Cookie 或容器环境变量；
- 清理 `RESOLVED` 状态、换 ID 或模拟六 Agent 以获得“新素材”；
- 用固定 sleep 假装 Manager、Runner 或 Auditor 已完成。

## 工具评估

### Screen recording

| Tool | 维护/许可证 | 适配判断 |
|---|---|---|
| [OBS Studio](https://obsproject.com/) | 活跃维护；GPL-2.0-or-later；Windows 10/11；官方当前页提供最新发行版 | **推荐主录制器**。Scene、窗口捕获、麦克风与硬件编码适合比赛视频 |
| [obs-websocket](https://obsproject.com/kb/remote-control-guide) | OBS 28+ 已内置；官方建议启用密码保护 | Level 2 才使用；本轮人工切 Scene 更稳妥，不单独安装旧插件 |
| [FFmpeg](https://ffmpeg.org/legal.html) | 活跃；默认 LGPL-2.1-or-later，启用 GPL 组件时整套按 GPL | **推荐后期工具**；应记录所用构建及许可证，避免不必要的专利/非自由组件 |

OBS 未安装意味着当前不能直接正式录制；最小解决方案是安装官方 Windows 版、配置本地录制、
启用 NVENC 或稳定的软件编码，然后做一次 30 秒试录。不要在提交包中再分发 OBS/FFmpeg 二进制。

### Browser

[Playwright](https://github.com/microsoft/playwright) 活跃维护，Apache-2.0，可确定性打开 Public Demo、
Dashboard 和等待 DOM 状态。它适合后续 Level 2，但 Element 是复杂 SPA 且包含登录态；提交前不应
为了自动切房间额外引入 Node/Python 运行时与浏览器版本依赖。现阶段人工切换并使用固定 shot
顺序风险更低。

### Windows GUI

| Tool | 状态/许可证 | 建议 |
|---|---|---|
| PowerShell / Windows UI Automation | 系统能力 | 首选：启动程序、窗口定位、健康检查 |
| [pywinauto](https://github.com/pywinauto/pywinauto) | BSD-3-Clause；项目可用但发行节奏较慢 | 可作为 Level 2 的窗口焦点 fallback；提交前不引入 |
| [Microsoft UFO / UFO²](https://github.com/microsoft/UFO) | MIT；活跃且功能范围大 | 不适合本轮：需模型、配置和更大的 GUI Agent 运行面 |
| [Open Interpreter](https://github.com/openinterpreter/openinterpreter) | Apache-2.0；活跃 | 不适合本轮：自由式电脑操作增加不可预测性和凭据暴露面 |

### 中文 TTS

| 方案 | 中文自然度 | Windows/硬件 | 许可证与分发边界 | 结论 |
|---|---|---|---|---|
| [CosyVoice](https://github.com/QwenAudio/CosyVoice) | 高，官方覆盖普通话与多种方言/风格 | 安装较重；官方流程以 Python 3.10、模型下载和 GPU/服务部署为主；4 GB 显存需实测 | 代码 Apache-2.0；模型、参考音频和第三方组件仍需逐项核对 | 适合赛后精修；不建议为本轮临时搭建 |
| [Piper (OHF-Voice)](https://github.com/OHF-Voice/piper1-gpl) | 轻量；2026 版本已增加中文 phonemizer，但自然度通常低于大模型 TTS | CPU/离线友好，Windows wheel 可用 | 当前维护分支 GPL-3.0；voice 模型许可证必须单独核对 | 可作离线备用旁白，不随提交包再分发引擎或模型 |
| [piper-plus](https://github.com/ayutaz/piper-plus) | 支持中文，轻量 | CPU/离线，需额外兼容性试验 | 仓库声明 MIT 且不依赖 espeak-ng；voice 模型仍需单独核对 | 时间不足时不引入未经试录的新 fork |
| 本人录音 | 取决于录音环境 | 零模型依赖 | 只处理本人音频授权 | **本轮首选**；事实口径与节奏最可控 |

若使用克隆声音或第三方 voice，必须保留明确授权；不要仅凭引擎许可证推断模型或声音可分发。

### Post-production

FFmpeg 可确定性完成：

- `trim` / `atrim`：裁剪等待；
- concat demuxer/filter：拼接 shot；
- `amix`：混合旁白与系统声；
- `subtitles`：烧录 SRT；
- `loudnorm`：两遍响度归一化；
- H.264/AAC MP4：生成高兼容交付文件。

正式导出前保存命令、输入文件 SHA-256、FFmpeg build 配置和输出 SHA-256。不要用 FFmpeg 改写
Evidence 或把隐藏的 live 间隔剪成虚假的连续执行。

## 推荐 Level 1 流程

```text
人工隐私检查
  → OBS 人工录制每个真实 Shot
  → 人工核对 LIVE / ARCHIVED 标签
  → FFmpeg 自动裁剪/拼接/响度/字幕
  → 人工事实与敏感信息复核
  → 生成最终 MP4 SHA-256
```

## 如果赛后进入 Level 2

仅设计如下薄层，不在当前冻结分支创建 `tools/demo-recorder/`：

- `recording_plan.yaml`：shot、窗口、标签、预期状态；
- `orchestrator.py`：状态机，只编排录制，不编排 AgentTeams；
- `obs_controller.py`：通过带认证的本机 obs-websocket 切 Scene；
- `browser_controller.py`：只控制 Dashboard/Public Demo，不接触登录凭据；
- `agentteams_watcher.py`：只读 Matrix event、HTTP 和 artifact 状态；
- `video_renderer.py`：FFmpeg 渲染与 SHA-256。

预计 500–800 行代码、5–7 个直接依赖、2–3 个工程日，加 1 天 Windows/OBS 稳定性测试。该投入
不会明显提升本次复赛评分，因此**不值得进入独立 Phase 10**。

## 必须人工完成的下一步

1. 轮换可能暴露的 HiClaw/Matrix/MinIO/LLM 凭据；
2. 安装 OBS 官方 Windows 版或选择已有可信录制器；
3. 完成 30 秒试录，核对分辨率、麦克风、系统声、编码与窗口隐私；
4. 按 Runbook 录制 Strategy C；
5. 安装经确认来源的 FFmpeg 或使用编辑器完成后期；
6. 对最终 MP4 做逐帧敏感信息检查并生成 SHA-256。
