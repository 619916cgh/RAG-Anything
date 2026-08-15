## 1. CPU Runtime Foundation

- [x] 1.1 Add a committed Linux/Python 3.11/x86_64 hash-verified CPU dependency lock with compatible CPU Torch and Torchvision wheels.
- [x] 1.2 Split the app Dockerfile into reusable dependency-only runtime targets and thin source targets, and apply the CPU runtime policy to the Marker image.
- [x] 1.3 Add a runtime acceptance script that rejects CUDA packages and verifies required parser executables/imports and model-cache policy.
- [x] 1.4 Add focused static and script tests for CPU lock and Docker runtime-target invariants.

## 2. Commit Fast Release

- [x] 2.1 Add thin app and Nginx release Dockerfiles that consume only an immutable runtime base plus a complete staged release payload.
- [x] 2.2 Add ignored local deployment configuration with a tracked example and SSH-key bootstrap guidance that does not contain credentials.
- [x] 2.3 Implement commit-only PowerShell staging, eligibility checks, archive hashing, remote upload, and sanitized manifest generation.
- [x] 2.4 Implement the remote lock, capacity preflight, import smoke, app-first/Nginx-second switch, health stability window, and rollback trap.
- [x] 2.5 Add focused tests for release eligibility, payload boundaries, remote service allowlist, and rollback behavior.

## 3. Verification and Handoff

- [x] 3.1 Run OpenSpec strict validation, focused tests, and static checks.
- [ ] 3.2 Perform controlled production GPU/index preflight and CPU runtime build acceptance after SSH-key access is available or through an operator-executed command.
- [x] 3.3 Update project summary with implemented behavior, validation evidence, and remaining production acceptance boundaries.
