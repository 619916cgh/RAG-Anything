# Commit Fast Release

The fast-release path deploys one complete Git commit on top of prevalidated,
immutable app and Nginx runtime image IDs. It never packages the working tree,
runs migrations, prunes Docker data, or changes persistent volumes.

## One-time local setup

1. Copy `deploy.config.example.psd1` to the ignored
   `deploy.config.psd1` and replace every placeholder.
2. Record the accepted runtime IDs with `docker image inspect`; a mutable tag
   without its expected `sha256:` ID is rejected.
   For the accepted app CPU runtime currently on the host, use tag
   `raganything-app-runtime:cpu-de7a773` and image ID
   `sha256:ade5bf64a9a9c7d6046a53d69aaa1895ab1723067b0d8da2f9a06d497ba333ca`.
   Configure a separate immutable Nginx base tag and its inspected ID before
   enabling fast release.
3. Generate a dedicated SSH key in PowerShell:

   ```powershell
   ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\rag_anything_deploy" -C "rag-anything-deploy"
   ```

4. Add only the `.pub` key to the deployment account's `authorized_keys` and
   verify non-interactive access:

   ```powershell
   ssh -o BatchMode=yes -i "$env:USERPROFILE\.ssh\rag_anything_deploy" deploy-user@example-host true
   ```

Do not commit the private key, passwords, `.env`, tokens, or the populated
configuration file.

## Release

Use a full 40-character commit SHA:

```powershell
.\deploy.ps1 -Commit 0123456789abcdef0123456789abcdef01234567
```

The command verifies eligibility against `EligibilityBaselineCommit`, exports
that exact revision with `git archive`, builds `frontend/dist` inside the
staging directory, validates payload boundaries, uploads a SHA-256-verified
archive, and invokes the remote locked rollout. The remote routine builds app
and Nginx overlays, runs import smoke checks, switches app before Nginx, and
restores both previous image IDs if a post-switch check fails.

Changes to dependencies, Docker/Compose, migrations, model manifests, frontend
lock/runtime inputs, or release tooling require a controlled base or migration
release and are rejected before contacting the server.
