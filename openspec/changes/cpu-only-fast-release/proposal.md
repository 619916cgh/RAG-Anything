## Why

The production host has limited disk capacity and low dependency-download bandwidth. Its current unconstrained PyTorch resolution downloads CUDA packages even when no GPU is available, making a routine release consume hours and several gigabytes. Previous file-by-file deployments also created inconsistent Python imports.

## What Changes

- Define CPU-only application and Marker base images that install their parser runtimes, Java/LibreOffice where required, and CPU-only PyTorch once.
- Add a hash-verified Linux/Python 3.11/x86_64 CPU dependency lock and verify that the final images contain no NVIDIA, CUDA, or Triton runtime packages.
- Add a commit-only fast release path that stages a complete Git revision, builds thin application and Nginx overlays, validates imports and health endpoints, and rolls back on a failed switch.
- Keep migrations outside the fast release path; releases that change migration or base-image inputs must be rejected with an explicit reason.
- Add local SSH deployment configuration examples and PowerShell automation without committing credentials, including source, base-image, and resulting-image provenance.

## Capabilities

### New Capabilities

- `cpu-only-runtime-image`: Build and validate reusable CPU-only app and Marker parser runtime images without CUDA dependencies.
- `commit-fast-release`: Deploy an explicit complete Git revision through verified staging, smoke checks, controlled switching, and rollback.

### Modified Capabilities

- None.

## Impact

- Affected code: `Dockerfile`, Docker build configuration, new deployment Dockerfiles and PowerShell/shell release scripts, and focused release tests.
- Affected systems: production Docker host and the local Windows release workstation.
- No application API, database schema, migration execution, persistent volume, or runtime data behavior changes are included.
