# Stage 3 Offline Qualification Handoff

Date: 2026-08-26 (Asia/Shanghai)

## Current v3 Record

- Bundle: `D:\stage3-offline-release-bundle-20260826-v3`.
- v3 `SHA256SUMS`: `621b2d28a1ef737f8f28a60648bc7fcefe7c7f3f39a58dea10064ad23a1d100c`.
- v2 provenance: `e853de298fd8b487d3eea793943fc6f8dcc87e7a5333d8ea61f65cc1e69ff1ae`.
- Candidate / rollback / tooling: `9798feddb37a9e8ade6ffdda9306df7ff33d8361`,
  `36c2ddaa01b5a2025d6d44980e174d1c2023be10`, and
  `695d94b96a55b02ca88e008963c3d7e83bf81024`.

All v3 image archives remain byte-identical to v2: candidate
`745f7a6fb7647fc33247e86abb99e6d664489893b871ad61d05c2f063208923e`,
rollback `8d654987609e9ec7e7a6accd11bf71b2b56589c13716ed418c20f11042fc1c88`,
postgres `c8ea9511b4cf5b510a737ffb4bd409412e6c3b857c73dde2979ddd410bf99d5f`,
redis `8bf0105c92f562367889d7fc5947321c6313edb01ee6df80683724ccce56dc1a`,
and nginx `a962e86019ff8ed6596fb1c50ff9b06f45de87a6619d09d2f151f9a37ae3149b`.

## Supply-chain Evidence

The v3 verifier now checks each candidate/rollback SBOM, license, and
vulnerability record against the manifest hash, archive SHA256, image digest,
`linux/amd64`, scanner/version, output format, completion state, database
state, and redaction rules. It passed with the v3 checksum above.

Docker Scout v1.23.1 was the only usable local scanner. Both v3 archives were
imported and retained expected IDs/platforms. Archive and post-import image
SBOM commands produced no output before bounded timeout. Syft, Grype, Trivy,
and Grant were absent; two public Syft downloads timed out and Docker Hub pulls
failed due to local credential/network errors. The public Grype DB listing was
reachable, but its newest v5 build is `2026-03-09T00:31:20Z`, outside the
documented 120-hour freshness gate.

## Qualification And Boundaries

**Qualification: `not-qualified`.** The sole blocker is real archive-bound
candidate and rollback SBOMs, license inventories derived from those SBOMs,
and vulnerability snapshots bound to a verifiably current local database.

No clean-room or DR run was repeated. No project cloud or production resource
was accessed; no production deployment, migration, backup/restore, or data
operation was performed. The run-owned Scout temporary index remains because
the local command policy rejected its narrow deletion; no global Docker cleanup
was attempted.
