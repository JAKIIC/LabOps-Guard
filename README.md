# LabOps Guard — P0 Vertical Slice

Local-first controlled experiment operations for AI/algorithm lab reproducibility.
Implements the full chain: **snapshot registry/hash → evidence → hypothesis (with
mandatory evidence_id) → approval gate → controlled action → verification → append-only
JSONL trace (hash chain)**.

**Principles:** 无证据不诊断，无审批不执行，无验证不闭环
(no evidence → no diagnosis; no approval → no execution; no verification → no closure).

Standard-library **Python only** — no third-party dependencies, no installs, no network.
Includes a local read-only visual dashboard and a hardened Docker one-click demo.
Includes AgentTeams identity, handoff, state-machine, and reusable Skill contracts.

---

## Architecture (REAL vs SIMULATED)

| Component | Module | Nature | Notes |
|-----------|--------|--------|-------|
| Snapshot Registry | `labops/registry.py` | **REAL** | SHA-256 of allowed files + cross-check vs verification JSON |
| Evidence Collector | `labops/evidence.py` | **REAL** | Loads audit evidence_index + evidence_gaps; never reads excluded data |
| Diagnosis Engine | `labops/diagnosis.py` | **REAL** (rule-based) | Every hypothesis requires ≥1 evidence_id; no evidence → UNKNOWN/BLOCKED |
| Approval Gate | `labops/approval.py` | **REAL** | read_only_auto / manual_approval / forbidden; approve/reject/timeout first-class |
| Action Executor | `labops/action.py` | **REAL benign + SIMULATED risky** | dry-run default; allowlist; workspace boundary; timeout; truncate+redact |
| Verification Closer | `labops/verify.py` | **REAL** | Only PASSED closes; FAILED/PARTIAL/NOT_VERIFIED keeps BLOCKED |
| Trace Log | `labops/trace.py` | **REAL** | append-only JSONL with SHA-256 chain |
| Demo Harness | `labops/demo.py` | **REAL chain + SIMULATED risk actions** | polar-baseline 10 real gaps |

**SIMULATED note:** risky actions (`pip install`, download, train) are **recorded as
intent only** — never actually executed. LabOps Guard does **not** claim to fix the Polar
root cause or resolve missing evidence; it only surfaces gaps and enforces the guard loop.

---

## Layout

```
labops-guard/
├── labops/            # package (CLI + modules)
│   ├── cli.py         # CLI entry
│   ├── __main__.py    # python -m labops
│   ├── registry.py
│   ├── evidence.py
│   ├── diagnosis.py
│   ├── approval.py
│   ├── action.py
│   ├── verify.py
│   ├── trace.py
│   ├── demo.py
│   ├── web.py        # local read-only JSON API/server
│   └── dashboard.html
├── docs/planning/     # 6 approved planning specs (copies)
├── agentteams/         # identities, state machine, task contract, Manager prompt
├── skills/             # 5 reusable LabOps Guard Skill packages
├── tests/             # standard-library unittest
├── demo/              # demo runbook script + generated outputs
├── Dockerfile
├── compose.yaml
├── docker-start.ps1
├── README.md
└── SELF_CHECK.md
```

---

## Commands

### 新主 Demo：checkpoint regression

CPU PyTorch 环境使用本机已有的 `d2l`，不下载数据、不访问网络。可直接双击
`demo-checkpoint.cmd`，或运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\demo-checkpoint.ps1
```

脚本依次完成：三次稳定基线 → 合法 checkpoint 修复 → 非法 metric 篡改拦截与回滚。
期望结果：`DEMO-RCA-001 = RESOLVED/PASS`，`DEMO-RCA-002 = ROLLED_BACK/POLICY_VIOLATION`。

也可以单独运行统一事故入口：

```powershell
D:\APP\Anaconda\envs\d2l\python.exe -m labops run-incident `
  --incident demos\checkpoint-regression\incident.json
```

> Self-contained: the demo uses bundled fixtures in `demo/fixtures/` (13 verified
> snapshot files + verification + 5 audit files). **No MinIO paths needed.**
> Defaults are repo-relative; override via `LABOPS_FIXTURES` / `LABOPS_OUTPUT`.

### Linux / macOS (python3)

```bash
# full test suite (no bytecode cache)
python3 -B -m unittest discover -s tests -p "test_*.py" -v

# full demo (uses demo/fixtures, writes demo/output)
bash demo/run_demo.sh

# or run the chain manually against bundled fixtures
python3 -B -m labops demo \
  --workspace demo/output \
  --snapshot demo/fixtures/project_snapshot_lite \
  --audit-dir demo/fixtures/audit \
  --verification demo/fixtures/snapshot_verification.json \
  --allowed-list demo/allowed_files.json

python3 -B -m labops trace --workspace demo/output --verify
```

### Windows / PowerShell (python)

From the staged project root `E:\AICompetition\LabOpsWorkspace\labops-guard`:

```powershell
# full test suite (no bytecode cache)
python -B -m unittest discover -s tests -p "test_*.py" -v

# full demo (uses demo\fixtures, writes demo\output)
powershell -ExecutionPolicy Bypass -File .\demo\run_demo.ps1

# or run the chain manually against bundled fixtures
python -B -m labops demo `
  --workspace demo\output `
  --snapshot demo\fixtures\project_snapshot_lite `
  --audit-dir demo\fixtures\audit `
  --verification demo\fixtures\snapshot_verification.json `
  --allowed-list demo\allowed_files.json

