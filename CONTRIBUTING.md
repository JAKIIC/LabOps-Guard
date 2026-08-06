# Contributing

Thank you for helping improve LabOps Guard. Before opening a change:

1. Keep the six-role boundary and core state machine stable unless an issue explicitly approves
   a contract change.
2. Never commit credentials, private datasets, checkpoints, host-specific absolute paths, or
   generated release directories.
3. Add or update tests for policy, Schema, evidence integrity, and failure behavior.
4. Run `python -B -m unittest discover -s tests -p "test_*.py" -v` and
   `python -B scripts/verify_evidence.py`.
5. Describe the user-visible outcome, safety impact, evidence affected, and rollback path.

Pull requests should be small and reviewable. Do not rewrite formal AT-002/003/004 evidence;
publish a new versioned bundle when a derived artifact is required. A passing test or prettier
dashboard never justifies weakening approval, hash, rollback, network, or workspace controls.

The repository license is currently pending owner confirmation. Contributions should not be
submitted under an assumed Apache-2.0 grant until `LICENSE` contains the approved full text.
