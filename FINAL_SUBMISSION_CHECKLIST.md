# LabOps-Guard Final Submission Checklist

候选版本：`v1.0-rc1`

Python 包版本：`1.0.0rc1`

交付边界：source-only；不包含 Runner 镜像、镜像 tar、Token、私有 room ID 或本机绝对路径。

## A. 必交材料

- [x] 更新版项目方案 PPT：`submission/LabOps-Guard-GOAI-复赛方案-v1.0-rc1.pptx`
- [x] 同步 PDF：`submission/LabOps-Guard-GOAI-复赛方案-v1.0-rc1.pdf`
- [x] 可核验源码、六 Agent 配置、七 Skill Registry/Schema、Runner Gateway 与 Sandbox Runner
- [x] 第三方运行手册：`docs/final-demo-guide.md`
- [x] AgentTeams 真实演示准备与验证入口：`labops live-demo prepare/verify`
- [x] 样例输入、输出、Trace、Approval、Runner Artifact、Auditor 与 Evidence Bundle
- [x] Trust Evaluation Suite v1.0 结果与方法报告
- [x] GitHub URL：`https://github.com/JAKIIC/LabOps-Guard`
- [x] Public Demo URL：`https://jakiic.github.io/LabOps-Guard/`
- [ ] 最终 Demo 视频 MP4（项目所有者录制并逐帧检查）
- [ ] 比赛平台所需的个人/团队信息及最终表单（项目所有者填写）

## B. 冻结事实

- [x] 六 Agent、七 Skill 数量不变；Human Approval 不计作 Agent
- [x] Trust Contract v1、Trust State Machine v1 不变
- [x] AT-004 保持 `71.875% × 3 → 97.8124976% × 3` 与 `PASS / RESOLVED`
- [x] AT-002 保持 `POLICY_VIOLATION / ROLLED_BACK`
- [x] Dashboard 只读，不执行、不修改、不审批、不生成 Trust Score
- [x] Evaluation 只称 10 个固定治理案例，不称通用 Benchmark，不声称“100% 安全”
- [x] Skill 运行时证据不外推：历史 Trace 不补写 `skill_id`
- [x] Runner 镜像许可证门禁保持关闭，不随提交包分发

## C. 本地候选验证

从仓库根目录执行：

```powershell
python -B -m unittest discover -s tests -p "test_*.py"
python -B scripts/verify_evidence.py
python -B scripts/run_semifinal_eval.py
python -B scripts/build_public_demo.py --check
python -B scripts/scan_sensitive.py --repo-root .
python -B -m labops demo-readiness
```

- [x] 167 项测试通过
- [x] AT-002/003/004 Evidence verifier 通过且 SHA 不变
- [x] 10 个治理案例评测通过
- [x] Public Demo stale/CSP/无脚本检查通过
- [x] 敏感信息扫描无发现
- [x] PPT/PDF 18 页且逐页无溢出
- [x] `submission/SHA256SUMS.txt` 与 PPT/PDF、评测 JSON 和评测报告一致

## D. Source Package

最终代码提交后，使用 Git 归档生成源码包，避免把 `.git`、忽略目录、live session 或本机缓存带入：

```powershell
$shortSha = git rev-parse --short=7 HEAD
git archive --format=zip --prefix=LabOps-Guard-v1.0-rc1/ `
  -o "release/LabOps-Guard-v1.0-rc1-$shortSha-source.zip" HEAD
```

标准安装命令为 `python -m pip install --no-deps .`；完全离线安装需预先提供
`setuptools>=68`，不要误用缺少构建后端的 `--no-build-isolation` 环境。

- [x] 源码包由最终 Task 5B commit 生成
- [x] 解压后可安装 `1.0.0rc1` 并运行 CLI
- [x] 源码包内没有 `release/`、`.git/`、`.env`、密钥、私有 room ID、绝对路径或 Runner 镜像
- [x] `release/FINAL_CANDIDATE_MANIFEST.txt` 已登记 commit 与源码包 SHA-256

## E. 公开仓库与上传门禁

- [ ] Task 5B 候选已合入并推送公开 `main`
- [ ] `git ls-remote origin refs/heads/main` 等于最终登记 SHA
- [ ] GitHub Actions Windows/Linux、Python 3.9/3.12 全部通过
- [ ] Pages 从最终 `main` 重新部署并返回 HTTP 200
- [ ] GitHub About、README、PPT/PDF、Demo 页定位一致
- [ ] PPT/PDF 二维码及可见 URL 均可访问
- [ ] 最终视频无 Token、通知、私有 room、桌面路径或个人隐私
- [ ] 视频 SHA-256 已登记
- [ ] 比赛平台上传后重新下载/打开全部文件复核
- [ ] 最终提交时间、公开 SHA、源码包 SHA、视频 SHA 已离线留档

## F. 最终停止条件

出现以下任一情况时停止上传并回到最近通过门禁的提交：

- 正式 Evidence SHA 变化；
- Runner 在缺少或不匹配 ApprovalGrant 时仍执行；
- Public Demo 出现脚本、网络请求、写入口或私有数据；
- 源码包不是由登记的 Git commit 生成；
- GitHub `main`、Pages、PPT/PDF 或提交包版本不一致；
- 视频把 Archived Replay 描述为 live execution，或把受控评测宣传为生产 ROI。
