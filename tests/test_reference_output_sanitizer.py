from raganything.query.output_sanitizer import (
    ReferenceOutputFilter,
    strip_reference_markers,
)


def test_strip_reference_markers_removes_inline_markers_and_tail_section():
    text = (
        "答案是 12V。[来源 1]\n"
        "同时检查接地。[来源：维修手册]\n\n"
        "📚 参考来源\n"
        "[来源 1] — 原文字段\n"
    )

    assert strip_reference_markers(text) == "答案是 12V。\n同时检查接地。\n\n"


def test_streaming_filter_handles_split_markers_and_reference_tail():
    stream_filter = ReferenceOutputFilter(enabled=True)
    chunks = [
        "答案是 ",
        "12V。[来",
        "源 1]\n继续检查。\n📚 参",
        "考来源\n[来源 1] — 原文",
    ]

    visible = "".join(stream_filter.feed(chunk) for chunk in chunks)
    visible += stream_filter.finish()

    assert visible == "答案是 12V。\n继续检查。\n"
    assert "[来源" not in visible
    assert "参考来源" not in visible


def test_streaming_filter_is_passthrough_when_references_enabled():
    stream_filter = ReferenceOutputFilter(enabled=False)

    assert stream_filter.feed("答案 [来源 1]") == "答案 [来源 1]"
    assert stream_filter.finish() == ""


def test_streaming_filter_handles_one_character_tokens_and_source_alias():
    raw = "正文 [来源1] 和 [Source 2]\n\n📚 参考来源\n[来源 1] — 原文"
    stream_filter = ReferenceOutputFilter(enabled=True)

    visible = "".join(stream_filter.feed(char) for char in raw)
    visible += stream_filter.finish()

    assert visible == "正文  和 \n\n"
    assert "[来源" not in visible
    assert "[Source" not in visible
    assert "参考来源" not in visible
