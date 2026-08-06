# Incident case memory

`memory/cases/` is a lightweight, local index of evidence-backed incident closures. Each JSON
record points to an immutable source evidence bundle and captures only the reusable failure
signature, diagnosis, bounded repair, safety checks, result, and limitations.

Search locally with:

```text
python -m labops.case_memory search "evaluation drift"
```

Case memory is advisory context for future diagnosis. It is never sufficient evidence for a
new incident and never bypasses collection, approval, execution, or independent verification.
