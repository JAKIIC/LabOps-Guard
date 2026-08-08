# Reproducible experiment scenarios

`demos/` contains source code and deterministic fixtures used to reproduce controlled incidents.
These files are inputs to the restricted Runner, not proof that an AgentTeams run occurred.

- `eval-drift/` is the AT-004 main scenario: evaluation preprocessing drift with a fixed model,
  checkpoint, metric and validation set.
- `checkpoint-regression/` is the AT-003 fallback scenario: evaluation selects `last.pt` instead of
  `best.pt`.

The Runner copies only allowlisted files into a new sandbox, disables network access and writes a new
artifact set for each run. Immutable AgentTeams evidence packages live in [`../demo/`](../demo/).
