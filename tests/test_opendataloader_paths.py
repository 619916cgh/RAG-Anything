import json
from pathlib import Path

import pytest

from raganything.parser.office_parser import PageTrackedContent
from raganything.parser.opendataloader_parser import (
    OpenDataLoaderParser,
    _build_ocr_content_blocks,
    _build_table_block,
    _extract_rapidocr_lines,
    _has_retainable_element_content,
    _meaningful_text_char_count,
    _ocr_recovery_is_sufficient,
    _resolve_output_base,
    ODLOcrError,
)
from raganything.utils._content import separate_content


def test_relative_output_directory_resolves_before_artifact_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pdf_path = (tmp_path / "uploads" / "document.pdf").resolve()

    output_base = _resolve_output_base("odl-artifacts", pdf_path)
    artifact = (output_base / "document" / "run-1" / "page.json").resolve()

    assert output_base.is_absolute()
    assert artifact.relative_to(output_base).as_posix() == (
        "document/run-1/page.json"
    )


def test_default_output_directory_is_absolute(tmp_path):
    pdf_path = (tmp_path / "uploads" / "document.pdf").resolve()

    assert _resolve_output_base(None, pdf_path) == (
        pdf_path.parent / "odl_output"
    ).resolve()


def test_page_tracked_content_carries_odl_provenance_reference():
    reference = {
        "schema": "odl-provenance-ref-v1",
        "relative_path": "document/run-1/provenance.json",
    }

    content = PageTrackedContent([], {"source_total_pages": 1}, reference)

    assert content.provenance_ref == reference


def test_flattened_odl_block_keeps_page_element_and_bbox_provenance(tmp_path):
    content, provenance, pages = OpenDataLoaderParser._flatten_elements(
        [
            {
                "id": "paragraph-7",
                "type": "paragraph",
                "page number": 2,
                "bounding box": [10, 20, 110, 70],
                "content": "检修前断开电源。",
            }
        ],
        tmp_path,
        "",
    )

    assert pages == {2}
    assert provenance[0]["source_page"] == 2
    assert content[0]["_provenance"] == {
        "source_page": 2,
        "page_idx": 1,
        "element_id": "paragraph-7",
        "element_type": "paragraph",
        "bbox": [10.0, 20.0, 110.0, 70.0],
        "bbox_coordinate_system": {
            "units": "PDF points",
            "origin": "bottom-left",
            "order": ["left", "bottom", "right", "top"],
        },
    }


@pytest.mark.parametrize(
    "table",
    [
        {
            "type": "table",
            "rows": [
                {
                    "cells": [
                        {"content": "", "kids": []},
                        {"content": "   ", "kids": []},
                    ]
                }
            ],
        },
        {
            "type": "table",
            "rows": [
                {
                    "cells": [
                        {"content": "|"},
                        {"content": " --- | :--- "},
                    ]
                }
            ],
        },
        {
            "type": "table",
            "rows": [
                {
                    "cells": [
                        {"kids": [{"type": "paragraph", "content": " | | "}]},
                    ]
                }
            ],
        },
    ],
)
def test_empty_odl_tables_do_not_become_table_blocks(tmp_path, table):
    assert _build_table_block(table, tmp_path, 0, "") is None


def test_odl_table_keeps_real_text_and_zero_value(tmp_path):
    block = _build_table_block(
        {
            "type": "table",
            "rows": [
                {
                    "cells": [
                        {"content": "项目"},
                        {"content": "0"},
                    ]
                }
            ],
        },
        tmp_path,
        0,
        "",
    )

    assert block is not None
    assert block["type"] == "table"
    assert "| 项目 | 0 |" in block["table_body"]


def test_odl_table_row_content_is_kept_when_cells_are_empty(tmp_path):
    block = _build_table_block(
        {
            "type": "table",
            "rows": [{"cells": [], "content": "有效文本"}],
        },
        tmp_path,
        0,
        "",
    )

    assert block is not None
    assert "有效文本" in block["table_body"]


def test_caption_only_odl_table_is_text_not_table(tmp_path):
    content, provenance, pages = OpenDataLoaderParser._flatten_elements(
        [
            {
                "type": "table",
                "id": "table-caption",
                "page number": 2,
                "caption": "表 1 系统参数",
                "rows": [{"cells": [{"content": ""}]}],
            }
        ],
        tmp_path,
        "",
    )

    assert pages == {2}
    assert content == [
        {
            "type": "text",
            "text": "表 1 系统参数",
            "page_idx": 1,
            "_provenance": {
                "source_page": 2,
                "page_idx": 1,
                "element_id": "table-caption",
                "element_type": "table",
            },
        }
    ]
    assert provenance[0]["odl_id"] == "table-caption"


