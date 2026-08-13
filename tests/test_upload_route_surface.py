from pathlib import Path


def test_only_file_upload_routes_remain_public():
    source = Path("raganything/routers/knowledge.py").read_text(encoding="utf-8")

    assert '@router.post("/upload")' in source
    assert '@router.post("/upload/batch")' in source
    assert "/upload/folder" not in source
    assert "/upload/content" not in source
    assert "/upload/url" not in source
    assert "PasteContentRequest" not in source
    assert "def _folder_upload_roots" not in source
