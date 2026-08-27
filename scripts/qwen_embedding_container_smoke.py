"""One SDK embedding call for the isolated container boundary; output is fixed and redacted."""
from __future__ import annotations

import asyncio
import os
import time


async def main() -> int:
    from lightrag.llm.openai import openai_embed

    started = time.monotonic()
    try:
        result = await asyncio.wait_for(
            openai_embed.func(
                ["health"],
                model=os.environ["PERF_QWEN_EMBEDDING_MODEL"],
                base_url=os.environ["PERF_QWEN_ENDPOINT"],
                api_key=os.environ["PERF_QWEN_API_KEY"],
                client_configs={"timeout": 20, "max_retries": 0},
            ),
            timeout=25,
        )
        dimensions = [len(item) for item in result] if hasattr(result, "__iter__") else []
        print({"outcome": "success", "elapsed_ms": round((time.monotonic() - started) * 1000, 1), "vector_dimensions": dimensions})
        return 0
    except TimeoutError:
        print({"outcome": "timeout", "elapsed_ms": round((time.monotonic() - started) * 1000, 1), "vector_dimensions": []})
        return 1
    except Exception:
        print({"outcome": "request_or_response_error", "elapsed_ms": round((time.monotonic() - started) * 1000, 1), "vector_dimensions": []})
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