def test_markup_only_caption_is_not_emitted(tmp_path):
    content, _, _ = OpenDataLoaderParser._flatten_elements(
        [
            {
                "type": "table",
                "caption": "| --- | :--- |",
                "rows": [{"cells": [{"content": ""}]}],
            }
        ],
        tmp_path,
        "",
    )

    assert content == []
    assert _has_retainable_element_content(
        {
            "type": "table",
            "caption": "| --- | :--- |",
            "rows": [{"cells": [{"content": ""}]}],
        },
        tmp_path,
        0,
        "",
    ) is False


def test_nested_table_image_is_preserved_with_media_and_provenance(tmp_path):
    output_root = tmp_path / "odl-output"
    media_dir = output_root / "media"
    media_dir.mkdir(parents=True)
    image = media_dir / "inside-table.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + (b"0" * 32))

    content, provenance, pages = OpenDataLoaderParser._flatten_elements(
        [
            {
                "type": "table",
                "id": "table-3",
                "page number": 3,
                "bounding box": [10, 20, 200, 90],
                "rows": [
                    {
                        "cells": [
                            {
                                "kids": [
                                    {
                                        "type": "image",
                                        "id": "nested-image-1",
                                        "page number": 3,
                                        "bounding box": [20, 30, 80, 70],
                                        "caption": "接线示意",
                                        "source": "media/inside-table.png",
                                    }
                                ]
                            }
                        ]
                    }
                ],
            }
        ],
        output_root,
        "",
    )

    assert pages == {3}
    assert [block["type"] for block in content] == ["image"]
    image_block = content[0]
    assert image_block["img_path"] == str(image.resolve())
    assert image_block["_odl_media"]["relative_path"] == "media/inside-table.png"
    assert image_block["_provenance"] == {
        "source_page": 3,
        "page_idx": 2,
        "element_id": "nested-image-1",
        "element_type": "image",
        "bbox": [20.0, 30.0, 80.0, 70.0],
        "bbox_coordinate_system": {
            "units": "PDF points",
            "origin": "bottom-left",
            "order": ["left", "bottom", "right", "top"],
        },
    }
    nested_provenance = provenance[1]
    assert nested_provenance["odl_id"] == "nested-image-1"
    assert nested_provenance["parent_element_id"] == "table-3"
    assert nested_provenance["media_sha256"] == image_block["_odl_media"]["sha256"]
    assert image_block["_odl_provenance_index"] == 1


def test_nested_table_image_is_kept_alongside_meaningful_table_text(tmp_path):
    output_root = tmp_path / "odl-output"
    media_dir = output_root / "media"
    media_dir.mkdir(parents=True)
    image = media_dir / "inside-table.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + (b"0" * 32))

    content, _, _ = OpenDataLoaderParser._flatten_elements(
        [
            {
                "type": "table",
                "id": "table-4",
                "page number": 4,
                "rows": [
                    {
                        "cells": [
                            {
                                "content": "项目",
                                "kids": [
                                    {
                                        "type": "image",
                                        "id": "nested-image-2",
                                        "source": "media/inside-table.png",
                                    }
                                ],
                            }
                        ]
                    }
                ],
            }
        ],
        output_root,
        "",
    )

    assert [block["type"] for block in content] == ["table", "image"]
    assert image.exists()


def test_nested_table_kid_image_is_not_walked_twice(tmp_path):
    output_root = tmp_path / "odl-output"
    media_dir = output_root / "media"
    media_dir.mkdir(parents=True)
    image = media_dir / "kid-image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + (b"0" * 32))

    content, provenance, _ = OpenDataLoaderParser._flatten_elements(
        [
            {
                "type": "table",
                "id": "table-kid",
                "page number": 6,
                "kids": [
                    {
                        "type": "image",
                        "id": "kid-image",
                        "source": "media/kid-image.png",
                    }
                ],
                "rows": [{"cells": [{"content": ""}]}],
            }
        ],
        output_root,
        "",
    )

    assert [block["type"] for block in content] == ["image"]
    assert len([item for item in provenance if item["odl_id"] == "kid-image"]) == 1


def test_table_level_image_is_kept_when_table_has_no_text(tmp_path):
    output_root = tmp_path / "odl-output"
    media_dir = output_root / "media"
    media_dir.mkdir(parents=True)
    image = media_dir / "empty-table-image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + (b"0" * 32))

    content, _, _ = OpenDataLoaderParser._flatten_elements(
        [
            {
                "type": "table",
                "id": "table-image-only",
                "page number": 5,
                "image": "media/empty-table-image.png",
                "rows": [{"cells": [{"content": ""}]}],
            }
        ],
        output_root,
        "",
    )

    assert [block["type"] for block in content] == ["image"]
    assert content[0]["_odl_media"]["relative_path"] == (
        "media/empty-table-image.png"
    )


