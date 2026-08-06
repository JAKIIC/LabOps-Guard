# Third-party notices

The LabOps Guard Python control-plane source is designed to use the Python standard library. The
repository does not vendor PyTorch or a Python runtime into source control.

The optional Runner image is built from an official Python container base and installs the pinned
CPU build of PyTorch. Redistributors of built images must review and comply with the licenses and
notices shipped by those upstream components and their transitive dependencies:

- Python: <https://docs.python.org/3/license.html>
- PyTorch: <https://github.com/pytorch/pytorch/blob/main/LICENSE>
- Debian packages used by the Python slim image: notices are included by their packages/base image.

The competition PowerPoint template is an externally supplied submission asset and is not presented
as LabOps Guard source code. OpenTelemetry names appear only as documentation for a future adapter;
no OpenTelemetry SDK or Collector is bundled.

This notice is informational and does not replace the license text of any distributed dependency.
