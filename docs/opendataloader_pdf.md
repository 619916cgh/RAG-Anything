# OpenDataLoader PDF Backend

`opendataloader` is an opt-in PDF override. It never replaces the global
parser and it does not parse non-PDF files.

Marker is not exposed as a project extra: Marker requires `Pillow<11`, whereas
the default MinerU runtime requires `Pillow>=11`. It must run in a separately
designed worker/container and cannot be combined with MinerU, `all`, or
OpenDataLoader. The old advertised Marker extra is intentionally absent rather
than leaving an install command that cannot resolve.

## Prerequisites

- Install `raganything[opendataloader]`; the dependency is pinned to
  `opendataloader-pdf==2.5.0`.
- Provide Java 17 or newer through `JAVA_HOME` or `PATH`.
- Enable it only in an isolated worker/staging deployment with
  `PDF_PARSER=opendataloader`. Leave `PARSER` set to an existing general
  parser such as `mineru`.

The adapter uses the official Python SDK in a supervised child process once
per PDF page. It uses local fast mode only; hybrid, remote URLs, fallback, and
disabled content-safety options are not supported. A page with missing,
ambiguous, invalid, or out-of-root artifacts fails the whole upload before
cache or ingestion.

## Resource Controls

`ODL_TIMEOUT` limits one document, `ODL_PAGE_TIMEOUT` limits one controlled
runner, `ODL_JAVA_HEAP` accepts only values such as `-Xmx2g`, and
`ODL_CONCURRENCY` defaults to one shared conversion across workers using the
same `WORKING_DIR`. `ODL_MAX_PAGES` and `ODL_MAX_BYTES` reject inputs before
Java starts. `ODL_MAX_OUTPUT_BYTES` caps retained JSON, Markdown, images, and
provenance output. Timeouts terminate the runner
process tree on Windows and Linux containers.

Parser artifacts and provenance sidecars remain under `ODL_ARTIFACT_ROOT`, an
explicit dedicated artifact root that is separate from the normal parser output
root. `PDF_PARSER=opendataloader` refuses to start unless this is an existing,
absolute path. This prevents an artifact registry from authorizing deletion in
a shared parser tree.
They contain relative references and hashes, never a public provenance API or
document text in telemetry. Delete/re-ingest through the supported document or
knowledge-base lifecycle; do not remove individual sidecars manually.

## Artifact lifecycle volume

Automatic cleanup is deliberately opt-in and is supported only with
`ODL_ARTIFACT_ROOT=/odl-artifacts` and `ODL_ARTIFACT_CLEANUP_MODE=linux-volume`
in a dedicated local Linux,
Docker-named-volume, or WSL ext4 volume. The parser output root must be a
server-provisioned real directory on that volume, not a Windows bind mount,
SMB/NFS/FUSE share, upload directory, or a shared parser-output parent. The
lifecycle registry binds a document owner to one strict parser run and deletes
only that registered run through descriptor-relative no-follow traversal.
At runtime the cleanup gate rejects overlay, 9p/Windows mounts, SMB/NFS,
FUSE and virtiofs, and requires the root to be private (`0700`) and owned by
the worker service identity. The cleanup opener verifies the same root inode
after opening it, so a replaced root fails closed rather than authorizing a
second path.

On Windows and any runtime without the required descriptor operations,
automatic retry overwrite, document deletion cleanup, KB cleanup, and
retention cleanup fail closed. Parsing remains available, but artifacts are
retained for an administrator-controlled cleanup process; callers must report
cleanup as pending rather than claiming it completed.

## Isolated Staging Procedure

Use a dedicated worker deployment, `WORKING_DIR`, knowledge base, and storage
namespace. Do not point this parser at a production knowledge base during the
evaluation. Start with `ODL_CONCURRENCY=1` and the SDK thread cap of one, then
set `ODL_MAX_PAGES`, `ODL_MAX_BYTES`, `ODL_JAVA_HEAP`, `ODL_TIMEOUT`, and
`ODL_PAGE_TIMEOUT` from measured staging capacity. These values are deployment
limits, not application defaults.

For a PDF-only canary, leave the general routing unchanged and configure the
worker as follows:

```text
PARSER=mineru
PDF_PARSER=opendataloader
ODL_CONCURRENCY=1
```

Run the approved external corpus in this isolated environment and retain the
coverage, quality, injection-defense, P50/P95, and peak-memory report with the
release evidence. A task failing coverage, preflight, resource, timeout,
conversion, or artifact validation must remain failed; there is no automatic
retry through MinerU, Docling, hybrid, or remote parsing.

## Container

The normal `docker-compose.yml` remains the default image and does not install
Java or OpenDataLoader. On a Linux Docker host, enable the isolated runtime
explicitly with the override below. It builds the `opendataloader` target,
mounts only the named `raganything_odl_artifacts` volume at
`/odl-artifacts`, creates it with mode `0700`, and leaves `/app/output` as the
ordinary parser-output bind mount.

```bash
docker compose -f docker-compose.yml -f docker-compose.opendataloader.yml up --build -d
```

Do not replace this named volume with a Windows bind mount, a shared network
filesystem, or the normal `/app/output` directory. The parser fails closed if
the runtime cannot prove the mounted root is safe for cleanup.

The default image has no Java or OpenDataLoader dependency. Build the opt-in
image with `docker build --target opendataloader -t raganything:opendataloader .`.
It verifies Java and the pinned SDK while building.

## Rollback

Clear or restore `PDF_PARSER`, restart document workers, and new PDFs return to
the global parser. Existing OpenDataLoader documents are unchanged; retain the
source and use supported deletion followed by re-ingestion when rebuilt content
is required.

## Distribution Gate

Before distributing the opt-in wheel, JAR bundle, or image, generate an SBOM
from the actual final artifacts; record wheel/JAR hashes, image digest, notices,
corresponding-source references, and version reconciliation. `NOASSERTION`,
unresolved licenses, missing notices, or the veraPDF notice/version discrepancy
block distribution. This gate covers this integration only and requires written
license-owner approval.

The executable gate is `scripts/opendataloader_release_gate.py`, with generated
notices under `OSS_NOTICES/opendataloader-pdf/` and approval/reconciliation
records under `release-evidence/opendataloader-pdf/`. Templates are deliberately
non-approving and cannot pass the gate.
