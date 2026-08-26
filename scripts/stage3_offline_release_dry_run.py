#!/usr/bin/env python3
"""Fixture-only offline deployment and rollback state-machine dry run.

There are no subprocess, SSH, Docker, deployment-script, migration-runner, or
database calls in this module.  A fixture supplies the result for each state,
so every failure path is deterministic and can be tested without deployment.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable


FORWARD_STEPS = (
    "preflight", "backup_acknowledged", "migration_status_plan_verify", "candidate_import",
    "candidate_app_switch", "candidate_nginx_switch", "health_observation",
)
ROLLBACK_STEPS = ("rollback_app_switch", "rollback_nginx_switch", "rollback_health", "cleanup")
DEPLOYMENT_OR_HEALTH = frozenset({"candidate_import", "candidate_app_switch", "candidate_nginx_switch", "health_observation"})


def _event(step: str, status: str, code: str) -> dict[str, str]:
    return {"step": step, "status": status, "code": code}


def _valid_fixture(payload: dict[str, Any]) -> dict[str, bool]:
    outcomes = payload.get("outcomes")
    known = set(FORWARD_STEPS + ROLLBACK_STEPS)
    if not isinstance(outcomes, dict) or set(outcomes) - known or any(not isinstance(value, bool) for value in outcomes.values()):
        raise ValueError("DRYRUN_FIXTURE_INVALID")
    return {step: outcomes.get(step, True) for step in known}


def run_dry_run(payload: dict[str, Any]) -> dict[str, Any]:
    outcomes = _valid_fixture(payload)
    events: list[dict[str, str]] = []
    for step in FORWARD_STEPS:
        if outcomes[step]:
            events.append(_event(step, "passed", f"DRYRUN_{step.upper()}_PASSED"))
            continue
        events.append(_event(step, "failed", f"DRYRUN_{step.upper()}_FAILED"))
        if step not in DEPLOYMENT_OR_HEALTH:
            return {"status": "failed", "terminal": "hard-stop", "rollback_attempts": 0, "events": events}
        # Exactly one rollback transition follows an in-scope failed deploy or health step.
        for rollback_step in ROLLBACK_STEPS:
            if outcomes[rollback_step]:
                events.append(_event(rollback_step, "passed", f"DRYRUN_{rollback_step.upper()}_PASSED"))
                continue
            events.append(_event(rollback_step, "failed", f"DRYRUN_{rollback_step.upper()}_FAILED"))
            return {"status": "failed", "terminal": "rollback-hard-stop", "rollback_attempts": 1, "events": events}
        return {"status": "rolled-back", "terminal": "rollback-complete", "rollback_attempts": 1, "events": events}
    for step in ("cleanup",):
        if outcomes[step]:
            events.append(_event(step, "passed", f"DRYRUN_{step.upper()}_PASSED"))
            return {"status": "passed", "terminal": "complete", "rollback_attempts": 0, "events": events}
        events.append(_event(step, "failed", f"DRYRUN_{step.upper()}_FAILED"))
        return {"status": "failed", "terminal": "hard-stop", "rollback_attempts": 0, "events": events}
    raise AssertionError("unreachable")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True, help="required fixture JSON; this tool has no live mode")
    args = parser.parse_args(argv)
    try:
        result = run_dry_run(json.loads(args.fixture.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError):
        result = {"status": "failed", "terminal": "hard-stop", "code": "DRYRUN_FIXTURE_INVALID"}
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result["status"] in {"passed", "rolled-back"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
