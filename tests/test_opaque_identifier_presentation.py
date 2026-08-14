from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from raganything.routers import agent, demo, knowledge
from raganything.services.demo_shares import DemoShare
from raganything.utils.kb_display_name import (
    UNKNOWN_KNOWLEDGE_BASE_NAME,
    get_knowledge_base_display_name,
)


OPAQUE_ID = "0123456789abcdef0123456789ABCDEF"
NON_HEX_32_CHARACTER_NAME = "g" * 32


def _share() -> DemoShare:
    return DemoShare(
        share_id="00000000-0000-4000-8000-000000000001",
        agent_id="agent-1",
        kb_name=OPAQUE_ID,
        created_by=1,
        created_at=None,
        revoked_at=None,
        max_requests_per_minute=10,
        max_concurrent_queries=2,
    )


def test_kb_display_name_never_falls_back_to_an_opaque_internal_name():
    assert get_knowledge_base_display_name({"name": "Course material"}, OPAQUE_ID) == "Course material"
    assert get_knowledge_base_display_name({"name": OPAQUE_ID}, OPAQUE_ID) == UNKNOWN_KNOWLEDGE_BASE_NAME
    assert get_knowledge_base_display_name({}, OPAQUE_ID) == UNKNOWN_KNOWLEDGE_BASE_NAME


@pytest.mark.asyncio
async def test_agents_and_shares_include_safe_kb_display_names(monkeypatch):
    async def metadata():
        return {OPAQUE_ID: {"name": OPAQUE_ID}}

    monkeypatch.setattr(agent, "load_kb_meta", metadata)
    presented_agents = await agent._present_agents([{"id": "agent-1", "kb_name": OPAQUE_ID}])
    assert presented_agents[0]["kb_display_name"] == UNKNOWN_KNOWLEDGE_BASE_NAME

    payload = demo._present_share(_share(), await metadata(), {"agent-1": {"name": "Course assistant"}})
    assert payload["kb_display_name"] == UNKNOWN_KNOWLEDGE_BASE_NAME
    assert payload["agent_name"] == "Course assistant"


@pytest.mark.asyncio
async def test_public_demo_bootstrap_uses_safe_name_for_legacy_metadata(monkeypatch):
    async def authenticated(_share_id, _token):
        return _share()

    async def validated(_share):
        return {"name": "Course assistant"}, {"name": OPAQUE_ID}

    monkeypatch.setattr(demo, "_authenticated_share", authenticated)
    monkeypatch.setattr(demo, "_validated_share_agent", validated)

    result = await demo.demo_bootstrap(_share().share_id, "x")
    assert result["knowledge_base"]["name"] == UNKNOWN_KNOWLEDGE_BASE_NAME


@pytest.mark.asyncio
async def test_graph_hides_opaque_automatic_entities_and_edges_before_manual_merge(monkeypatch):
    async def entities(_workspace):
        return {"doc-1": {"entity_names": [OPAQUE_ID, "Course", NON_HEX_32_CHARACTER_NAME], "count": 3}}

    async def relations(_workspace):
        return {"doc-1": {"relation_pairs": [(OPAQUE_ID, "Course"), ("Course", NON_HEX_32_CHARACTER_NAME)], "count": 2}}

    async def doc_ids(_workspace):
        return {"doc-1"}

    captured = {}

    async def merge(_workspace, nodes, edges):
        captured["nodes"] = nodes
        captured["edges"] = edges
        return nodes + [{"id": OPAQUE_ID, "label": OPAQUE_ID[:25], "entity_type": "manual"}], edges + [{
            "source": OPAQUE_ID,
            "target": "Course",
            "label": "manual",
            "_user_relation_id": "relation-1",
        }]

    from raganything.services import pg_graph_edit_repo

    monkeypatch.setattr(knowledge, "kb_dir", lambda _kb: "workspace")
    monkeypatch.setattr(knowledge, "_pg_fetch_graph_entities", entities)
    monkeypatch.setattr(knowledge, "_pg_fetch_graph_relations", relations)
    monkeypatch.setattr(knowledge, "_pg_fetch_doc_ids", doc_ids)
    monkeypatch.setattr(pg_graph_edit_repo, "apply_user_edits_to_graph", merge)

    graph = await knowledge.graph_data(kb="kb", current_user={})
    entity_list = await knowledge.list_entities(SimpleNamespace(query_params={}), kb="kb", current_user={})

    assert {node["id"] for node in captured["nodes"]} == {"Course", NON_HEX_32_CHARACTER_NAME}
    assert captured["edges"] == [{"source": "Course", "target": NON_HEX_32_CHARACTER_NAME, "label": ""}]
    assert {node["id"] for node in graph["nodes"]} == {OPAQUE_ID, "Course", NON_HEX_32_CHARACTER_NAME}
    assert {tuple((edge["source"], edge["target"])) for edge in graph["edges"]} == {
        (OPAQUE_ID, "Course"),
        ("Course", NON_HEX_32_CHARACTER_NAME),
    }
    assert {entry["name"] for entry in entity_list["entities"]} == {"Course", NON_HEX_32_CHARACTER_NAME}
    assert entity_list["total"] == 2


@pytest.mark.asyncio
async def test_opaque_graph_detail_requires_a_manual_entity(monkeypatch):
    from raganything.services import pg_graph_edit_repo

    async def no_manual_entities(_workspace):
        return []

    monkeypatch.setattr(knowledge, "kb_dir", lambda _kb: "workspace")
    monkeypatch.setattr(pg_graph_edit_repo, "list_user_entities", no_manual_entities)

    with pytest.raises(HTTPException, match="实体不存在") as exc:
        await knowledge.graph_node_detail(OPAQUE_ID, kb="kb", current_user={})
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_manual_opaque_graph_entity_does_not_mix_in_automatic_sources(monkeypatch):
    from raganything.services import pg_graph_edit_repo

    async def manual_entities(_workspace):
        return [{"name": OPAQUE_ID, "entity_type": "business-code"}]

    async def manual_relations(_workspace, _entity_name):
        return [{
            "id": "relation-1",
            "source_entity": OPAQUE_ID,
            "target_entity": "Course",
            "relation_type": "manual",
        }]

    async def unexpected_auto_read(_workspace):
        pytest.fail("manual opaque entities must not read automatic graph data")

    monkeypatch.setattr(knowledge, "kb_dir", lambda _kb: "workspace")
    monkeypatch.setattr(pg_graph_edit_repo, "list_user_entities", manual_entities)
    monkeypatch.setattr(pg_graph_edit_repo, "get_user_relations_for_entity", manual_relations)
    monkeypatch.setattr(knowledge, "_pg_fetch_graph_entities", unexpected_auto_read)
    monkeypatch.setattr(knowledge, "_pg_fetch_graph_relations", unexpected_auto_read)
    monkeypatch.setattr(knowledge, "_pg_fetch_doc_ids", unexpected_auto_read)

    detail = await knowledge.graph_node_detail(OPAQUE_ID, kb="kb", current_user={})
    assert detail["source_doc_count"] == 0
    assert detail["connected_entities"] == ["Course"]
    assert detail["relations"] == [{
        "source": OPAQUE_ID,
        "target": "Course",
        "type": "manual",
        "relation_type": "manual",
        "relation_id": "relation-1",
    }]
