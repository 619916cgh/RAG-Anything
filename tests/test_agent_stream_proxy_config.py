from pathlib import Path


def test_agent_sse_proxy_disables_response_buffering():
    config = (Path(__file__).resolve().parents[1] / "nginx.conf").read_text(encoding="utf-8")

    stream_location = config.index(
        "location ~ ^/api/agents/[^/]+/query/stream(?:/internal)?$"
    )
    generic_api_location = config.index("location /api/")
    stream_block = config[stream_location:generic_api_location]

    assert "proxy_buffering off;" in stream_block
    assert "proxy_request_buffering off;" in stream_block
    assert "proxy_cache off;" in stream_block


def test_cors_allows_authenticated_media_range_headers():
    source = (Path(__file__).resolve().parents[1] / "server.py").read_text(
        encoding="utf-8"
    )

    assert 'allow_headers=["Authorization", "Content-Type", "Range"]' in source
    assert (
        'expose_headers=["Accept-Ranges", "Content-Length", "Content-Range"]'
        in source
    )
