import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest


class _Connection:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.executed = None

    async def execute(self, sql, *args):
        self.executed = (sql, args)
        return "INSERT 0 1"

    async def fetch(self, _sql, *_args):
        return self.rows


class _Pool:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


@pytest.mark.asyncio
async def test_query_history_insert_serializes_citations(monkeypatch):
    from raganything.services import pg_state_repo

    connection = _Connection()
    monkeypatch.setattr(pg_state_repo, "_get_pool", lambda: _Pool(connection))
    citation = {
        "citation_id": "trace:1",
        "document_id": "doc-1",
        "chunk_id": "chunk-1",
        "document_name": "manual.pdf",
        "locator_status": "page",
        "page": 2,
    }
    await pg_state_repo.insert_query_history({
        "id": "query-1",
        "query": "question",
        "answer": "answer [来源 1]",
        "citations": [citation],
        "time": datetime.now(timezone.utc),
    })

    sql, args = connection.executed
    assert "citations" in sql
    assert json.loads(args[7]) == [citation]


@pytest.mark.asyncio
async def test_query_history_read_restores_citations_array(monkeypatch):
    from raganything.services import pg_state_repo

    citation = {"citation_id": "trace:1", "document_name": "manual.pdf"}
    row = {
        "id": "query-1",
        "citations": json.dumps([citation]),
    }
    monkeypatch.setattr(
        pg_state_repo,
        "_get_pool",
        lambda: _Pool(_Connection(rows=[row])),
    )

    result = await pg_state_repo.get_query_history()

    assert result[0]["citations"] == [citation]
