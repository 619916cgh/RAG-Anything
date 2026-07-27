"""Focused security tests for the OpenDataLoader artifact lifecycle boundary."""

from __future__ import annotations

import hashlib
import sqlite3

import pytest

import raganything.services.odl_artifact_lifecycle as lifecycle_module
from raganything.services.odl_artifact_lifecycle import (
    ArtifactLifecycleCapabilityError,
    ArtifactOwner,
    ArtifactRegistryConflict,
    OpenDataLoaderArtifactLifecycle,
    UnsafeArtifactPath,
    validate_run_relative_path,
)


_SIDECAR_HASH = hashlib.sha256(b"{}").hexdigest()


def _make_run(root, name="report_a1b2c3d4/run-12345678"):
    run = root.joinpath(*name.split("/"))
    run.mkdir(parents=True)
    (run / "provenance.json").write_text("{}", encoding="utf-8")
    return name, run


def _register(service, owner, run_relpath, *, expected_generation=None):
    return service.register(
        owner,
        run_relpath=run_relpath,
        sidecar_relpath=f"{run_relpath}/provenance.json",
        sidecar_sha256=_SIDECAR_HASH,
        expected_generation=expected_generation,
    )


def test_registry_requires_existing_strict_run_and_cas_generation(tmp_path):
    service = OpenDataLoaderArtifactLifecycle(tmp_path)
    owner = ArtifactOwner("kb-alpha", "doc-1")
    run_relpath, _ = _make_run(tmp_path)

    record = _register(service, owner, run_relpath)

    assert record.generation == 1
    assert record.state == "active"
    assert service.get(owner) == record
    with pytest.raises(ArtifactRegistryConflict, match="generation"):
        _register(service, owner, run_relpath, expected_generation=2)
    with pytest.raises(ArtifactRegistryConflict, match="different owner"):
        _register(service, ArtifactOwner("kb-alpha", "doc-2"), run_relpath)


@pytest.mark.parametrize(
    "run_relpath",
    [
        "../report_a1b2c3d4/run-12345678",
        "/report_a1b2c3d4/run-12345678",
        "report_a1b2c3d4/run-12345678/extra",
        "report_a1b2c3d4\\run-12345678",
        "report_a1b2c3d4/run-123",
        "report_name/run-12345678",
    ],
)
def test_strict_run_paths_reject_traversal_legacy_and_windows_forms(run_relpath):
    with pytest.raises(UnsafeArtifactPath):
        validate_run_relative_path(run_relpath)


def test_strict_run_path_retains_safe_unicode_stem_for_chinese_documents():
    assert (
        validate_run_relative_path("中文合同_a1b2c3d4/run-12345678")
        == "中文合同_a1b2c3d4/run-12345678"
    )


def test_windows_or_missing_fd_primitives_fail_closed_for_deletion(tmp_path, monkeypatch):
    service = OpenDataLoaderArtifactLifecycle(tmp_path)
    owner = ArtifactOwner("kb-alpha", "doc-1")
    run_relpath, run = _make_run(tmp_path)
    registered = _register(service, owner, run_relpath)
    monkeypatch.setattr(lifecycle_module, "_is_linux_fd_safe", lambda: False)

    with pytest.raises(ArtifactLifecycleCapabilityError, match="Linux/Docker/WSL"):
        service.delete(owner, expected_generation=registered.generation, worker_exited=True)

    assert run.exists()
    assert service.get(owner).state == "active"


def test_controlled_volume_mode_rejects_nonlocal_mount_and_insecure_permissions(
    tmp_path, monkeypatch
):
    service = OpenDataLoaderArtifactLifecycle(tmp_path)
    monkeypatch.setattr(lifecycle_module, "_is_linux_fd_safe", lambda: True)
    monkeypatch.setenv("ODL_ARTIFACT_CLEANUP_MODE", "linux-volume")
    monkeypatch.setattr(lifecycle_module, "_linux_mount_filesystem", lambda _path: "nfs")

    with pytest.raises(ArtifactLifecycleCapabilityError, match="not filesystem type 'nfs'"):
        service._require_destructive_capability()

    monkeypatch.setattr(lifecycle_module, "_linux_mount_filesystem", lambda _path: "ext4")
    real_stat = tmp_path.stat()
    monkeypatch.setattr(
        lifecycle_module.Path,
        "stat",
        lambda _self: type(
            "Stat", (), {"st_mode": real_stat.st_mode | 0o020, "st_uid": 1}
        )(),
    )
    with pytest.raises(ArtifactLifecycleCapabilityError, match="writable by group"):
        service._require_destructive_capability()


