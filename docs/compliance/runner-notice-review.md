# Runner NOTICE review

Review date: 2026-08-09

## Repository scope

`THIRD_PARTY_NOTICES.md` correctly distinguishes the Apache-2.0 LabOps Guard source from the optional
Runner image. The repository does not vendor Python, PyTorch, Debian packages, or a Runner tar.

## Image scope

The installed PyTorch distribution contains its own LICENSE and NOTICE material. Python and each
Debian package also retain component-specific license/copyright files in the image. Those files are
not replaced by the repository's Apache-2.0 license or by this review.

Before any image distribution, build a machine-readable and human-readable notice bundle that:

1. names the exact image digest and build date;
2. includes the base-image license and NOTICE files;
3. includes Python and PyTorch license/NOTICE files;
4. includes applicable notices for every redistributed Debian and Python component;
5. documents how corresponding source is supplied for copyleft components; and
6. is verified against the final SBOM after the last image rebuild.

## Current decision

NOTICE coverage is sufficient for the public source repository, but incomplete for Runner image
redistribution. The current `v1.0-rc1` remains a source-only candidate; the earlier `v0.3.0-rc1`
label is historical. No image archive is part of the competition submission.
