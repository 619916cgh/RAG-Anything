## ADDED Requirements

### Requirement: Hash-verified CPU runtime dependency resolution
The app and Marker runtime image builds SHALL install from a committed Linux/Python 3.11/x86_64 dependency lock using hash verification. The lock MUST pin compatible CPU-only PyTorch and Torchvision wheels from a configured CPU package source and all resolved transitive dependencies; it MUST retain hashes for an explicitly unavoidable source distribution that lacks a compatible Linux wheel. A build MUST fail if a locked wheel cannot be installed and MUST NOT silently fall back to a CUDA-enabled PyTorch package.

#### Scenario: CPU dependency build succeeds
- **WHEN** the configured CPU package source provides every wheel in the committed lock
- **THEN** each relevant runtime image installs the locked CPU PyTorch and Torchvision packages with their verified hashes.

#### Scenario: CPU dependency build cannot resolve
- **WHEN** the configured CPU package source cannot provide a requested locked wheel
- **THEN** the build fails before a release image is created or a running container is replaced.

### Requirement: Reusable runtime target
The Dockerfile SHALL expose a target containing system packages and Python runtime dependencies but no application source or built frontend assets. Source-overlay release images MUST use an explicit immutable tag of this target.

#### Scenario: Source-only release
- **WHEN** a candidate changes only permitted application or frontend source files
- **THEN** its release image build does not execute APT or Python dependency installation.

### Requirement: CUDA exclusion verification
The app and Marker runtime image builds MUST fail unless their installed Python distributions contain no `nvidia-` or `triton` package and `torch.version.cuda` is empty or null.

#### Scenario: A CUDA package is present
- **WHEN** a runtime image contains a CUDA-enabled Torch build or an NVIDIA or Triton distribution
- **THEN** its build fails before it can be tagged as a reusable runtime image.

### Requirement: Parser and cache acceptance gate
Before a runtime image receives an immutable release tag, the acceptance gate MUST verify Docling fixture conversion, MinerU availability, CPU-mode Paddle initialization when required by its installed version, OpenDataLoader with Java 17, FFmpeg, and LibreOffice. The gate MUST report the configured versioned parser-model cache locations and MUST fail if it needs to download model assets during fast release.

#### Scenario: Runtime parser capability is missing
- **WHEN** a required parser import, executable probe, or fixture conversion fails
- **THEN** the runtime image is not tagged as a reusable release base.
