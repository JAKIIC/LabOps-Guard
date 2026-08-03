# LabOps PyTorch CPU Runner 0.1.0

`labops/pytorch-cpu-runner:0.1.0` is an execution appliance, not an Agent. Safe
Executor supplies a structured ExperimentPlan; the host adapter starts one
ephemeral container with `--network none`, read-only inputs and a read-only root
filesystem. The container accepts only `evaluate_checkpoint`.

Runtime controls:

- non-root UID 10001;
- CPU only, one CPU, 768 MiB memory and 64 processes;
- `--network none`, all Linux capabilities dropped and no-new-privileges;
- source project and baseline inputs mounted read-only;
- only `/output` and a bounded `/tmp` are writable;
- no credentials are accepted in ExperimentPlan and none are copied to image;
- exact Python 3.11.15 and CPU PyTorch 2.5.1+cpu labels are checked before use.

Build:

```powershell
docker build -f runner\Dockerfile -t labops/pytorch-cpu-runner:0.1.0 runner
```
