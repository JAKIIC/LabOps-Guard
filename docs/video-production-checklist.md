# Demo video production checklist

Target length: 3:30–4:00. Use `docs/demo-video-script.md` as the narration source.

## Record

- 1920×1080, 30 fps, system scale fixed before recording.
- Show AT-004 as the primary case; AT-002 and the illegal metric branch only as safety evidence.
- Show the six-role handoff, approval timestamp, Runner checks, exact three-run metrics, protected
  hashes and final Auditor decision.
- Keep browser notifications, tokens, local absolute paths, email, phone and unrelated tabs off-screen.
- Do not call a replay “live execution.” If using archived evidence, label it clearly.

## Fallback

- Dashboard unavailable: use the verified PPT/PDF plus evidence validation output.
- Docker unavailable: show the preserved `BLOCKED` branch; do not install dependencies on stage.
- AgentTeams unavailable: show the real handoff manifest and trace event IDs; prompts are not proof.
- Hash or trace failure: stop the closure and report `BLOCKED` or `INCONCLUSIVE`.

## Final review

- [ ] Spoken values match `71.875% × 3 → 97.8124976% × 3`.
- [ ] Runner is `0.2.0`, CPU, non-root, `network=none`.
- [ ] Human approval is separate from the six Agents.
- [ ] No claim of deployed MCP, RAG, OpenTelemetry backend or production scale.
- [ ] No Runner image download is offered while redistribution gates remain blocked.
