import importlib.util
from pathlib import Path


def load_attribution():
    path = (
        Path(__file__).parents[1]
        / "scripts"
        / "judge_retrieval_attribution.py"
    )
    spec = importlib.util.spec_from_file_location(
        "judge_retrieval_attribution",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_primary_cause_distinguishes_recall_from_unused_context():
    attribution = load_attribution()
    base_context = {"context_present": True, "error": None}

    assert (
        attribution.primary_cause(
            base_context,
            {
                "context_support": "none",
                "answer_relationship": "no_answer",
            },
        )
        == "retrieval_miss"
    )
    assert (
        attribution.primary_cause(
            base_context,
            {
                "context_support": "full",
                "answer_relationship": "ignores_context",
            },
        )
        == "context_present_but_unused"
    )
    assert (
        attribution.primary_cause(
            base_context,
            {
                "context_support": "full",
                "answer_relationship": "contradicts_context",
            },
        )
        == "context_present_and_used_wrongly"
    )
