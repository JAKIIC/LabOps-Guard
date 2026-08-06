# Security policy

## Supported scope

Security fixes are accepted for the current default branch and the latest local release candidate.
Historical demo evidence remains immutable; corrections must be published as a new derived bundle.

## Reporting

Use the repository's private security-advisory channel when it is available. If it is not enabled,
contact the project owner through the existing competition collaboration channel. Do not place
credentials, private data, exploit details, or unredacted logs in a public issue.

Include the affected version or commit, reproduction boundary, expected/observed policy result,
and whether evidence integrity or approval ordering may be affected. The maintainer will acknowledge
the report, classify impact, and coordinate a fix before public disclosure.

## Security invariants

Changes must not bypass human approval, allow forbidden actions, expose Docker or credentials to
Workers, enable experiment networking, write the original workspace, accept invalid traces, or let
an Executor self-verify. If a safe fix is not available, fail closed and report `BLOCKED`.
