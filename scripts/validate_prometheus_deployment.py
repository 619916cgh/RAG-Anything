#!/usr/bin/env python3
"""Validate the credential-free release monitoring contract.

The script is intentionally static: staging must still prove that each target
is reachable and that Alertmanager receives a test alert before rules are
enabled for an environment.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


REQUIRED_JOBS = {"raganything", "postgres", "redis", "node", "backup", "tls"}


def validate_inventory(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    jobs = {line.split(":", 1)[1].strip() for line in text.splitlines() if line.lstrip().startswith("- job_name:")}
    missing = REQUIRED_JOBS - jobs
    if missing:
        raise ValueError(f"scrape inventory missing jobs: {', '.join(sorted(missing))}")
    if any(token in text.lower() for token in ("password", "token", "authorization:")):
        raise ValueError("scrape inventory must not contain credentials")
    for job in REQUIRED_JOBS:
        if f"job_name: {job}" not in text or "target_owner:" not in text:
            raise ValueError(f"scrape inventory lacks target owner for {job}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--promtool", default=shutil.which("promtool"))
    args = parser.parse_args()
    deploy = args.root / "deploy" / "prometheus"
    inventory = deploy / "release-scrape-inventory.yml"
    rules = deploy / "release-operations-alerts.yml"
    validate_inventory(inventory)
    if args.promtool:
        for command, path in (("check config", inventory), ("check rules", rules)):
            subprocess.run([args.promtool, *command.split(), str(path)], check=True)
    print("Prometheus release inventory is structurally valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