python -B -m labops trace --workspace demo\output --verify
```

### 使用 Conda `polar` 环境（推荐）

```powershell
conda activate polar
python -B -m unittest discover -s tests -p "test_*.py" -v
powershell -ExecutionPolicy Bypass -File .\demo\run_demo.ps1
python -B -m labops web --workspace demo\output --host 127.0.0.1 --port 8787
```

然后打开 <http://127.0.0.1:8787>。页面和 `/api/status` 均为只读，
只读取 LabOps Guard 生成的白名单 JSON 文件，不提供任意文件访问。

### Docker Desktop 一键启动

确保 Docker Desktop 左下角显示 Engine running，然后在项目根目录执行：

可以直接双击 `docker-start.cmd`，或在 PowerShell 中执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\docker-start.ps1
```

首次启动需要拉取 `python:3.11-slim` 基础镜像。构建完成后打开
<http://127.0.0.1:8787>。停止服务：

可以双击 `docker-stop.cmd`，或执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\docker-stop.ps1
```

脚本检测到本地已有 `labops-guard:local` 时会直接启动；代码更新后需要重建时使用：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\docker-start.ps1 -Rebuild
```

若 Docker Hub 暂时不可达、但旧版 `labops-guard:local` 已在本机，可只刷新仪表盘代码：

```powershell
docker build --pull=false -f Dockerfile.dashboard-refresh -t labops-guard:local .
docker compose up -d --no-build --force-recreate
```

容器以非 root 用户运行，只监听本机 `127.0.0.1:8787`，根文件系统只读，
Compose 默认将 `demo/output-agentteams`、`artifacts` 和
`demo/output-agentteams-at002` 以只读方式挂载。仪表盘直接读取 AgentTeams
归档，并在服务端独立校验 ZIP、包内 artifact 和 trace 哈希链，而不是伪造或重放前端数据。该目录只包含
白名单产物，不挂载竞赛私有数据，也不需要外部 API；单独运行镜像时仍使用内置演示。

## AgentTeams 协作任务

首个真实协作任务为 `LABOPS-AT-001`，包含 5 个不同职责 Agent 和 5 个 Skill：

| Agent | Skill | 职责边界 |
|---|---|---|
| LabOps Manager | `pack-lab-evidence` | 只编排、维护状态和汇总，不执行或自证 |
| Evidence Collector | `collect-lab-evidence` | 只读白名单快照并生成证据 |
| RCA Analyst | `diagnose-lab-incident` | 只基于 evidence_id 生成受限假设 |
| Controlled Executor | `control-lab-action` | 分类、dry-run、等待审批和受控执行 |
| Verification Auditor | `verify-lab-result` | 从原始产物独立验证，决定能否闭环 |

在 AgentTeams Manager 房间发送
`agentteams/prompts/manager_task.md` 的内容。Manager 必须按
`agentteams/tasks/LABOPS-AT-001.json` 和 `agentteams/state_machine.json`
进行至少四次跨角色交接；任何路径或工具缺失均返回 `BLOCKED`，不得伪造结果。

Agent Identity 和框架映射详见 `agentteams/agent_identities.json` 与
`docs/agentteams_mapping.md`。

### LABOPS-AT-002 六角色实跑

checkpoint 线路的 Manager 任务为 `agentteams/prompts/checkpoint_demo_task.md`。
2026-08-03 的真实运行已固化为 `demo/output-agentteams-at002` 证据包：六角色和
六次 handoff 均真实发生；非法 `metric.py` 路径得到
`POLICY_VIOLATION / ROLLED_BACK`。合法路径因 Worker 环境缺少 PyTorch，只能得到
`INCONCLUSIVE / DEMO_PASSED_NOT_RESOLVED`，总状态为 `BLOCKED`。详细的演示口径和证据定位见
`docs/LABOPS-AT-002-DEMO.md`。

### LABOPS-AT-003 专用 PyTorch Runner

AT-003 保留同一六角色治理链，但 Safe Executor 不再在 Worker 中运行或安装
PyTorch。它只提交经过人工审批的结构化 ExperimentPlan；本机控制面用
`labops/pytorch-cpu-runner:0.1.0` 在无网络、非 root、只读且限额的容器内运行。
三次本地验证及真实 AgentTeams 运行均得到 `70.00% → 98.12%`，且 `metric.py`、
验证数据和原始工作区未修改。Verification Auditor 独立复核通过后，最终状态才是
`PASS / RESOLVED`。证据和演示口径见 `docs/LABOPS-AT-003-DEMO.md`。

> `-B` avoids writing `__pycache__`; backtick `` ` `` is the PowerShell line
> continuation. All commands run from the project root; no absolute/MinIO paths.

---

## Tests

```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
```

Covers: no-evidence diagnosis refusal, approval rejection/timeout, forbidden action,
out-of-boundary path, simulated action, verification failure, trace hash-chain integrity
(+ tamper detection), the full polar-baseline demo, the offline Runner contract,
incident identity isolation, and independent AT-003 evidence-package revalidation.

---

## Safety & Constraints

- **No installs, no network, no training** — enforced; risky ops SIMULATED.
- **Excluded data never read** (train/test CSV, private labels, keys, checkpoints).
- **Default dry-run**; command allowlist; workspace boundary; timeout; output truncation
  + redaction.
- **No fabricated faults**; no claim of fixing Polar root cause; no model-optimization
  suggestions.
- This slice does **not** write to `/host-share` — it is staged there by the Manager.
