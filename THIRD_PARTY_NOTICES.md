# Third-party notices

The LabOps Guard Python control-plane source is designed to use the Python standard library. The
repository does not vendor PyTorch or a Python runtime into source control.

The optional Runner image layers LabOps code on the pinned AgentTeams CoPaw Worker image and installs
the pinned CPU build of PyTorch. The directly identified upstream projects use permissive licenses
that are compatible with licensing LabOps Guard source under Apache-2.0:

- AgentTeams: Apache License 2.0 — <https://github.com/agentscope-ai/AgentTeams/blob/main/LICENSE>
- CoPaw/QwenPaw: Apache License 2.0 — <https://github.com/teambition/CoPaw/blob/main/LICENSE>
- Python: PSF License Version 2 — <https://docs.python.org/3/license.html>
- PyTorch: BSD-style license — <https://github.com/pytorch/pytorch/blob/main/LICENSE>

Redistributors of a built Runner image must also retain applicable upstream license and NOTICE files
from the base image, PyTorch wheel, system packages and their transitive dependencies. The source
repository's Apache-2.0 license does not replace those component-specific obligations. A Runner image
tar is therefore published only after image-level SBOM/license review; it is not committed to normal
Git history.

The competition PowerPoint template is an externally supplied submission asset and is not presented
as LabOps Guard source code. OpenTelemetry names appear only as documentation for a future adapter;
no OpenTelemetry SDK or Collector is bundled.

This notice records the direct dependency review performed for the source release. It is informational
and does not replace the complete license text or notices of any distributed dependency.
