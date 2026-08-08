# Runner image license review

Review date: 2026-08-09
Images: `labops/pytorch-cpu-runner:0.1.0` and `:0.2.0`

## Result

The offline inventory completed successfully, but it does **not** authorize image redistribution.
The source repository and Dockerfiles may remain public. Publishing either image, an image tar, or a
release bundle containing the image remains blocked until the four release gates below are closed.

## What was inspected

- Both local image IDs were read directly from Docker.
- Each image was started with `--network none --read-only` only to enumerate installed software.
- The generated CycloneDX 1.5 file contains 171 unique components: two container images, Python
  distributions, and Debian packages. See `runner-sbom.json`.
- Direct Python runtime dependencies are permissively licensed: PyTorch is BSD-3-Clause; Jinja2,
  MarkupSafe, fsspec, networkx, mpmath and sympy use BSD-family licenses; filelock, pip, setuptools
  and wheel use MIT-family licenses; typing_extensions uses PSF-2.0.
- The runtime OS is Debian GNU/Linux 13. Debian packages include mixed permissive, GPL and LGPL
  terms. Their installed copyright files are authoritative; the SBOM does not guess SPDX IDs.

## Release gates

| Gate | Status | Required evidence |
|---|---|---|
| Base image redistribution terms | BLOCKED | Written license/provenance for the exact pinned `agentteams-copaw-worker` base layers |
| Complete image NOTICE bundle | BLOCKED | Python, PyTorch, base-image and transitive notices copied into the distributable image/package |
| Debian source obligations | BLOCKED | Corresponding-source or valid source-offer process for every distributed copyleft binary |
| Final digest review | BLOCKED | Rebuild the final image, rerun `scripts/build_runner_sbom.py`, compare digests, then approve |

## Decision

Do not create `v0.3.0-rc1`, do not publish a GitHub Release, and do not export/push the Runner image
while any gate is blocked. This is a distribution boundary, not a runtime defect: the local,
network-disabled competition demo remains valid.
