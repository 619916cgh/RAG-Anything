"""Streaming-safe answer sanitization for reference-disabled agent queries."""

from __future__ import annotations

import re


_REFERENCE_MARKER_RE = re.compile(
    r"(?:"
    r"[\[【]来源\s*[^\]】\r\n]{1,200}[\]】]"
    r"|\[Source\s*\d+\]"
    r")",
    re.IGNORECASE,
)
_DANGLING_REFERENCE_MARKER_RE = re.compile(
    r"(?:"
    r"[\[【]来源\s*[^\]】\r\n]*$"
    r"|\[Source\s*\d*$"
    r")",
    re.IGNORECASE,
)
_REFERENCE_HEADING_RE = re.compile(
    r"(?m)^[ \t]*(?:📚[ \t]*参考来源|【?引用来源】?|参考文献)"
    r"[ \t]*[:：]?[^\n]*$"
)
_PARTIAL_REFERENCE_TOKENS = (
    "[",
    "【",
    "[来源",
    "【来源",
    "[Source",
    "[source",
    "📚 参考来源",
    "📚参考来源",
    "📚",
    "参考来源",
    "参考文献",
    "引用来源",
    "【引用来源",
    "【引用来源】",
)


def strip_reference_markers(text: str | None) -> str:
    """Remove citation markers and any trailing reference section from text."""
    if not text:
        return ""
    heading = _REFERENCE_HEADING_RE.search(text)
    if heading:
        text = text[: heading.start()]
    text = _REFERENCE_MARKER_RE.sub("", text)
    return _DANGLING_REFERENCE_MARKER_RE.sub("", text)


def _safe_emit_end(text: str) -> int:
    """Return a prefix length that cannot contain a split reference token."""
    hold = 0
    for match in re.finditer(
        r"(?:[\[【]来源\s*[^\]】\r\n]*|\[Source\s*\d*)$",
        text,
        re.IGNORECASE,
    ):
        hold = max(hold, len(match.group(0)))

    for token in _PARTIAL_REFERENCE_TOKENS:
        max_prefix = min(len(token) - 1, len(text))
        for prefix_len in range(max_prefix, 0, -1):
            if text.endswith(token[:prefix_len]):
                hold = max(hold, prefix_len)
                break
    return len(text) - hold


class ReferenceOutputFilter:
    """Incrementally suppress citation markers and reference tails in SSE output."""

    def __init__(self, *, enabled: bool):
        self.enabled = bool(enabled)
        self._buffer = ""
        self._suppress_tail = False

    def feed(self, token: str | None) -> str:
        if not self.enabled:
            return str(token or "")
        if self._suppress_tail:
            return ""

        self._buffer += str(token or "")
        heading = _REFERENCE_HEADING_RE.search(self._buffer)
        if heading:
            visible = strip_reference_markers(self._buffer[: heading.start()])
            self._buffer = ""
            self._suppress_tail = True
            return visible

        cleaned = _REFERENCE_MARKER_RE.sub("", self._buffer)
        emit_end = _safe_emit_end(cleaned)
        visible = cleaned[:emit_end]
        self._buffer = cleaned[emit_end:]
        return visible

    def finish(self) -> str:
        if not self.enabled or self._suppress_tail:
            self._buffer = ""
            return ""
        visible = strip_reference_markers(self._buffer)
        self._buffer = ""
        return visible
