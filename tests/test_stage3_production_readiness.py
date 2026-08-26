import json
import tempfile
from pathlib import Path

import pytest

from scripts import stage3_production_readiness as stage3


def test_registry_is_fixed_and_has_no_stage_command_cli_surface():
    assert stage3.STAGE_REGISTRY == ("inventory", "recovery", "acceptance", "rollback")
    source = Path(stage3.__file__).read_text(encoding="utf-8")
    assert "stage-command" not in source
    assert "deploy.ps1" in source and "outside this command" in source


@pytest.mark.parametrize("value", ["production-a", "prod-a", "live-a", "stage3-a", "preprod_A"])
def test_target_guard_rejects_production_like_or_invalid_identifiers(value):
    with pytest.raises(stage3.Stage3Error, match="target"):
        stage3._safe_target(value)


def test_database_and_workdir_guards_are_fail_closed(tmp_path):
    with pytest.raises(stage3.Stage3Error):
        stage3._safe_database("production", production_guard="production")
    with pytest.raises(stage3.Stage3Error):
        stage3._safe_database("stage3_demo", production_guard="isolated")
    with pytest.raises(stage3.Stage3Error):
        stage3._temp_descendant(Path(tempfile.gettempdir()))


def test_recursive_evidence_redaction_excludes_nested_location_and_secret():
    payload = {
        "database_url": "postgresql://person:secret@private.example/db",
        "nested": [{"token": "super-secret"}, "C:\\Users\\private\\source.txt"],
        "image": "registry.internal:5000/private/app:tag",
    }
    cleaned = stage3.sanitize(payload)
    serialized = json.dumps(cleaned)
    assert "super-secret" not in serialized
    assert "private.example" not in serialized
    assert "C:\\Users" not in serialized
    assert "registry.internal" not in serialized


def test_retry_budget_records_two_repairs_then_success():
    budget = stage3.RepairBudget(attempts_per_stage=2, timeout_seconds=600)
    calls = []

    def flaky():
        calls.append(True)
        if len(calls) < 3:
            raise RuntimeError("compose unavailable")
        return {"count": 1}

    result, passed = stage3._record_stage("acceptance", flaky, budget)

    assert passed is True
    assert len(result["attempts"]) == 3
    assert [repair["action"] for repair in budget.repairs] == ["retry-compose", "retry-compose"]


def test_hard_stop_never_retries_or_runs_later_stage():
    budget = stage3.RepairBudget()

    def unsafe():
        raise stage3.Stage3Error("image_identity", "mismatch")

    result, passed = stage3._record_stage("preflight", unsafe, budget)
    assert passed is False
    assert result["failure_class"] == "image_identity"
    assert len(result["attempts"]) == 1
    assert budget.repairs == []


