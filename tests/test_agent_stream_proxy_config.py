from pathlib import Path


def test_agent_sse_proxy_disables_response_buffering():
    config = (Path(__file__).resolve().parents[1] / "nginx.conf").read_text(encoding="utf-8")

    stream_location = config.index("location ~ ^/api/agents/[^/]+/query/stream$")
    generic_api_location = config.index("location /api/")
    stream_block = config[stream_location:generic_api_location]

    assert "proxy_buffering off;" in stream_block
    assert "proxy_request_buffering off;" in stream_block
    assert "proxy_cache off;" in stream_block
