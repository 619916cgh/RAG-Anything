"""Classify one isolated DashScope embedding health call without secrets or content."""
from __future__ import annotations

import json
import os
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse


def _http_family(status: int) -> str:
    if 200 <= status < 300:
        return "2xx"
    if 400 <= status < 500:
        return "4xx"
    if 500 <= status < 600:
        return "5xx"
    return "other"


def _result(*, outcome: str, http_family: str, embedding_data_present: bool, vector_dimensions: list[int]) -> int:
    print(json.dumps({
        "kind": "qwen_embedding_health",
        "outcome": outcome,
        "http_family": http_family,
        "embedding_data_present": embedding_data_present,
        "vector_dimensions": vector_dimensions,
    }, sort_keys=True))
    return 0 if outcome == "success" else 1


def _dimensions(payload: Any) -> list[int]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return []
    dimensions: list[int] = []
    for item in payload["data"]:
        vector = item.get("embedding") if isinstance(item, dict) else None
        if isinstance(vector, list):
            dimensions.append(len(vector))
    return dimensions


def main() -> int:
    endpoint = os.getenv("PERF_QWEN_ENDPOINT", "").strip().rstrip("/")
    api_key = os.getenv("PERF_QWEN_API_KEY", "").strip()
    model = os.getenv("PERF_QWEN_EMBEDDING_MODEL", "").strip()
    parsed = urlparse(endpoint)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com"}
        or not api_key
        or not model
    ):
        return _result(
            outcome="invalid_isolated_configuration",
            http_family="none",
            embedding_data_present=False,
            vector_dimensions=[],
        )

    body = json.dumps({"model": model, "input": ["health"]}).encode("utf-8")
    request = Request(
        endpoint + "/embeddings",
        data=body,
        method="POST",
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            status = int(response.status)
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return _result(
            outcome="http_failure",
            http_family=_http_family(int(error.code)),
            embedding_data_present=False,
            vector_dimensions=[],
        )
    except (URLError, OSError, TimeoutError, json.JSONDecodeError):
        return _result(
            outcome="transport_or_invalid_response",
            http_family="transport",
            embedding_data_present=False,
            vector_dimensions=[],
        )

    dimensions = _dimensions(payload)
    return _result(
        outcome="success" if dimensions else "invalid_success_response",
        http_family=_http_family(status),
        embedding_data_present=isinstance(payload.get("data"), list),
        vector_dimensions=dimensions,
    )


if __name__ == "__main__":
    raise SystemExit(main())
