import importlib.util
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
