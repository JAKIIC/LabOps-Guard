# 离线部署与复现

## 环境

- Windows 10/11 + Docker Desktop；
- PowerShell 5.1+；
- Python 3.9+（宿主机只负责控制面，PyTorch 固定在 Runner 镜像）；
- 建议至少 4 GB 可用内存、3 GB 可用磁盘。

## 开发目录检查

```powershell
.\scripts\check_environment.ps1 -PythonPath D:\APP\Anaconda\envs\polar\python.exe
.\scripts\verify_evidence.ps1 -PythonPath D:\APP\Anaconda\envs\polar\python.exe
```

## 离线 Release 复现

1. 校验整个 Release：

```powershell
.\scripts\verify_release.ps1 -ReleaseDirectory .\release\v0.2.0-rc1
```

2. 解压 `labops-guard-source.zip` 到新的空目录。
3. 将 Release 中 AT-003 的 ZIP 与 manifest 放到解压目录：

```text
demo/output-agentteams-at003/artifacts/DEMO-RCA-003/
```

AT-002 已随冻结源码提交；若分发环境中没有，也从 `release/evidence/` 放到 `demo/output-agentteams-at002/`。

4. 离线加载 Runner 和仪表盘镜像：

```powershell
.\scripts\load_runner_image.ps1 `
  -Archive ..\release\v0.2.0-rc1\labops-pytorch-runner-0.1.0.tar `
  -DashboardArchive ..\release\v0.2.0-rc1\labops-guard-dashboard-local.tar `
  -Checksums ..\release\v0.2.0-rc1\checksums.sha256
```

5. 用固定 fixture 连续运行三次 AT-003：

```powershell
.\scripts\run_local_demo.ps1 `
  -FixtureZip ..\release\v0.2.0-rc1\demo-fixture\LABOPS-AT-003-baseline-fixture.zip
```

6. 启动只读仪表盘：

```powershell
.\scripts\start_dashboard.ps1
```

访问 <http://127.0.0.1:8787/>。停止服务使用 `.\scripts\stop_labops.ps1`。

## 预期验收

- RuntimeCapabilityCheck：`PASS`；
- 三次运行均为 `70.00% → 98.12%`；
- `metric.py` 与验证数据哈希不变；
- AT-002：`BLOCKED`；AT-003：`PASS / RESOLVED`；
- 非法案例：`POLICY_VIOLATION / ROLLED_BACK`；
- 仪表盘同时展示两个正式案例；实验期间无需联网。

## 常见故障

| 故障 | 行为 | 处理 |
|---|---|---|
| Docker 未启动 | 环境检查 FAIL | 启动 Docker Desktop后重试 |
| Runner 镜像缺失 | RuntimeCapabilityCheck FAIL | 使用 Release tar 离线加载 |
| 8787 被占用 | 仪表盘启动失败 | 停止占用进程或已有演示容器 |
| ZIP 被修改 | 证据验证 FAIL | 恢复正式证据，不跳过哈希检查 |
| Trace 重复或断链 | Auditor 拒绝收口 | 保留 ISSUE，修正来源事件后重新审计 |
| Matrix Worker 未唤醒 | 实时路径 BLOCKED | 使用已归档真实证据回放并明确说明 |
| 人工拒绝审批 | 不启动 Runner | 保持拒绝状态，不绕过审批 |
