import importlib.util
import sys
from pathlib import Path


def load_runner():
    path = Path(__file__).parents[1] / "scripts" / "cloud_agent_qa_test.py"
    spec = importlib.util.spec_from_file_location("cloud_agent_qa_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_load_qa_sets_parses_project_order_and_counts(tmp_path):
    runner = load_runner()
    for number, question_number in zip(
        ("一", "二", "三", "四", "五", "六"),
        range(1, 7),
    ):
        (tmp_path / f"项目{number} 测试项目.md").write_text(
            "前言\n\n"
            f"### 项目{number} 测试项目\n\n"
            f"**{question_number}. 问：问题{question_number}？**  \n"
            f"答：答案{question_number}。\n",
            encoding="utf-8",
        )

    records = runner.load_qa_sets(tmp_path)

    assert [item["question_number"] for item in records] == [1, 2, 3, 4, 5, 6]
    assert [item["project_number"] for item in records] == [1, 2, 3, 4, 5, 6]
    assert [item["answer"] for item in records] == [
        f"答案{number}。" for number in range(1, 7)
    ]


def test_sanitize_value_removes_path_like_citation_fields():
    runner = load_runner()
    value = {
        "document_name": "项目一.md",
        "file_path": "/private/tmp/project.md",
        "nested": {"url": "http://example.invalid", "score": 0.9},
    }

    assert runner.sanitize_value(value) == {
        "document_name": "项目一.md",
        "nested": {"score": 0.9},
    }


def test_percentile_is_bounded():
    runner = load_runner()

    assert runner.percentile([], 0.95) is None
    assert runner.percentile([1.0, 2.0, 3.0], 0.95) == 3.0


def test_query_nonce_is_opt_in(monkeypatch):
    runner = load_runner()
    monkeypatch.setattr(sys, "argv", ["cloud_agent_qa_test.py", "--dry-run"])

    args = runner.parse_args()

    assert args.query_nonce is False


def test_query_stream_replaces_streamed_answer(monkeypatch):
    runner = load_runner()
    frames = [
        b'data: {"type":"accepted"}\n\n',
        b'data: {"type":"token","content":"first"}\n\n',
        b'data: {"type":"replace","content":"revised","answer_guard":{"used_revision":true}}\n\n',
        b'data: {"type":"done","id":"q1","citations":[]}\n\n',
    ]

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def readline(self):
            return frames.pop(0) if frames else b""

    monkeypatch.setattr(
        runner.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(),
    )
    client = runner.CloudClient("http://local", "token")

    result = client.query_stream("agent", "question", timeout=10)

    assert result["status"] == "passed"
    assert result["answer"] == "revised"
    assert result["answer_guard"] == {"used_revision": True}
