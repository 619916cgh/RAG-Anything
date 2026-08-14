## Context

The current production build installs all Python dependencies during every application image build. `docling` permits a broad PyTorch range, so an unconstrained resolver can select CUDA-enabled wheels and download several gigabytes of NVIDIA packages on a host that has not established GPU availability. The host has limited capacity and slow external downloads. Previous partial source overlays also proved that deployment must use a complete revision boundary.

## Goals / Non-Goals

**Goals:**

- Produce a reusable CPU-only runtime image with system packages and Python parser dependencies.
- Ensure an ordinary release consumes a complete committed source tree and no dependency installation.
- Make release switching recover automatically to the prior app and Nginx images when validation fails.
- Preserve volumes, `.env`, model caches, uploads, indexes, and database state.

**Non-Goals:**

- GPU acceleration, GPU autodetection, or changes to parser quality.
- Automatic database migrations, data restoration, or off-host backup retention.
- Switching the existing Marker service during the first fast-release rollout; its CPU runtime is built and accepted separately first.

## Decisions

### Pin and assert CPU PyTorch before transitive dependency resolution

The app and Marker base builds SHALL install from a committed Linux/Python 3.11/x86_64 hash-verified CPU dependency lock. The lock SHALL pin compatible CPU `torch` and `torchvision` wheels from a dedicated PyTorch CPU source as well as all resolved transitive packages. It SHALL prefer wheels and explicitly retain hashes for any unavoidable source distribution such as a package without a compatible Linux wheel. The selected package source and versions are updated only through a controlled lock refresh. Both final images SHALL assert that the installed Torch build has no CUDA runtime and that installed distributions do not include `nvidia-`, `cuda-`, or `triton` packages.

Installing ordinary PyPI `torch` was rejected because it permitted CUDA dependency downloads. Relying on runtime GPU detection was rejected because it occurs after image construction and cannot prevent the download.

### Split reusable runtime and source overlays

The Dockerfile SHALL expose a runtime target after system and Python dependencies, before repository source is copied. A versioned immutable tag for the app runtime target becomes the sole parent for thin release app images. The Marker runtime remains separately built and validated because it has incompatible Pillow requirements. A separate thin Nginx release image receives only the committed `frontend/dist` and Nginx configuration.

Rebuilding the full Dockerfile for every source change was rejected because it repeats dependency installation. Copying selected files into an old image was rejected because it can create incompatible imports.

### Commit-only fast release with a change gate

`deploy.ps1 -Commit <SHA>` SHALL construct its staging area from Git, never the working tree. It SHALL reject a candidate that changes dependency files, Dockerfiles, Compose, migrations, or release tooling relative to the configured runtime-base revision. The initial base-image release is a separate controlled operation.

Using an uncommitted archive was rejected because it is not reproducible. Allowing schema changes in fast release was rejected because they require backup and migration acceptance.

### Remote verification and rollback

The remote release routine SHALL acquire a host release lock, verify the archive checksum, build candidate overlays, run an application import smoke test, preserve immutable image IDs under release-specific rollback tags, switch only `app` and then `nginx` with `--no-deps --no-build --force-recreate`, and poll direct and reverse-proxy health checks plus zero restart count over a bounded stability window. A `trap` SHALL restore both preserved images on every post-switch failure and verify rollback health. It SHALL never invoke `migrate` or automatic image pruning.

### Verify parser capability and model-cache policy before freezing a base

The base-image gate SHALL check CPU Torch/Torchvision, Docling conversion with a fixture, MinerU availability, CPU-mode Paddle initialization where supported, OpenDataLoader and Java 17, FFmpeg, and LibreOffice. Parser model artifacts remain in versioned persistent host caches rather than in the base image; the gate SHALL report cache misses as a prewarming requirement and the fast release path SHALL not download model assets.

## Risks / Trade-offs

- [The CPU wheel index is unavailable from the deployment host] -> Fail the base build before switching containers; do not fall back to a CUDA wheel.
- [CPU parsing is slower than GPU parsing] -> The current host does not have confirmed usable GPU capability; prioritize predictable capacity and deployability. A future GPU profile is a separate change.
- [Parser models download after a seemingly successful release] -> Keep models in versioned persistent caches, validate cache availability during base acceptance, and prohibit fast-release downloads.
- [The current production image is not the new base] -> Fast release remains disabled until the new base is built, tagged, smoke-tested, and explicitly configured.
- [A release can fail after app replacement] -> Preserve both app and Nginx image tags and revert without touching volumes or migrations.
- [Concurrent releases consume host capacity or overwrite a rollback point] -> Hold a host-local `flock`, preflight free capacity, and reject concurrent build/release activity without automatic cleanup.

## Migration Plan

1. Verify the production host GPU capability and the configured CPU package index, then build the app and Marker CPU runtime images with mirrors.
2. Smoke-test the runtime images, record their image IDs, tag them immutably, and retain the current running images for rollback.
3. Configure the local ignored SSH settings and run the commit-based fast release for a source-only commit.
4. On any failed import or health check, restore the previous app and Nginx image tags; do not run a database migration.

## Open Questions

- The exact compatible CPU wheel set and the deployment host's access to the PyTorch CPU index require a controlled Linux lock refresh and read-only host checks before the base build.
