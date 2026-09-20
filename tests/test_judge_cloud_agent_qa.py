import importlib.util
import json
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


def judge_payload(
    *,
    verdicts=("hit",),
    core_correct=True,
    required_atoms=(),
):
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
        "required_atoms": list(required_atoms),
        "reason_codes": [],
        "rationale": "测试理由",
        "confidence": 0.9,
    }


def test_strict_json_rejects_duplicate_keys():
    judge = load_judge()

    with pytest.raises(ValueError, match="Duplicate JSON key"):
        judge.strict_json_loads('{"verdict":"correct","verdict":"partial"}')


def test_judge_payload_normalizes_common_transport_variants():
    judge = load_judge()
    payload = judge_payload()
    payload.update(
        {
            "core_correct": "true",
            "ambiguous_question": "false",
            "evidence_sufficient_for_scoring": "true",
            "polarity": "N/A",
            "critical_conflicts": None,
            "required_atoms": None,
            "reason_codes": "normal",
            "confidence": "90%",
        }
    )
    payload["keypoint_verdicts"][0]["id"] = 1
    payload["keypoint_verdicts"][0]["evidence"] = None

    normalized = judge.normalize_judge_payload(
        judge.strict_json_loads(json.dumps({"judgment": payload}))
    )
    validated = judge.validate_judge_payload(normalized)

    assert validated["core_correct"] is True
    assert validated["polarity"] == "not_applicable"
    assert validated["required_atoms"] == []
    assert validated["reason_codes"] == ["normal"]
    assert validated["confidence"] == 0.9
    assert validated["keypoint_verdicts"][0]["id"] == "1"
    assert validated["keypoint_verdicts"][0]["evidence"] == ""


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


def test_supplementary_number_does_not_downgrade_complete_answer():
    judge = load_judge()
    verdict, signals = judge.deterministic_verdict(
        judge_payload(),
        "搭铁线的作用是什么？",
        "搭铁线用于连接电路和车身，长度规格为300mm。",
        "搭铁线用于连接电路和车身，使电流回路闭合。",
    )

    assert verdict == "correct"
    assert signals["atomic_consistency"] < 1.0
    assert signals["required_atomic_consistency"] == 1.0
    assert signals["manual_review_required"] is False


def test_required_atom_accepts_equivalent_unit():
    judge = load_judge()
    verdict, signals = judge.deterministic_verdict(
        judge_payload(required_atoms=("12V",)),
        "低压电源通常是多少伏？",
        "低压电源通常为12V蓄电池。",
        "低压电源通常为12伏蓄电池。",
    )

    assert verdict == "correct"
    assert signals["required_atomic_consistency"] == 1.0


def test_required_atom_mismatch_prevents_correct():
    judge = load_judge()
    verdict, signals = judge.deterministic_verdict(
        judge_payload(required_atoms=("12V",)),
        "低压电源通常是多少伏？",
        "低压电源通常为12V蓄电池。",
        "低压电源通常为24V蓄电池。",
    )

    assert verdict == "incorrect"
    assert signals["required_atomic_consistency"] == 0.0


def test_required_atoms_not_in_expected_answer_are_ignored():
    judge = load_judge()
    payload = judge_payload(required_atoms=("24V",))

    audit = judge.reconcile_required_atoms(
        payload,
        "低压电源通常为12V蓄电池。",
    )

    assert payload["required_atoms"] == []
    assert audit["rejected"] == ["24V"]
    assert audit["rejected_atoms"] == ["V:24"]


def test_non_atomic_required_entries_are_ignored():
    judge = load_judge()
    payload = judge_payload(required_atoms=("QVR型", "12V"))

    audit = judge.reconcile_required_atoms(
        payload,
        "普通低压导线绝缘层分为QVR型和QFR型，低压电源为12V。",
    )

    assert payload["required_atoms"] == ["12V"]
    assert audit["rejected"] == ["QVR型"]
    assert audit["rejected_atoms"] == []


def test_mixed_required_atom_entry_is_rejected_as_a_whole():
    judge = load_judge()
    payload = judge_payload(required_atoms=("12V和24V",))

    audit = judge.reconcile_required_atoms(
        payload,
        "低压电源通常为12V蓄电池。",
    )

    assert payload["required_atoms"] == []
    assert audit["rejected"] == ["12V和24V"]
    assert audit["rejected_atoms"] == ["V:24"]


def test_filtered_required_atom_conflict_cannot_be_correct():
    judge = load_judge()
    payload = judge_payload(required_atoms=("24V",))
    judge.reconcile_required_atoms(
        payload,
        "低压电源通常为12V蓄电池。",
    )

    verdict, signals = judge.deterministic_verdict(
        payload,
        "低压电源通常是多少伏？",
        "低压电源通常为12V蓄电池。",
        "低压电源通常为24V蓄电池。",
    )

    assert verdict == "incorrect"
    assert signals["rejected_atom_conflict"] is True
    assert signals["manual_review_required"] is True


def test_filtered_required_atoms_force_manual_review_without_conflict():
    judge = load_judge()
    payload = judge_payload(required_atoms=("QVR型",))
    judge.reconcile_required_atoms(
        payload,
        "普通低压导线绝缘层分为QVR型和QFR型。",
    )

    verdict, signals = judge.deterministic_verdict(
        payload,
        "普通低压导线绝缘层分哪两种？",
        "普通低压导线绝缘层分为QVR型和QFR型。",
        "普通低压导线绝缘层分为QVR型和QFR型。",
    )

    assert verdict == "correct"
    assert signals["required_atoms_filtered"] is True
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


def test_numeric_ranges_expand_both_bounds_with_shared_unit():
    judge = load_judge()

    assert judge.extract_atoms("0.5～16mm²") == {"MM:0.5", "MM:16"}
    assert judge.extract_atoms("-40～200℃") == {"℃:-40", "℃:200"}


def test_range_bound_matches_answer_without_repeating_lower_unit():
    judge = load_judge()
    verdict, signals = judge.deterministic_verdict(
        judge_payload(required_atoms=("0.5mm²", "16mm²")),
        "低压导线截面积范围是多少？",
        "低压导线截面积范围为0.5～16mm²。",
        "低压导线截面积范围为0.5~16mm²。",
    )

    assert verdict == "correct"
    assert signals["required_atomic_consistency"] == 1.0


def test_resume_does_not_skip_previous_judge_errors(tmp_path):
    judge = load_judge()
    path = tmp_path / "judgments.jsonl"
    path.write_text(
        '{"score_key":"k1","verdict":"judge_error"}\n'
        '{"score_key":"k2","verdict":"correct"}\n',
        encoding="utf-8",
    )

    records, completed = judge.load_existing_judgments(path)

    assert [record["score_key"] for record in records] == ["k2"]
    assert completed == {"k2"}


def test_ambiguous_judgment_can_have_no_keypoints():
    judge = load_judge()
    payload = {
        **judge_payload(),
        "core_correct": False,
        "ambiguous_question": True,
        "evidence_sufficient_for_scoring": False,
        "keypoint_verdicts": [],
    }

    validated = judge.validate_judge_payload(payload)
    verdict, signals = judge.deterministic_verdict(
        validated,
        "BCM功能有哪些？",
        "比亚迪秦EV的BCM功能包括……",
        "BCM功能包括……",
    )

    assert verdict == "unscorable_data"
    assert signals["manual_review_required"] is True