def test_register_hashes_the_actual_direct_child_sidecar_and_lists_only_its_kb(tmp_path):
    service = OpenDataLoaderArtifactLifecycle(tmp_path)
    first_owner = ArtifactOwner("kb-alpha", "doc-1")
    second_owner = ArtifactOwner("kb-alpha", "doc-2")
    other_kb_owner = ArtifactOwner("kb-beta", "doc-3")
    first_run, _ = _make_run(tmp_path)
    second_run, _ = _make_run(tmp_path, "other_c0ffee12/run-87654321")
    other_run, _ = _make_run(tmp_path, "third_deadbeef/run-11223344")
    _register(service, first_owner, first_run)
    _register(service, second_owner, second_run)
    _register(service, other_kb_owner, other_run)

    assert [record.owner for record in service.list_records_for_kb("kb-alpha")] == [
        first_owner,
        second_owner,
    ]
    with pytest.raises(UnsafeArtifactPath, match="hash"):
        service.register(
            ArtifactOwner("kb-alpha", "doc-bad"),
            run_relpath="third_deadbeef/run-11223344",
            sidecar_relpath="third_deadbeef/run-11223344/provenance.json",
            sidecar_sha256="b" * 64,
        )
    with pytest.raises(UnsafeArtifactPath, match="direct child"):
        service.register(
            ArtifactOwner("kb-alpha", "doc-external"),
            run_relpath=first_run,
            sidecar_relpath="unrelated/provenance.json",
            sidecar_sha256=_SIDECAR_HASH,
        )


def test_registry_retention_purges_only_records_already_marked_deleted(tmp_path):
    service = OpenDataLoaderArtifactLifecycle(tmp_path)
    owner = ArtifactOwner("kb-alpha", "doc-1")
    run_relpath, _ = _make_run(tmp_path)
    _register(service, owner, run_relpath)

    with sqlite3.connect(tmp_path / ".odl-artifact-registry.sqlite3") as connection:
        connection.execute(
            "UPDATE odl_artifact_runs SET state='deleted' WHERE kb_id=? AND doc_id=?",
            (owner.kb_id, owner.doc_id),
        )

    assert service.purge_deleted_registry_records(kb_id="kb-alpha") == 1
    assert service.get(owner) is None


