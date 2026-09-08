from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]
HANDOFF = ROOT / "openspec" / "changes" / "video-semantic-segment-index" / "handoff.md"

BEHAVIOR = "ac5a35cac6de33747755bac1b8fa3c4b3ebdbab2"
SOURCE = "3dd1bc14194b0348fb3ad1ed51b536085fa6b2c8"
INITIAL = "e1739d48b77a309552eb1f5f55d8ad27a204beed"
ANCHOR = "51b2264f29299f6311873f429a824ca7754434bf"
PROHIBITED = "b10c1af185c9fd11eee60ea1c5e5a5972a4ab467"
INITIAL_PATHS = [
    "handoff-video54-sse-body-ownership-20260901.md",
    "handoff-video54-sse-manifest-repair-20260901.md",
    "scripts/run_isolated_acceptance.py",
    "summary-delta-video54-sse-body-ownership-20260901.md",
    "summary-delta-video54-sse-manifest-repair-20260901.md",
    "tests/acceptance/compose.yml",
    "tests/acceptance/generate_video_fixture.py",
    "tests/acceptance/video_browser_uat.mjs",
    "tests/test_video_acceptance_contract.py",
]


def _contract() -> dict[str, object]:
    content = HANDOFF.read_text(encoding="utf-8")
    start = content.index("```json\n") + len("```json\n")
    end = content.index("\n```", start)
    return json.loads(content[start:end])


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="strict",
        capture_output=True,
        check=False,
    )


def _git_stdout(*args: str) -> str:
    result = _git(*args)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_video54_verification_handoff_is_git_derived_and_fail_closed():
    contract = _contract()
    identities = contract["identities"]
    assert isinstance(identities, dict)
    assert contract["schema_version"] == 1
    assert contract["status"] == "governance-only"
    assert identities["behavior_baseline"]["sha"] == BEHAVIOR
    assert identities["verification_source"]["sha"] == SOURCE
    assert identities["initial_verification"]["sha"] == INITIAL
    assert identities["shared_lineage_anchor"]["sha"] == ANCHOR

    for sha in (BEHAVIOR, SOURCE, INITIAL, ANCHOR, PROHIBITED):
        assert _git("cat-file", "-e", f"{sha}^{{commit}}").returncode == 0

    ancestry = contract["ancestry"]
    assert isinstance(ancestry, dict)
    assert _git_stdout("merge-base", BEHAVIOR, INITIAL) == BEHAVIOR
    assert _git_stdout("merge-base", SOURCE, INITIAL) == ANCHOR
    assert _git_stdout("merge-base", BEHAVIOR, SOURCE) == ANCHOR
    assert ancestry == {
        "behavior_to_initial_merge_base": BEHAVIOR,
        "source_to_initial_merge_base": ANCHOR,
        "behavior_to_source_merge_base": ANCHOR,
        "behavior_is_initial_ancestor": True,
        "source_is_initial_ancestor": False,
    }
    assert _git("merge-base", "--is-ancestor", BEHAVIOR, INITIAL).returncode == 0
    assert _git("merge-base", "--is-ancestor", SOURCE, INITIAL).returncode == 1

    git_paths = sorted(
        path
        for path in _git_stdout("diff", "--name-only", f"{BEHAVIOR}..{INITIAL}").splitlines()
        if path
    )
    assert git_paths == INITIAL_PATHS
    assert contract["initial_verification_paths"] == INITIAL_PATHS
    assert len(git_paths) == len(set(git_paths)) == 9

    candidate = contract["candidate_construction"]
    assert isinstance(candidate, dict)
    assert candidate["candidate_created_by_this_handoff"] is False
    assert candidate["governance_commit_is_candidate"] is False
    assert candidate["only_approved_candidate_sha"] == INITIAL
    assert candidate["expanded_candidate_scope"] == (
        "not authorized; a different candidate or any additional path requires a separately authorized replacement contract"
    )

    history = contract["historical_exclusions"]
    assert isinstance(history, dict)
    assert history["non_authoritative_intermediate_commits"] == [
        "7a2f80f1821af4e6d7a0cbe5452bf5088b84484f",
        "ebe60a55c8a8d6584adcdf3e02fdd9b6835a2e3f",
    ]
    assert history["prohibited_reuse_commits"] == [PROHIBITED]
    assert history["historical_root_handoffs_are_evidence_only"] is True
    assert "An expanded candidate scope or runtime action is attempted without a separately authorized replacement contract." in contract["fail_closed_conditions"]
