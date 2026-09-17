import pytest

from raganything.modalprocessors.table import TableModalProcessor


@pytest.mark.asyncio
async def test_empty_table_is_marked_non_indexable_without_persisting_a_chunk():
    processor = object.__new__(TableModalProcessor)
    content = {
        "type": "table",
        "table_body": "| | |\n| --- | --- |",
        "page_idx": 0,
    }

    description, entity_info = await processor.generate_description_only(
        content,
        "table",
    )
    result = await processor.process_multimodal_content(
        content,
        "table",
    )

    assert "未提取到" in description
    assert entity_info["non_indexable"] is True
    assert entity_info["analysis_source"] == "empty_table"
    assert entity_info["empty_reason"] == "no_meaningful_table_content"
    assert result[0] == description
    assert result[1] == entity_info
    assert result[2] == []


@pytest.mark.asyncio
async def test_table_exception_fallback_uses_chinese_labels(monkeypatch):
    monkeypatch.setenv("MULTIMODAL_PROMPT_LANGUAGE", "zh")
    processor = object.__new__(TableModalProcessor)

    async def fail(*_args, **_kwargs):
        raise RuntimeError("synthetic provider failure")

    processor._call_modal_caption = fail
    _, entity_info = await processor.generate_description_only(
        {"table_body": "| 项目 | 数值 |\n| --- | --- |\n| 续航 | 500km |"},
        "table",
    )

    assert entity_info["entity_name"].startswith("表格_")
    assert entity_info["summary"].startswith("表格内容：")
    assert "Table content:" not in entity_info["summary"]
