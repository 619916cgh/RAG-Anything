import json
from pathlib import Path

from scripts import stage3_offline_preflight as preflight
from scripts import stage3_offline_release_dry_run as dry_run


def _bundle(tmp_path):
    bundle = tmp_path / "bundle"
    images = bundle / "images"
    requirements = bundle / "requirements"
    images.mkdir(parents=True)
    requirements.mkdir()
    for archive in preflight.REQUIRED_ARCHIVES:
        (images / archive).write_bytes(b"archive")
    (requirements / "secret-references.txt").write_text("\n".join(sorted(preflight.REQUIRED_SECRETS)) + "\n", encoding="utf-8")
    (requirements / "host-prerequisites.txt").write_text("names only\n", encoding="utf-8")
    (bundle / "runbook.md").write_text("offline runbook\n", encoding="utf-8")
    return bundle


def _host(**overrides):
    values = dict(system="Linux", machine="x86_64", docker_engine="27.0", compose="v2.29.0", cpu_count=4,
                  memory_bytes=preflight.MIN_MEMORY_BYTES, disk_free_bytes=preflight.MIN_DISK_BYTES,
                  docker_data_free_bytes=preflight.MIN_DISK_BYTES, occupied_ports=[])
    values.update(overrides)
    return preflight.observation_from_fixture({"host": values})


def test_preflight_fixture_passes_and_defers_external_work(tmp_path):
    result = preflight.preflight(_bundle(tmp_path), observation=_host())
    assert result["status"] == "passed"
    assert {item["code"] for item in result["checks"] if item["status"] == "pending-external"} == {
        "PREFLIGHT_DNS", "PREFLIGHT_TLS", "PREFLIGHT_PROVIDER", "PREFLIGHT_BACKUP_CUSTODY"}


def test_preflight_rejects_windows_low_docker_space_and_port_conflict(tmp_path):
    result = preflight.preflight(_bundle(tmp_path), observation=_host(system="Windows", docker_data_free_bytes=1, occupied_ports=[443]))
    codes = {item["code"] for item in result["checks"] if item["status"] == "failed"}
    assert result["status"] == "failed"
    assert {"PREFLIGHT_PLATFORM", "PREFLIGHT_DOCKER_DATA_DISK", "PREFLIGHT_PORTS"}.issubset(codes)


def test_preflight_checks_operator_selected_port_and_every_service_resource_plan(tmp_path):
    result = preflight.preflight(_bundle(tmp_path), observation=_host(occupied_ports=[18080]), ports=[18080])
    codes = {item["code"] for item in result["checks"] if item["status"] == "failed"}
    assert "PREFLIGHT_PORTS" in codes
    assert {"PREFLIGHT_RESOURCE_PLAN_POSTGRES", "PREFLIGHT_RESOURCE_PLAN_REDIS", "PREFLIGHT_RESOURCE_PLAN_APP", "PREFLIGHT_RESOURCE_PLAN_WORKER", "PREFLIGHT_RESOURCE_PLAN_NGINX"}.isdisjoint(codes)


def test_preflight_never_reads_secret_values_and_requires_complete_name_inventory(tmp_path):
    bundle = _bundle(tmp_path)
    (bundle / "requirements" / "secret-references.txt").write_text("JWT_SECRET=not-allowed\n", encoding="utf-8")
    result = preflight.preflight(bundle, observation=_host())
    assert result["status"] == "failed"
    assert {item["code"] for item in result["checks"] if item["status"] == "failed"} == {"PREFLIGHT_SECRET_REFERENCES_INVALID"}
    assert "not-allowed" not in json.dumps(result)


def test_preflight_cli_accepts_fixture_without_host_or_docker_access(tmp_path, capsys):
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps({"host": {
        "system": "Linux", "machine": "x86_64", "docker_engine": "27.0", "compose": "v2.29.0",
        "cpu_count": 4, "memory_bytes": preflight.MIN_MEMORY_BYTES, "disk_free_bytes": preflight.MIN_DISK_BYTES,
        "docker_data_free_bytes": preflight.MIN_DISK_BYTES, "occupied_ports": [],
    }}), encoding="utf-8")
    assert preflight.main(["--bundle", str(_bundle(tmp_path)), "--fixture", str(fixture)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "passed"


def test_dry_run_success_observes_app_before_nginx_and_has_no_rollback():
    result = dry_run.run_dry_run({"outcomes": {}})
    assert result["status"] == "passed"
    assert result["rollback_attempts"] == 0
    steps = [event["step"] for event in result["events"]]
    assert steps.index("candidate_app_switch") < steps.index("candidate_nginx_switch") < steps.index("health_observation")


def test_dry_run_deployment_failure_performs_exactly_one_deterministic_rollback():
    result = dry_run.run_dry_run({"outcomes": {"candidate_nginx_switch": False}})
    assert result["status"] == "rolled-back"
    assert result["rollback_attempts"] == 1
    assert [event["step"] for event in result["events"]][-4:] == list(dry_run.ROLLBACK_STEPS)


def test_dry_run_rollback_failure_is_hard_stop_without_looping():
    result = dry_run.run_dry_run({"outcomes": {"health_observation": False, "rollback_health": False}})
    assert result["status"] == "failed"
    assert result["terminal"] == "rollback-hard-stop"
    assert result["rollback_attempts"] == 1
    assert [event["step"] for event in result["events"]].count("rollback_app_switch") == 1


def test_dry_run_preflight_failure_does_not_attempt_rollback():
    result = dry_run.run_dry_run({"outcomes": {"preflight": False}})
    assert result["terminal"] == "hard-stop"
    assert result["rollback_attempts"] == 0


def test_dry_run_fixture_cli_has_no_live_mode_and_reports_stable_code(tmp_path, capsys):
    fixture = tmp_path / "dry-run.json"
    fixture.write_text(json.dumps({"outcomes": {"candidate_import": False}}), encoding="utf-8")
    assert dry_run.main(["--fixture", str(fixture)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "rolled-back"
    assert all(event["code"].startswith("DRYRUN_") for event in result["events"])
    source = (Path(dry_run.__file__)).read_text(encoding="utf-8")
    assert "import subprocess" not in source and "deploy.ps1" not in source
