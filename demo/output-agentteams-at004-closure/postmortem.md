# LABOPS-AT-004 incident postmortem

Status: `PASS / RESOLVED`  
Publisher: Incident Commander  
Source evidence SHA-256: `4092b43f39df52db3847caa28ca01e4321129a1c17ec7ca5efd2029ab1fb77cd`

The same model, checkpoint, validation data, metric, and evaluation protocol repeatedly scored
71.88%, compared with the registered historical result of about 97.81%. The only supported
high-confidence difference was the evaluation preprocessing profile: `train_augmented` instead
of `eval_standard`.

After explicit human approval, the Safe Executor changed that one field only inside a fresh,
offline CPU sandbox. Three candidate evaluations reached 97.81%. The Verification Auditor
recomputed the metric from raw output, verified every protected hash, checked the approval
timestamp and seven-entry trace, and returned `PASS / RESOLVED`.

The reusable lesson is narrow: when a stable evaluation regresses while checkpoint, data, and
metric hashes remain unchanged, compare the registered evaluation preprocessing contract. This
memory is not proof for another incident and never replaces fresh evidence or approval.
