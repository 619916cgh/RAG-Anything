from pathlib import Path

import pytest

from raganything.parser.office_parser import PageTrackedContent
from raganything.parser.opendataloader_parser import (
    OpenDataLoaderParser,
    _build_table_block,
    _has_retainable_element_content,
    _resolve_output_base,
)


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
