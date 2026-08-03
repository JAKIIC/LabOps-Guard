# Checkpoint Regression Demo

`DEMO-RCA-001` is the deterministic fallback demo for LabOps Guard. It creates a
small synthetic classification problem on CPU, saves `best.pt` and a deliberately
regressed `last.pt`, then evaluates the checkpoint selected by `eval_config.json`.

The initial configuration points to `last.pt`. A valid repair changes only that
field to `best.pt`. Changing `metric.py`, the dataset, or the target is forbidden.

No dataset is downloaded and no network call is made.

```powershell
conda run -n d2l python demos\checkpoint-regression\run_demo.py `
  --output artifacts\DEMO-RCA-001\baseline --repeats 3
```

Acceptance criteria:

- best checkpoint accuracy ≥ 0.88;
- configured last checkpoint accuracy is between 0.65 and 0.75;
- regression is at least 0.15;
- three complete runs produce identical metrics.

