# Video 5.4 Verification Contract Handoff

Status: `CONTRACT_ESTABLISHED` on 2026-09-08. This is a governance-only
handoff. It creates no candidate and authorizes no runtime work.

## Authoritative Contract

The JSON block below is the single current-tree authority for this contract.
Its values are verified from immutable Git objects, not inferred from the
current runner literal or a historical Run.

```json
{
  "schema_version": 1,
  "contract_id": "video54-verification-contract-20260908",
  "status": "governance-only",
  "identities": {
    "behavior_baseline": {
      "sha": "ac5a35cac6de33747755bac1b8fa3c4b3ebdbab2",
      "role": "approved behavior baseline and required ancestor of the initial verification identity"
    },
    "verification_source": {
      "sha": "3dd1bc14194b0348fb3ad1ed51b536085fa6b2c8",
      "role": "historical verification provenance and merge-base witness; not a candidate ancestor"
    },
    "initial_verification": {
      "sha": "e1739d48b77a309552eb1f5f55d8ad27a204beed",
      "role": "only approved initial verification identity"
    },
    "shared_lineage_anchor": {
      "sha": "51b2264f29299f6311873f429a824ca7754434bf",
      "role": "common ancestor for behavior baseline and verification source, and source-to-initial merge-base"
    }
  },
  "ancestry": {
    "behavior_to_initial_merge_base": "ac5a35cac6de33747755bac1b8fa3c4b3ebdbab2",
    "source_to_initial_merge_base": "51b2264f29299f6311873f429a824ca7754434bf",
    "behavior_to_source_merge_base": "51b2264f29299f6311873f429a824ca7754434bf",
    "behavior_is_initial_ancestor": true,
    "source_is_initial_ancestor": false
  },
  "initial_verification_paths": [
    "handoff-video54-sse-body-ownership-20260901.md",
    "handoff-video54-sse-manifest-repair-20260901.md",
    "scripts/run_isolated_acceptance.py",
    "summary-delta-video54-sse-body-ownership-20260901.md",
    "summary-delta-video54-sse-manifest-repair-20260901.md",
    "tests/acceptance/compose.yml",
    "tests/acceptance/generate_video_fixture.py",
    "tests/acceptance/video_browser_uat.mjs",
    "tests/test_video_acceptance_contract.py"
  ],
  "candidate_construction": {
    "candidate_created_by_this_handoff": false,
    "governance_commit_is_candidate": false,
    "only_approved_candidate_sha": "e1739d48b77a309552eb1f5f55d8ad27a204beed",
    "checkout_requirements": [
      "full 40-character commit SHA",
      "clean detached checkout with HEAD equal to the approved candidate SHA"
    ],
    "identity_requirements": [
      "git merge-base behavior_baseline candidate equals behavior_baseline",
      "git merge-base verification_source candidate equals shared_lineage_anchor",
      "git diff --name-only behavior_baseline..candidate equals initial_verification_paths"
    ],
    "expanded_candidate_scope": "not authorized; a different candidate or any additional path requires a separately authorized replacement contract"
  },
  "historical_exclusions": {
    "non_authoritative_intermediate_commits": [
      "7a2f80f1821af4e6d7a0cbe5452bf5088b84484f",
      "ebe60a55c8a8d6584adcdf3e02fdd9b6835a2e3f"
    ],
    "prohibited_reuse_commits": [
      "b10c1af185c9fd11eee60ea1c5e5a5972a4ab467"
    ],
    "historical_root_handoffs_are_evidence_only": true
  },
  "scope_exclusions": [
    "No runner implementation, product code, frontend code, migrations, database state, AGENTS.md, or PROJECT_SUMMARY.md change is authorized.",
    "No candidate, Docker or Compose resource, PostgreSQL instance, Run, Browser profile, Worker, Agent, thread, or query is created or started.",
    "This handoff and its contract test are governance artifacts and are not members of initial_verification_paths.",
    "No path deletion, scope relaxation, ancestry bypass, historical rewrite, or reuse of a prohibited commit resolves a conflict."
  ],
  "fail_closed_conditions": [
    "Any identity is unavailable or is not a commit.",
    "Any required merge-base value or ancestor assertion differs.",
    "The Git-derived initial path set is not exactly initial_verification_paths, including a missing, extra, or duplicate path.",
    "A current runner literal, historical Run, or historical root handoff is used to replace an authoritative field.",
    "The selected candidate is not exactly only_approved_candidate_sha, is not a clean detached checkout, or includes any governance artifact in its candidate diff.",
    "An expanded candidate scope or runtime action is attempted without a separately authorized replacement contract.",
    "Any non_authoritative_intermediate_commits or prohibited_reuse_commits value is substituted for an identity or candidate."
  ]
}
```

## Git Evidence And Semantics

Run these checks against the immutable objects before any later candidate
selection:

```powershell
git cat-file -e ac5a35cac6de33747755bac1b8fa3c4b3ebdbab2^{commit}
git cat-file -e 3dd1bc14194b0348fb3ad1ed51b536085fa6b2c8^{commit}
git cat-file -e e1739d48b77a309552eb1f5f55d8ad27a204beed^{commit}
git cat-file -e 51b2264f29299f6311873f429a824ca7754434bf^{commit}
git merge-base ac5a35cac6de33747755bac1b8fa3c4b3ebdbab2 e1739d48b77a309552eb1f5f55d8ad27a204beed
git merge-base 3dd1bc14194b0348fb3ad1ed51b536085fa6b2c8 e1739d48b77a309552eb1f5f55d8ad27a204beed
git merge-base ac5a35cac6de33747755bac1b8fa3c4b3ebdbab2 3dd1bc14194b0348fb3ad1ed51b536085fa6b2c8
git diff --name-only ac5a35cac6de33747755bac1b8fa3c4b3ebdbab2..e1739d48b77a309552eb1f5f55d8ad27a204beed
```

The resulting merge-bases are, respectively, behavior baseline, shared
lineage anchor, and shared lineage anchor. `verification_source` is therefore
not an ancestor of `initial_verification`; treating it as one is a contract
failure, not a reason to merge or rewrite history.

The nine paths are derived only from the final `git diff --name-only` command.
The current runner literal is not an authority for this handoff: it contains
extra browser package paths that are absent from this immutable diff. Earlier
root handoffs contain older intermediate identities and one historical typo,
so they remain evidence only.

## Boundary And Coordinator Delta

No runtime evidence was created or re-used. This does not advance OpenSpec task
5.4, establish Worker, Browser, Docker, PostgreSQL, Provider, or production
acceptance, or authorize a bounded retry. The coordinator may later add this
governance conclusion to `PROJECT_SUMMARY.md`; this task intentionally leaves
that serially owned file unchanged.
