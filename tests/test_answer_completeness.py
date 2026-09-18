import json

import pytest

from raganything.services.answer_completeness import (
    answer_completeness_guard_enabled,
    apply_answer_completeness_guard,
)


def audit_payload(
    *,
    context_has_answer=True,
    draft_conflicts_context=False,
    missing_required_facts=(),
):
    return json.dumps(
        {
            "context_has_answer": context_has_answer,
            "draft_conflicts_context": draft_conflicts_context,
            "missing_required_facts": list(missing_required_facts),
            "reason": "audit result",
        }
    )


@pytest.mark.asyncio
async def test_guard_keeps_draft_when_no_facts_are_missing():
    calls = []

    async def llm(**kwargs):
        calls.append(kwargs)
        return audit_payload()

    result = await apply_answer_completeness_guard(
        question="问题",
        context="上下文包含答案",
        draft_answer="首轮回答",
        llm_callable=llm,
    )

    assert result.final_answer == "首轮回答"
    assert result.used_revision is False
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_guard_revises_once_when_required_facts_are_missing():
    calls = []

    async def llm(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return audit_payload(missing_required_facts=("关键数值 12V",))
        return "修订后的完整回答：关键数值 12V。"

    result = await apply_answer_completeness_guard(
        question="问题",
        context="上下文包含关键数值 12V",
        draft_answer="首轮回答",
        llm_callable=llm,
    )

    assert result.used_revision is True
    assert result.final_answer == "修订后的完整回答：关键数值 12V。"
    assert result.first_answer == "首轮回答"
    assert result.missing_required_facts == ("关键数值 12V",)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_guard_keeps_draft_when_context_has_no_answer():
    calls = []

    async def llm(**kwargs):
        calls.append(kwargs)
        return audit_payload(context_has_answer=False)

    result = await apply_answer_completeness_guard(
        question="问题",
        context="无关上下文",
        draft_answer="首轮回答",
        llm_callable=llm,
    )

    assert result.final_answer == "首轮回答"
    assert result.used_revision is False
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_guard_keeps_draft_when_audit_json_is_invalid():
    async def llm(**kwargs):
        return "not json"

    result = await apply_answer_completeness_guard(
        question="问题",
        context="上下文",
        draft_answer="首轮回答",
        llm_callable=llm,
    )

    assert result.final_answer == "首轮回答"
    assert result.used_revision is False
    assert result.reason == "audit_failed"


@pytest.mark.asyncio
async def test_guard_keeps_draft_when_revision_fails():
    calls = []

    async def llm(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return audit_payload(missing_required_facts=("缺失事实",))
        raise RuntimeError("provider failed")

    result = await apply_answer_completeness_guard(
        question="问题",
        context="上下文",
        draft_answer="首轮回答",
        llm_callable=llm,
    )

    assert result.final_answer == "首轮回答"
    assert result.used_revision is False
    assert result.reason == "revision_failed"
    assert result.revision_error == "RuntimeError"


def test_guard_is_disabled_by_agent_default(monkeypatch):
    monkeypatch.delenv(
        "AGENT_ANSWER_COMPLETENESS_GUARD_FORCE_DISABLED",
        raising=False,
    )

    assert answer_completeness_guard_enabled(False) is False


def test_guard_respects_persistent_agent_configuration(monkeypatch):
    monkeypatch.delenv(
        "AGENT_ANSWER_COMPLETENESS_GUARD_FORCE_DISABLED",
        raising=False,
    )

    assert answer_completeness_guard_enabled(True) is True
    assert answer_completeness_guard_enabled(False) is False


def test_guard_force_disable_overrides_agent_configuration(monkeypatch):
    monkeypatch.setenv(
        "AGENT_ANSWER_COMPLETENESS_GUARD_FORCE_DISABLED",
        "true",
    )

    assert answer_completeness_guard_enabled(True) is False
