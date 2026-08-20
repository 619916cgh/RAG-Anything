"""Small, dependency-free guards shared by the Linux cloud perf runner and tests."""
from __future__ import annotations

import argparse
import json
import pstats
import re
import sys
from collections import Counter
from pathlib import Path


def assert_temp_child(temp_root: str, candidate: str) -> Path:
    parent = Path(temp_root).resolve()
    resolved = Path(candidate).resolve()
    if resolved == parent or parent not in resolved.parents:
        raise ValueError("run directory must be below the system temporary directory")
    return resolved


def assert_ownership(project: str, run_id: str, labels: str) -> None:
    values = labels.split()
    if values != [project, run_id]:
        raise ValueError("resource ownership labels do not match the manifest")


_STACK_FRAME = re.compile(r'File "(/app/[^\"]+)", line \d+ in ([^\r\n]+)')


def summarize_stack_profile(raw: str) -> dict[str, object]:
    """Reduce faulthandler output to code locations without log payloads."""
    frames = Counter(
        f"{path.removeprefix('/app/')}:{function.strip()}"
        for path, function in _STACK_FRAME.findall(raw)
    )
    return {
        "snapshot_count": raw.count("Current thread"),
        "frames": [
            {"location": location, "samples": samples}
            for location, samples in frames.most_common(80)
        ],
    }


def summarize_cpu_profile(profile_path: Path) -> dict[str, object]:
    """Publish app-only aggregate cProfile locations without source content."""
    frames: list[dict[str, object]] = []
    stats = pstats.Stats(str(profile_path)).stats
    for (path, _line, function), (primitive, total, tottime, cumulative, _callers) in stats.items():
        if not path.startswith("/app/"):
            continue
        frames.append({
            "location": f"{path.removeprefix('/app/')}:{function}",
            "calls": int(total),
            "primitive_calls": int(primitive),
            "self_seconds": round(float(tottime), 6),
            "cumulative_seconds": round(float(cumulative), 6),
        })
    frames.sort(key=lambda item: (-float(item["self_seconds"]), str(item["location"])))
    return {
        "frame_count": len(frames),
        "frames": frames[:80],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    child = subparsers.add_parser("assert-temp-child")
    child.add_argument("temp_root")
    child.add_argument("candidate")
    owner = subparsers.add_parser("assert-ownership")
    owner.add_argument("project")
    owner.add_argument("run_id")
    owner.add_argument("labels")
    profile = subparsers.add_parser("summarize-stack-profile")
    profile.add_argument("--output", required=True)
    profile.add_argument("--container", required=True)
    profile.add_argument("--run-id", required=True)
    profile.add_argument("--started-at", required=True)
    profile.add_argument("--finished-at", required=True)
    profile.add_argument("--signals", required=True, type=int)
    cpu_profile = subparsers.add_parser("summarize-cpu-profile")
    cpu_profile.add_argument("--output", required=True)
    cpu_profile.add_argument("--container", required=True)
    cpu_profile.add_argument("--run-id", required=True)
    cpu_profile.add_argument("--image-id", required=True)
    cpu_profile.add_argument("--started-at", required=True)
    cpu_profile.add_argument("--finished-at", required=True)
    cpu_profile.add_argument("--input", required=True)
    args = parser.parse_args()
    if args.command == "assert-temp-child":
        assert_temp_child(args.temp_root, args.candidate)
    elif args.command == "assert-ownership":
        assert_ownership(args.project, args.run_id, args.labels)
    elif args.command == "summarize-stack-profile":
        payload = summarize_stack_profile(sys.stdin.read())
        payload.update({
            "container": args.container,
            "run_id": args.run_id,
            "started_at": args.started_at,
            "finished_at": args.finished_at,
            "signals_sent": args.signals,
            "available": bool(payload["snapshot_count"]),
        })
        Path(args.output).write_text(
            json.dumps(payload, ensure_ascii=True, sort_keys=True), encoding="utf-8"
        )
    else:
        payload = summarize_cpu_profile(Path(args.input))
        payload.update({
            "container": args.container,
            "run_id": args.run_id,
            "app_image_id": args.image_id,
            "started_at": args.started_at,
            "finished_at": args.finished_at,
            "available": bool(payload["frame_count"]),
        })
        Path(args.output).write_text(
            json.dumps(payload, ensure_ascii=True, sort_keys=True), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
