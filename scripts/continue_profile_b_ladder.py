"""Continue approved Profile B rungs only after explicit sanitized evidence."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


STAGES = (5, 10, 20, 30, 40, 50)


def _passed_report(path: Path, expected_stage: int) -> bool:
    payload = json.loads(path.read_text(encoding="utf-8"))
    result = payload.get("profile_b_result") or {}
    return (
        payload.get("resource_profile") == "profile-b"
        and payload.get("profile_b_execution_mode") == "ordered-ladder"
        and payload.get("profile_b_stage") == expected_stage
        and payload.get("cleanup_verified") is True
        and result.get("classification") == "profile_b_stage_passed"
        and result.get("recovery_passed") is True
    )


def _wait_for_report(path: Path, stage: int, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Profile B stage {stage} report did not arrive")
        time.sleep(5)
    if not _passed_report(path, stage):
        raise RuntimeError(f"Profile B stage {stage} did not pass")


def _new_report(report_root: Path, before: set[Path], stage: int) -> Path:
    candidates = [path for path in report_root.glob("*.json") if path not in before]
    if len(candidates) != 1 or not _passed_report(candidates[0], stage):
        raise RuntimeError(f"Profile B stage {stage} did not produce one passing report")
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-image", required=True)
    parser.add_argument("--report-root", type=Path, required=True)
    parser.add_argument("--predecessor", type=Path, required=True)
    parser.add_argument("--predecessor-stage", type=int, choices=(1, 5, 10, 20, 30, 40), required=True)
    parser.add_argument("--stages", type=int, choices=STAGES, nargs="+", default=list(STAGES))
    parser.add_argument("--wait-seconds", type=int, default=1800)
    args = parser.parse_args()

    _wait_for_report(args.predecessor, args.predecessor_stage, args.wait_seconds)
    root = Path(__file__).resolve().parents[1]
    runner = root / "scripts" / "run_profile_b_ladder.py"
    predecessor = args.predecessor
    for stage in args.stages:
        before = set(args.report_root.glob("*.json"))
        subprocess.run(
            [sys.executable, str(runner), "--stage", str(stage), "--app-image", args.app_image,
             "--report-root", str(args.report_root), "--predecessor", str(predecessor)],
            check=True,
        )
        predecessor = _new_report(args.report_root, before, stage)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