@pytest.mark.skipif(
    not OpenDataLoaderArtifactLifecycle.destructive_operations_supported(),
    reason="secure recursive deletion is deliberately Linux/Docker/WSL-only",
)
def test_linux_fd_relative_delete_tombstones_then_removes_only_registered_run(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ODL_ARTIFACT_CLEANUP_MODE", "linux-volume")
    service = OpenDataLoaderArtifactLifecycle(tmp_path)
    owner = ArtifactOwner("kb-alpha", "doc-1")
    run_relpath, run = _make_run(tmp_path)
    nested = run / "nested"
    nested.mkdir()
    (nested / "raw.json").write_text("{}", encoding="utf-8")
    untouched = tmp_path / "unrelated"
    untouched.mkdir()
    (untouched / "keep.txt").write_text("keep", encoding="utf-8")
    registered = _register(service, owner, run_relpath)

    deleted = service.delete(owner, expected_generation=registered.generation, worker_exited=True)

    assert deleted.state == "deleted"
    assert deleted.tombstone_relpath
    assert not run.exists()
    assert (untouched / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert service.get(owner) == deleted


@pytest.mark.skipif(
    not OpenDataLoaderArtifactLifecycle.destructive_operations_supported(),
    reason="secure recursive deletion is deliberately Linux/Docker/WSL-only",
)
def test_linux_symlink_in_tombstone_fails_closed_and_is_recoverable(tmp_path, monkeypatch):
    monkeypatch.setenv("ODL_ARTIFACT_CLEANUP_MODE", "linux-volume")
    service = OpenDataLoaderArtifactLifecycle(tmp_path)
    owner = ArtifactOwner("kb-alpha", "doc-1")
    run_relpath, run = _make_run(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("do-not-delete", encoding="utf-8")
    (run / "escape").symlink_to(outside)
    registered = _register(service, owner, run_relpath)

    with pytest.raises(UnsafeArtifactPath, match="symlink"):
        service.delete(owner, expected_generation=registered.generation, worker_exited=True)

    state = service.get(owner)
    assert state.state == "deleting"
    assert outside.read_text(encoding="utf-8") == "do-not-delete"
    assert not run.exists()


@pytest.mark.skipif(
    not OpenDataLoaderArtifactLifecycle.destructive_operations_supported(),
    reason="secure recursive deletion is deliberately Linux/Docker/WSL-only",
)
def test_recovery_resumes_persisted_tombstone_after_pre_rename_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("ODL_ARTIFACT_CLEANUP_MODE", "linux-volume")
    service = OpenDataLoaderArtifactLifecycle(tmp_path)
    owner = ArtifactOwner("kb-alpha", "doc-1")
    run_relpath, run = _make_run(tmp_path)
    registered = _register(service, owner, run_relpath)
    # Simulate a process crash after persisting state='deleting' and before the
    # rename.  Recovery must use the stored tombstone name, not reconstruct one.
    with service._owner_lock(owner):
        pending = service._transition_to_deleting(owner, registered.generation)

    recovered = service.recover_deletions(worker_exited=lambda checked: checked == owner)

    assert len(recovered) == 1
    assert recovered[0].owner == pending.owner
    assert recovered[0].generation == pending.generation
    assert recovered[0].state == "deleted"
    assert not run.exists()


@pytest.mark.skipif(
    not OpenDataLoaderArtifactLifecycle.destructive_operations_supported(),
    reason="secure recursive deletion is deliberately Linux/Docker/WSL-only",
)
def test_delete_kb_uses_registry_owners_not_a_recursive_kb_path(tmp_path, monkeypatch):
    monkeypatch.setenv("ODL_ARTIFACT_CLEANUP_MODE", "linux-volume")
    service = OpenDataLoaderArtifactLifecycle(tmp_path)
    first_owner = ArtifactOwner("kb-alpha", "doc-1")
    second_owner = ArtifactOwner("kb-alpha", "doc-2")
    first_run, first_path = _make_run(tmp_path)
    second_run, second_path = _make_run(tmp_path, "other_c0ffee12/run-87654321")
    first = _register(service, first_owner, first_run)
    second = _register(service, second_owner, second_run)
    unrelated = tmp_path / "kb-alpha-unregistered"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("keep", encoding="utf-8")

    deleted = service.delete_kb("kb-alpha", worker_exited=lambda _owner: True)

    assert {(record.owner, record.generation) for record in deleted} == {
        (first_owner, first.generation),
        (second_owner, second.generation),
    }
    assert all(record.state == "deleted" for record in deleted)
    assert not first_path.exists()
    assert not second_path.exists()
    assert (unrelated / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert service.purge_deleted_registry_records(kb_id="kb-alpha") == 2


def test_registry_does_not_trust_metadata_path_as_deletion_authority(tmp_path):
    service = OpenDataLoaderArtifactLifecycle(tmp_path)
    owner = ArtifactOwner("kb-alpha", "doc-1")
    with pytest.raises(UnsafeArtifactPath, match="does not exist"):
        service.register(
            owner,
            run_relpath="report_a1b2c3d4/run-12345678",
            sidecar_relpath="report_a1b2c3d4/run-12345678/provenance.json",
            sidecar_sha256=_SIDECAR_HASH,
        )

    with sqlite3.connect(tmp_path / ".odl-artifact-registry.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM odl_artifact_runs").fetchone()[0] == 0


@pytest.mark.skipif(not hasattr(__import__("os"), "symlink"), reason="symlink unsupported")
def test_registry_rejects_a_symlinked_ancestor_of_the_controlled_root(tmp_path):
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    try:
        linked_parent.symlink_to(real_parent, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    root = linked_parent / "artifacts"
    # Creating through a symlink is allowed by the OS but never by this
    # lifecycle boundary.
    (real_parent / "artifacts").mkdir()

    with pytest.raises(UnsafeArtifactPath, match="ancestors"):
        OpenDataLoaderArtifactLifecycle(root)


def test_document_cleanup_reports_pending_instead_of_prefix_deleting_odl_run(
    tmp_path, monkeypatch
):
    """The Windows/fail-closed route must retain a registered ODL run."""
    from raganything.routers import knowledge

    monkeypatch.chdir(tmp_path)
    output_root = tmp_path / "output_demo"
    output_root.mkdir()
    artifact_root = tmp_path / "odl-artifacts"
    artifact_root.mkdir()
    monkeypatch.setenv("ODL_ARTIFACT_ROOT", str(artifact_root))
    service = OpenDataLoaderArtifactLifecycle(artifact_root)
    owner = ArtifactOwner("demo", "doc-1")
    run_relpath, run = _make_run(artifact_root)
    registered = _register(service, owner, run_relpath)
    monkeypatch.setattr(lifecycle_module, "_is_linux_fd_safe", lambda: False)

    result = knowledge._cleanup_document_files("demo", "report.pdf", owner.doc_id)

    assert result == {"artifact_cleanup_pending": True}
    assert run.is_dir()
    assert service.get(owner) == registered


def test_document_cleanup_never_prefix_deletes_a_legacy_odl_root_without_record(
    tmp_path, monkeypatch
):
    """A missing registry row is not permission to remove an ODL-looking run."""
    from raganything.routers import knowledge

    monkeypatch.chdir(tmp_path)
    output_root = tmp_path / "output_demo"
    output_root.mkdir()
    service = OpenDataLoaderArtifactLifecycle(output_root)
    _run_relpath, run = _make_run(output_root, "report_a1b2c3d4/run-12345678")

    result = knowledge._cleanup_document_files("demo", "report.pdf", "missing-doc")

    assert result == {"artifact_cleanup_pending": True}
    assert run.is_dir()
    assert service.get(ArtifactOwner("demo", "missing-doc")) is None


def test_configured_artifact_root_must_be_absolute_and_never_derived_from_output(
    monkeypatch, tmp_path
):
    from raganything.services.odl_artifact_lifecycle import configured_odl_artifact_root

    monkeypatch.delenv("ODL_ARTIFACT_ROOT", raising=False)
    assert configured_odl_artifact_root() is None
    monkeypatch.setenv("ODL_ARTIFACT_ROOT", "relative-output")
    with pytest.raises(UnsafeArtifactPath, match="absolute"):
        configured_odl_artifact_root()
    absolute_root = tmp_path / "dedicated"
    monkeypatch.setenv("ODL_ARTIFACT_ROOT", str(absolute_root))
    assert configured_odl_artifact_root() == absolute_root


def test_document_cleanup_invalidates_only_matching_cached_doc_id(tmp_path, monkeypatch):
    from raganything.routers import knowledge

    monkeypatch.chdir(tmp_path)
    storage = tmp_path / "storage"
    storage.mkdir()
    cache_path = storage / "kv_store_parse_cache.json"
    cache_path.write_text(
        __import__("json").dumps(
            {
                "key-for-owned-doc": {"doc_id": "doc-owned"},
                "key-for-other-doc": {"doc_id": "doc-other"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(knowledge, "kb_dir", lambda _kb: storage)

    result = knowledge._cleanup_document_files("demo", "report.pdf", "doc-owned")

    assert result == {"artifact_cleanup_pending": False}
    cached = __import__("json").loads(cache_path.read_text(encoding="utf-8"))
    assert cached == {"key-for-other-doc": {"doc_id": "doc-other"}}
