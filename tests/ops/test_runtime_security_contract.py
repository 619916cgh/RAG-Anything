from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_app_healthcheck_uses_live_and_compose_does_not_publish_app_port():
    for path in (ROOT / "Dockerfile", ROOT / "deploy" / "fast-release" / "Dockerfile.app"):
        content = path.read_text(encoding="utf-8")
        assert "/api/live" in content
        assert "/api/health" not in content
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    app_section = compose.split("\n  postgres:", 1)[0]
    assert "ports:" not in app_section
    remote = (ROOT / "deploy" / "fast-release" / "remote-release.sh").read_text(encoding="utf-8")
    assert "curl -fsS --max-time 10 http://127.0.0.1:8000" not in remote
    assert "docker exec raganything-app" in remote


def test_prometheus_inventory_has_all_alert_rule_target_owners():
    inventory = (ROOT / "deploy" / "prometheus" / "release-scrape-inventory.yml").read_text(encoding="utf-8")
    for job in ("raganything", "postgres", "redis", "node", "backup", "tls"):
        assert f"job_name: {job}" in inventory
    assert inventory.count("target_owner:") == 6
    assert not any(secret in inventory.lower() for secret in ("password", "token", "authorization:"))
