# Known Limitations

## Preserved formal case

- `LABOPS-AT-002` is intentionally immutable and remains `BLOCKED`: its Worker lacked
  PyTorch, proving the system stops safely when execution capabilities are absent.

## Phase 3

- `labops/pytorch-cpu-runner:0.1.0` is a local Docker image. A machine reproducing
  LABOPS-AT-003 must build or load that exact image before execution.
- Image construction may access the official Python and PyTorch package registries;
  experiment containers always run with `--network none` and never install packages.
- The Runner adapter requires a local Docker daemon. Agent Workers never receive the
  Docker socket, credentials, API keys or package-install permissions.
- CPU results are deterministic for the bundled synthetic fixture. Other hardware,
  PyTorch versions or external datasets are outside the AT-003 evidence claim.
- The host Gateway is a short-lived localhost control-plane adapter for the demo, not
  a production multi-tenant service. It accepts only the exact AT-003 task, incident,
  image and run-id pattern, and still requires the recorded human approval payload.
- Docker Desktop must expose `host.docker.internal` to Agent Worker containers. A
  production deployment should replace the localhost adapter with an authenticated,
  mutually trusted runner service and an external job scheduler.
- AgentTeams automatic Matrix wake-up was intermittent during AT-003. Already-dispatched
  tasks were executed through each Worker's own OpenClaw Gateway; the resulting tool
  calls, artifacts, MinIO objects and Matrix handoffs are preserved. This is an
  orchestration reliability limitation, not a Runner result substitution.
- The Worker-side Auditor cannot import PyTorch. It therefore verifies the control-plane
  Runner's raw repeated metrics, immutable-file hashes, manifest, approval ordering and
  trace chain; it does not independently execute the model inside the Worker.
- `agentteams_trace_audit.json` intentionally preserves the first failed total-trace
  audit (duplicate Matrix event ID). The corrected, authoritative result is
  `agentteams_trace_audit_final.json` with `CHAIN_OK / ACCEPTED`.
