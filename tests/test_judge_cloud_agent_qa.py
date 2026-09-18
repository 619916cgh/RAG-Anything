import importlib.util
from pathlib import Path

import pytest


def load_judge():
    path = (
        Path(__file__).parents[1]
        / "scripts"
        / "judge_cloud_agent_qa.py"
    )
    spec = importlib.util.spec_from_file_location(
        "judge_cloud_agent_qa",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def judge_payload(*, verdicts=("hit",), core_correct=True):
    return {
        "core_correct": core_correct,
        "polarity": "not_applicable",
        "critical_conflicts": [],
        "ambiguous_question": False,
        "evidence_sufficient_for_scoring": True,
        "keypoint_verdicts": [
            {
                "id": f"k{index}",
                "verdict": verdict,
                "evidence": "候选回答证据",
            }
            for index, verdict in enumerate(verdicts, 1)
        ],
        "reason_codes": [],
        "rationale": "测试理由",
        "confidence": 0.9,
    }


def test_strict_json_rejects_duplicate_keys():
    judge = load_judge()

    with pytest.raises(ValueError, match="Duplicate JSON key"):
        judge.strict_json_loads('{"verdict":"correct","verdict":"partial"}')


def test_deterministic_verdict_requires_all_keypoints_for_correct():
    judge = load_judge()
    verdict, signals = judge.deterministic_verdict(
        judge_payload(verdicts=("hit", "miss")),
        "系统由什么组成？",
        "由电源和控制器组成。",
        "系统由电源组成。",
    )

    assert verdict == "partial"
    assert signals["keypoint_recall"] == 0.5


def test_deterministic_verdict_marks_atomic_conflict_manual_review():
    judge = load_judge()
    verdict, signals = judge.deterministic_verdict(
        {
            **judge_payload(),
            "core_correct": False,
            "critical_conflicts": ["电压值冲突"],
        },
        "低压电源通常是什么？",
        "通常为12V蓄电池。",
        "通常为24V蓄电池。",
    )

    assert verdict == "incorrect"
    assert signals["manual_review_required"] is True


def test_wilson_interval_is_bounded():
    judge = load_judge()

    low, high = judge.wilson_interval(50, 100)
    assert 0 <= low < 0.5 < high <= 1


def test_chinese_adjacent_units_are_normalized():
    judge = load_judge()

    assert judge.extract_atoms("12V蓄电池") == {"V:12"}
    assert judge.extract_atoms("12伏蓄电池") == {"V:12"}
    assert judge.extract_atoms("0.012kV蓄电池") == {"V:12"}