def test_meaningful_text_count_ignores_media_but_counts_table_and_equation():
    blocks = [
        {"type": "text", "text": "汽车电气线路导线按电压等级分类。"},
        {"type": "image", "img_path": "page.png", "image_caption": "如图"},
        {"type": "table", "table_body": "| 项目 | 数值 |\n| --- | --- |"},
        {"type": "equation", "text": "U=IR"},
    ]

    assert _meaningful_text_char_count(blocks) == 22
    assert _meaningful_text_char_count(
        [{"type": "image", "img_path": "page.png"}]
    ) == 0


def test_rapidocr_lines_are_sorted_and_page_noise_is_filtered():
    class ArrayLike:
        def __init__(self, values):
            self._values = values

        def __len__(self):
            return len(self._values)

        def __getitem__(self, index):
            return self._values[index]

    def box(points):
        return ArrayLike([ArrayLike(point) for point in points])

    class Result:
        txts = ("12", "第二行", "000", "---", "第一行")
        boxes = ArrayLike(
            (
                box([[10, 1900], [40, 1900], [40, 1930], [10, 1930]]),
                box([[100, 100], [300, 100], [300, 140], [100, 140]]),
                box([[100, 500], [200, 500], [200, 540], [100, 540]]),
                box([[100, 600], [180, 600], [180, 630], [100, 630]]),
                box([[100, 200], [300, 200], [300, 240], [100, 240]]),
            )
        )
        scores = (0.99, 0.98, 0.97, 0.96, 0.95)

    lines = _extract_rapidocr_lines(Result(), image_width=400, image_height=2000)

    assert [line["text"] for line in lines] == ["第二行", "第一行"]
    assert lines[0]["bbox_pixels"] == [100.0, 100.0, 300.0, 140.0]
    assert lines[0]["score"] == 0.98


def test_ocr_blocks_keep_page_provenance_without_value_loss():
    lines = [
        {
            "text": "2. 导线",
            "bbox_pixels": [10.0, 20.0, 100.0, 40.0],
            "score": 0.99,
        },
        {
            "text": "汽车电气线路导线按电压等级可分为低压线和高压线两类。",
            "bbox_pixels": [10.0, 50.0, 300.0, 70.0],
            "score": 0.98,
        },
    ]
    blocks, provenance = _build_ocr_content_blocks(lines, 12)

    assert [block["text"] for block in blocks] == [
        "2. 导线",
        "汽车电气线路导线按电压等级可分为低压线和高压线两类。",
    ]
    assert blocks[0]["page_idx"] == 11
    assert blocks[0]["_provenance"]["source_page"] == 12
    assert blocks[0]["_provenance"]["parser_chain"] == [
        "opendataloader",
        "rapidocr",
    ]
    assert provenance[1]["extraction_method"] == "ocr"
    assert provenance[1]["ocr_confidence"] == 0.98


def test_ocr_blocks_keep_repeated_table_values_at_distinct_positions():
    lines = [
        {
            "text": "1",
            "bbox_pixels": [10.0, 20.0, 30.0, 40.0],
            "score": 0.99,
        },
        {
            "text": "1",
            "bbox_pixels": [100.0, 20.0, 120.0, 40.0],
            "score": 0.98,
        },
    ]

    blocks, provenance = _build_ocr_content_blocks(lines, 14)

    assert [block["text"] for block in blocks] == ["1", "1"]
    assert len(provenance) == 2


def test_merge_ocr_text_preserves_same_value_from_existing_and_ocr():
    parser = OpenDataLoaderParser()
    page_content = [{"type": "text", "text": "系统", "page_idx": 11}]

    parser._merge_ocr_text(
        page_content,
        [{"odl_id": "existing"}],
        [{"text": "系统", "bbox_pixels": [10.0, 20.0, 50.0, 40.0]}],
        12,
    )

    assert [block["text"] for block in page_content] == ["系统", "系统"]


def test_ocr_recovery_requires_merged_body_text_to_meet_threshold():
    assert not _ocr_recovery_is_sufficient(0, 1, 5, 20)
    assert not _ocr_recovery_is_sufficient(0, 0, 20, 20)
    assert _ocr_recovery_is_sufficient(10, 1, 10, 20)


def test_ocr_batch_runner_rejects_expired_timeout_without_spawning(tmp_path):
    parser = OpenDataLoaderParser()

    with pytest.raises(ODLOcrError, match="no remaining timeout"):
        parser._run_ocr_batch_runner(
            tmp_path / "source.pdf",
            tmp_path / "run",
            [12],
            0,
        )


