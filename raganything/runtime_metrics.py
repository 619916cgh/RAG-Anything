"""Opt-in Prometheus setup compatible with FastAPI included routers."""

from __future__ import annotations

import os
from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.routing import iter_route_contexts
from prometheus_client import CollectorRegistry, REGISTRY
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_fastapi_instrumentator.middleware import (
    PrometheusInstrumentatorMiddleware,
)
from starlette.requests import Request
from starlette.routing import Match


_SETUP_STATE = "_rag_runtime_metrics_configured"


def _metrics_enabled() -> bool:
    return os.getenv("ENABLE_METRICS", "False").lower() in {"true", "1"}


def _iter_route_names(request: Request) -> Iterator[tuple[Match, str]]:
    """Yield FastAPI route templates without using request path values."""
    for context in iter_route_contexts(request.app.routes):
        match, _ = context.matches(request.scope)
        path = context.path
        if path is not None:
            yield match, path


def _fastapi_route_name(request: Request) -> str | None:
    """Mirror instrumentator lookup while supporting FastAPI route contexts."""
    partial_match = None
    for match, path in _iter_route_names(request):
        if match == Match.FULL:
            return path
        if match == Match.PARTIAL and partial_match is None:
            partial_match = path

    if partial_match is not None:
        return partial_match

    app = request.app
    scope = request.scope
    if not app.router.redirect_slashes or scope["path"] == "/":
        return None

    redirect_scope = dict(scope)
    if scope["path"].endswith("/"):
        redirect_scope["path"] = scope["path"][:-1]
        trim = True
    else:
        redirect_scope["path"] = scope["path"] + "/"
        trim = False

    redirect_request = Request(redirect_scope)
    for match, path in _iter_route_names(redirect_request):
        if match == Match.FULL:
            return f"{path}/" if trim else path[:-1]
        if match == Match.PARTIAL and partial_match is None:
            partial_match = path
    return partial_match


class _FastAPICompatibleMetricsMiddleware(PrometheusInstrumentatorMiddleware):
    """Resolve the handler through FastAPI route contexts for this app only."""

    def __init__(self, *args, **kwargs) -> None:
        try:
            super().__init__(*args, **kwargs)
        except ValueError as exc:
            if "rag_requests_inprogress" not in str(exc):
                raise
            # The third-party middleware always registers this Gauge in the
            # global registry. Reuse it for an additional app instance.
            self.inprogress = REGISTRY._names_to_collectors[
                self.inprogress_name
            ]

    def _get_handler(self, request: Request) -> tuple[str, bool]:
        route_name = _fastapi_route_name(request)
        return route_name or request.url.path, route_name is not None


def configure_runtime_metrics(
    app: FastAPI,
    *,
    registry: CollectorRegistry | None = None,
) -> bool:
    """Install the existing opt-in metrics contract once for ``app``.

    ``registry`` is test-only dependency injection. Production uses the global
    Prometheus registry, preserving the existing query timing Histogram.
    """
    if not _metrics_enabled() or getattr(app.state, _SETUP_STATE, False):
        return False

    metrics_path = os.getenv("METRICS_PATH", "/metrics")
    options = {
        "should_group_status_codes": True,
        "should_ignore_untemplated": True,
        "should_respect_env_var": True,
        "should_instrument_requests_inprogress": True,
        "excluded_handlers": [metrics_path, "/health", "/favicon.ico"],
        "env_var_name": "ENABLE_METRICS",
        "inprogress_name": "rag_requests_inprogress",
        "inprogress_labels": True,
    }
    if registry is not None:
        options["registry"] = registry

    instrumentator = Instrumentator(**options)
    app.add_middleware(_FastAPICompatibleMetricsMiddleware, **options)
    instrumentator.expose(app, endpoint=metrics_path, include_in_schema=True)
    setattr(app.state, _SETUP_STATE, True)
    return True
