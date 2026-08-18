import re
import os

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry
import pytest

from raganything.runtime_metrics import configure_runtime_metrics
from raganything.services.query_timing import QueryTiming


def _app(*, metrics=True, path=None, registry=None):
    os.environ["ENABLE_METRICS"] = "true" if metrics else "false"
    if path is None:
        os.environ.pop("METRICS_PATH", None)
    else:
        os.environ["METRICS_PATH"] = path

    app = FastAPI()
    configure_runtime_metrics(app, registry=registry)
    router = APIRouter()

    @router.get("/items/{item_id}")
    async def item(item_id: str):
        return {"item_id": item_id}

    app.include_router(router, prefix="/api")
    return app


@pytest.fixture(autouse=True)
def restore_metrics_environment():
    previous = {
        name: os.environ.get(name)
        for name in ("ENABLE_METRICS", "METRICS_PATH")
    }
    yield
    for name, value in previous.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def test_included_and_parameterized_route_is_instrumented_with_template():
    app = _app()
    with TestClient(app) as client:
        response = client.get("/api/items/private-value")
        body = client.get("/metrics").text

    assert response.status_code == 200
    assert 'handler="/api/items/{item_id}"' in body
    assert "private-value" not in body


def test_parameterized_route_wrong_method_is_405_and_still_templated():
    app = _app(registry=CollectorRegistry())
    with TestClient(app) as client:
        response = client.post("/api/items/private-value")
        body = client.get("/metrics").text

    assert response.status_code == 405
    assert 'handler="/api/items/{item_id}"' in body
    assert "private-value" not in body


def test_default_metrics_scrape_contains_query_timing_histogram():
    app = _app()
    with TestClient(app) as client:
        QueryTiming("metrics-scrape").record("retrieval", 0.001, channel="bm25")
        body = client.get("/metrics")

    assert body.status_code == 200
    assert "text/plain" in body.headers["content-type"]
    assert "rag_agent_query_phase_duration_seconds" in body.text
    assert 'phase="retrieval"' in body.text
    assert 'outcome="ok"' in body.text
    assert 'cache_status="na"' in body.text
    assert 'channel="bm25"' in body.text
    assert 'handler="/metrics"' not in body.text


def test_custom_path_is_exposed_once_and_excluded_from_http_metrics():
    app = _app(path="/internal/metrics", registry=CollectorRegistry())
    with TestClient(app) as client:
        before = client.get("/internal/metrics").text
        assert client.get("/metrics").status_code == 404
        client.get("/api/items/custom-value")
        after = client.get("/internal/metrics").text

    assert 'handler="/internal/metrics"' not in after
    assert 'handler="/api/items/{item_id}"' in after
    assert len(after) >= len(before)


def test_metrics_disabled_keeps_api_and_exposes_no_metrics_route():
    app = _app(metrics=False)
    with TestClient(app) as client:
        assert client.get("/api/items/private-value").status_code == 200
        assert client.get("/metrics").status_code == 404
        assert client.get("/internal/metrics").status_code == 404

    assert not getattr(app.state, "_rag_runtime_metrics_configured", False)


def test_repeated_setup_is_idempotent_and_can_enable_after_disabled():
    app = _app(metrics=False, path="/internal/metrics")
    os.environ["ENABLE_METRICS"] = "true"
    assert configure_runtime_metrics(app, registry=CollectorRegistry()) is True
    assert configure_runtime_metrics(app, registry=CollectorRegistry()) is False
    assert sum(
        getattr(route, "path", None) == "/internal/metrics" for route in app.routes
    ) == 1
    assert sum(
        middleware.cls.__name__ == "_FastAPICompatibleMetricsMiddleware"
        for middleware in app.user_middleware
    ) == 1


def test_lockfile_pins_supported_runtime_versions():
    lock = open("requirements.cpu-linux-py311-x86_64.lock", encoding="utf-8").read()
    assert re.search(r"^fastapi==0\.141\.1 \\", lock, re.MULTILINE)
    assert re.search(
        r"^prometheus-fastapi-instrumentator==7\.1\.0 \\",
        lock,
        re.MULTILINE,
    )