def test_restore_requires_verified_bundle_confirmation_and_inventory(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    restore_root = tmp_path / "restore"
    monkeypatch.setattr(stage3, "_temp_descendant", lambda path: Path(path))
    monkeypatch.setattr(stage3.release_ops, "verify_bundle", lambda _: {"backup_id": "backup-1", "artifacts": [{"path": "x"}]})
    with pytest.raises(stage3.Stage3Error) as rejected:
        stage3._restore_bundle(bundle, "wrong", restore_root, "stage3_demo", "production")
    assert rejected.value.failure_class == "backup_restore"

    monkeypatch.setattr(stage3.release_ops, "restore_bundle", lambda *_args, **_kwargs: restore_root.mkdir())
    with pytest.raises(stage3.Stage3Error) as missing:
        stage3._restore_bundle(bundle, "backup-1", restore_root, "stage3_demo", "production")
    assert missing.value.failure_class == "backup_restore"


def test_restore_reads_inventory_from_the_restored_owned_asset(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    restore_root = tmp_path / "restore"
    monkeypatch.setattr(stage3, "_temp_descendant", lambda path: Path(path))
    monkeypatch.setattr(stage3.release_ops, "verify_bundle", lambda _: {"backup_id": "backup-1", "artifacts": []})

    def restore(*_args, **_kwargs):
        inventory = restore_root / "assets" / "inventory" / "stage3-inventory.json"
        inventory.parent.mkdir(parents=True)
        inventory.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(stage3.release_ops, "restore_bundle", restore)
    monkeypatch.setattr(stage3.release_ops, "validate_restored_inventory", lambda *_args: {"status": "ok"})
    result = stage3._restore_bundle(bundle, "backup-1", restore_root, "stage3_demo", "production")
    assert result["validation"] == "ok"


def test_recovery_connection_reference_is_scoped_and_restored(monkeypatch):
    monkeypatch.setenv("PGHOST", "original")
    with stage3._recovery_connection({"PGHOST": "run-owned", "PGPORT": "1", "PGDATABASE": "db", "PGUSER": "u", "PGPASSFILE": "ref"}):
        assert stage3.os.environ["PGHOST"] == "run-owned"
    assert stage3.os.environ["PGHOST"] == "original"


def test_rollback_requires_distinct_identity_and_is_hard_stop():
    candidate = stage3.ImageIdentity("a" * 40, "sha256:" + "1" * 64, "candidate")
    same = stage3.ImageIdentity("a" * 40, "sha256:" + "1" * 64, "same")
    with pytest.raises(stage3.Stage3Error) as rejected:
        stage3._rollback_rehearsal(candidate, same)
    assert rejected.value.failure_class == "rollback"


def test_fixed_rollback_runner_reuses_the_fixed_acceptance_driver(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(stage3, "_fixed_acceptance_runner", lambda *args: lambda: calls.append(args))
    candidate = stage3.ImageIdentity("a" * 40, "sha256:" + "1" * 64, "candidate")
    rollback = stage3.ImageIdentity("b" * 40, "sha256:" + "2" * 64, "rollback")
    result = stage3._fixed_rollback_runner(tmp_path, "stage3-rollback", "b" * 40, tmp_path, "rollback", tmp_path / "fixture.mp4")(candidate, rollback)
    assert len(calls) == 1
    assert result["post_rollback_health"] == "isolated-preproduction-pass"


def test_fixed_acceptance_runner_refuses_missing_fixture_before_launch(tmp_path):
    with pytest.raises(stage3.Stage3Error) as rejected:
        stage3._fixed_acceptance_runner(tmp_path, "stage3-test", "a" * 40, tmp_path, "candidate", None)
    assert rejected.value.failure_class == "fixture"


def test_complete_injected_rehearsal_writes_sanitized_non_production_evidence(tmp_path, monkeypatch):
    working_dir = tmp_path / "stage3-run"
    restore_root = tmp_path / "restore"
    candidate = stage3.ImageIdentity("a" * 40, "sha256:" + "1" * 64, "candidate-fingerprint")
    rollback = stage3.ImageIdentity("b" * 40, "sha256:" + "2" * 64, "rollback-fingerprint")
    monkeypatch.setattr(stage3, "_temp_descendant", lambda path: Path(path))
    monkeypatch.setattr(stage3, "validate_candidate", lambda *_args: "a" * 40)
    monkeypatch.setattr(stage3, "validate_local_docker", lambda: None)
    images = iter((candidate, rollback))
    monkeypatch.setattr(stage3, "inspect_image", lambda *_args: next(images))
    monkeypatch.setattr(stage3.release_candidate_inventory, "inventory", lambda *_args: {"summary": {"owned": 1}})

    result = stage3.run_rehearsal(
        target_id="stage3-test", candidate_root=tmp_path, commit="a" * 40, working_dir=working_dir,
        candidate_image="candidate", candidate_digest="sha256:" + "1" * 64,
        rollback_image="rollback", rollback_digest="sha256:" + "2" * 64,
        rollback_revision="b" * 40,
        isolated_database="stage3_demo", production_database_guard="production",
        backup_bundle=None, backup_confirmation="", restore_root=restore_root,
        recovery_runner=lambda: {"secret": "do-not-write", "location": "C:\\private\\fixture"},
        acceptance_runner=lambda: {"retrieval": "ready"},
        rollback_runner=lambda *_args: {"health": "ok"},
    )

    evidence = json.loads((working_dir / "stage3-evidence.json").read_text(encoding="utf-8"))
    assert result["release_recommendation"] == "isolated-stage3-pass"
    assert evidence["release_recommendation"] == "isolated-stage3-pass"
    assert "do-not-write" not in json.dumps(evidence)
    assert "C:\\private" not in json.dumps(evidence)
    assert evidence["target_fingerprint"]


def test_cleanup_is_idempotent_when_acceptance_is_environment_blocked(tmp_path, monkeypatch):
    working_dir = tmp_path / "stage3-run"
    candidate = stage3.ImageIdentity("a" * 40, "sha256:" + "1" * 64, "candidate")
    rollback = stage3.ImageIdentity("b" * 40, "sha256:" + "2" * 64, "rollback")
    monkeypatch.setattr(stage3, "_temp_descendant", lambda path: Path(path))
    monkeypatch.setattr(stage3, "validate_candidate", lambda *_args: "a" * 40)
    monkeypatch.setattr(stage3, "validate_local_docker", lambda: None)
    monkeypatch.setattr(stage3, "inspect_image", lambda *_args: candidate if _args[0] == "candidate" else rollback)
    monkeypatch.setattr(stage3.release_candidate_inventory, "inventory", lambda *_args: {"summary": {}})
    result = stage3.run_rehearsal(
        target_id="stage3-test", candidate_root=tmp_path, commit="a" * 40, working_dir=working_dir,
        candidate_image="candidate", candidate_digest="sha256:" + "1" * 64,
        rollback_image="rollback", rollback_digest="sha256:" + "2" * 64,
        rollback_revision="b" * 40,
        isolated_database="stage3_demo", production_database_guard="production", backup_bundle=None,
        backup_confirmation="", restore_root=None, recovery_runner=lambda: {},
        acceptance_runner=lambda: (_ for _ in ()).throw(RuntimeError("network unavailable")),
    )
    assert result["release_recommendation"] == "not-releasable"
    assert result["cleanup"]["outcome"] == "passed"
    assert (working_dir / "stage3-evidence.json").is_file()


def test_cli_writes_gate_failure_evidence_only_to_safe_temporary_workdir(tmp_path, monkeypatch):
    workdir = tmp_path / "stage3-gate-failure"
    fixture = tmp_path / "fixture.mp4"
    fixture.write_bytes(b"fixture")
    monkeypatch.setattr(stage3, "_temp_descendant", lambda path: Path(path))
    exit_code = stage3.main([
        "--non-production", "--target-id", "production", "--candidate-root", str(tmp_path), "--commit", "bad",
        "--working-dir", str(workdir), "--candidate-image", "candidate", "--candidate-digest", "sha256:" + "1" * 64,
        "--rollback-image", "rollback", "--rollback-root", str(tmp_path), "--rollback-digest", "sha256:" + "2" * 64, "--rollback-revision", "b" * 40,
        "--isolated-database", "stage3_demo", "--production-database-guard", "production", "--backup-bundle", str(tmp_path),
        "--backup-confirmation", "x", "--restore-root", str(tmp_path / "restore"), "--recovery-pghost", "127.0.0.1", "--recovery-pgport", "1", "--recovery-pguser", "stage3", "--recovery-pgpassfile", str(tmp_path / "pgpass"),
        "--video-fixture", str(fixture),
    ])
    evidence = json.loads((workdir / "stage3-evidence.json").read_text(encoding="utf-8"))
    assert exit_code == 1
    assert evidence["failure_class"] == "target_identity"
    assert evidence["cleanup"]["outcome"] == "not-started"