def test_ocr_batch_runner_wraps_process_start_failure(tmp_path, monkeypatch):
    parser = OpenDataLoaderParser()

    def fail_to_start(*_args, **_kwargs):
        raise OSError("no interpreter")

    monkeypatch.setattr(
        "raganything.parser.opendataloader_parser.subprocess.Popen",
        fail_to_start,
    )

    with pytest.raises(ODLOcrError, match="could not start its runner"):
        parser._run_ocr_batch_runner(
            tmp_path / "source.pdf",
            tmp_path / "run",
            [12],
            30,
        )


def test_ocr_batch_runner_preserves_safe_failure_categories(tmp_path, monkeypatch):
    parser = OpenDataLoaderParser()

    class FailingProcess:
        def wait(self, timeout):
            request_path = Path(captured_command[4])
            (request_path.parent / "ocr-result.json").write_text(
                json.dumps(
                    {
                        "schema_version": "odl-ocr-runner-result-v1",
                        "error": {
                            "failure_code": "odl_ocr_dependency_missing",
                            "message": "unsafe detail ignored",
                        },
                    }
                ),
                encoding="utf-8",
            )
            return 1

    captured_command = []

    def fake_popen(command, **_kwargs):
        captured_command.extend(command)
        return FailingProcess()

    monkeypatch.setattr(
        "raganything.parser.opendataloader_parser.subprocess.Popen",
        fake_popen,
    )

    with pytest.raises(ODLOcrError) as raised:
        parser._run_ocr_batch_runner(
            tmp_path / "source.pdf",
            tmp_path / "run",
            [12],
            30,
        )

    assert raised.value.failure_code == "odl_ocr_dependency_missing"
    assert "dependency is unavailable" in str(raised.value)
    assert "unsafe detail" not in str(raised.value)


def test_merge_ocr_text_places_body_text_before_page_media():
    parser = OpenDataLoaderParser()
    image = {"type": "image", "img_path": "page.png", "page_idx": 11}
    page_content = [image]
    page_provenance = [{"odl_id": "image-1"}]
    lines = [
        {
            "text": "汽车电气线路导线分为低压线和高压线。",
            "bbox_pixels": [10.0, 20.0, 300.0, 40.0],
            "score": 0.99,
        }
    ]

    block_count, char_count = parser._merge_ocr_text(
        page_content,
        page_provenance,
        lines,
        12,
    )

    assert block_count == 1
    assert char_count > 0
    assert [block["type"] for block in page_content] == ["text", "image"]
    assert page_content[0]["_odl_provenance_index"] == 1
    assert page_provenance[1]["source_page"] == 12


def test_merge_ocr_text_preserves_existing_odl_text_before_ocr_body():
    parser = OpenDataLoaderParser()
    page_content = [
        {"type": "text", "text": "2. 导线", "page_idx": 11},
        {"type": "image", "img_path": "page.png", "page_idx": 11},
    ]
    page_provenance = [{"odl_id": "heading"}, {"odl_id": "image-1"}]

    parser._merge_ocr_text(
        page_content,
        page_provenance,
        [
            {
                "text": "汽车电气线路导线按电压等级可分为低压线和高压线两类。",
                "bbox_pixels": [10.0, 20.0, 300.0, 40.0],
                "score": 0.99,
            }
        ],
        12,
    )

    assert [block["type"] for block in page_content] == ["text", "text", "image"]
    assert page_content[0]["text"] == "2. 导线"
    assert page_content[1]["text"].startswith("汽车电气线路导线")


def test_merged_ocr_text_becomes_searchable_text_before_media_marker():
    parser = OpenDataLoaderParser()
    page_content = [{"type": "image", "img_path": "page.png", "page_idx": 11}]
    parser._merge_ocr_text(
        page_content,
        [{"odl_id": "image-1"}],
        [
            {
                "text": "汽车电气线路导线分为低压线和高压线。",
                "bbox_pixels": [10.0, 20.0, 300.0, 40.0],
                "score": 0.99,
            }
        ],
        12,
    )

    text_content, multimodal_items = separate_content(page_content)

    assert "汽车电气线路导线分为低压线和高压线。" in text_content
    assert text_content.index("汽车电气线路导线") < text_content.index("[📷")
    assert len(multimodal_items) == 1


def test_cache_identity_includes_ocr_fallback_contract():
    identity = OpenDataLoaderParser.cache_identity()

    assert identity["adapter_schema"] == "2"
    assert identity["ocr_engine"] == "rapidocr"
    assert isinstance(identity["ocr_fallback_enabled"], bool)
    assert identity["ocr_min_text_chars"] >= 1
    assert identity["ocr_max_pages"] >= 1
    assert identity["ocr_render_scale"] >= 0.5
    assert 0.0 <= identity["ocr_text_score"] <= 1.0
    assert identity["ocr_det_limit_side_len"] == 960
    assert identity["ocr_onnx_threads"] == 2
