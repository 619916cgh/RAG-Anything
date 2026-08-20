## ADDED Requirements

### Requirement: Isolated Profile B capacity ladder
The harness SHALL define Profile B as one disposable mock-backed application process limited to four CPU and six GiB, with one server worker and four fixed `MAX_ASYNC` LLM slots, behind the existing loopback Nginx topology. It SHALL record a content-free configuration fingerprint and keep Profile A results and gates distinct. Profile B SHALL run only the ordered stages `1`, `5`, `10`, `20`, `30`, `40`, and `50` VU, with a new manifest-owned isolated stack for every stage.

#### Scenario: Profile B stage starts
- **WHEN** the runner is asked to start a Profile B stage
- **THEN** it SHALL refuse any stage outside the ordered allowlist or any later stage whose preceding Profile B stage did not pass and complete recovery and cleanup with the same Profile B configuration fingerprint

#### Scenario: Profile A result exists
- **WHEN** a Profile A CPU-gate result is present
- **THEN** the harness SHALL retain it as `profile_a_standard_gate_failed` and SHALL NOT use it to pass, fail, or skip any Profile B rung

#### Scenario: Explicit direct 50 VU diagnostic is requested
- **WHEN** an explicitly authorized Profile B direct diagnostic requests stage `50` with no predecessor evidence
- **THEN** the harness SHALL create a fresh isolated stack with execution mode `direct-50-diagnostic` and the explicitly authorized 8C32G diagnostic envelope of 8 CPU, 24 GiB application memory, and `MAX_ASYNC=8`, retain all normal preflight, SSE, latency, resource, recovery, cleanup, and permitted production-probe gates, and classify its result only as `profile_b_direct_diagnostic_completed` or `profile_b_direct_diagnostic_hard_stop`
- **AND THEN** it SHALL mark the report ineligible for the ordered ladder, SHALL reject it as continuation evidence, and SHALL NOT launch or unlock any later stage

#### Scenario: An unapproved or non-50 direct diagnostic is requested
- **WHEN** a direct diagnostic omits explicit authorization, includes predecessor evidence, or requests a stage other than `50`
- **THEN** the harness SHALL refuse before creating isolated resources

### Requirement: Profile B preflight and risk gates
Before each Profile B stage, the harness SHALL verify the immutable test image preflight, a minimum of 16 GiB available host memory, 40 GiB free host disk, manifest-owned resource absence, per-VU retrieval readiness with non-empty sources, and only the allowed read-only production probes. During a maximum 90-second stage with five-second samples, it SHALL stop new load and classify the stage as `profile_b_hard_stop` for any non-successful SSE terminal result, timeout, unexpected 429, 5xx, SSE trace violation, retry, OOM, restart, ownership failure, host-gate breach, queue age above 120 seconds, or production-probe regression.

#### Scenario: Quota-relative resource threshold is crossed
- **WHEN** application CPU exceeds 75 percent of the four-CPU quota for three consecutive samples, reaches 90 percent of that quota on one sample, RSS exceeds 70 percent of six GiB for three consecutive samples, or reaches 80 percent on one sample
- **THEN** the harness SHALL stop the current rung within one sampling interval and SHALL NOT start a later rung

#### Scenario: A stage satisfies all acceptance gates
- **WHEN** every stage request reaches the expected bounded SSE terminal sequence with no error classification, TTFT P95 is at most 2.1 seconds, complete-response P95 is at most 2.7 seconds, and no hard stop occurs
- **THEN** the harness SHALL classify that rung as `profile_b_stage_passed` and begin recovery collection instead of immediately advancing; per-request streams SHALL retain their bounded accepted-first terminal protocol, while non-empty retrieval sources are proven by the required per-VU readiness gate before the stage

#### Scenario: A conflicting Profile B stack exists
- **WHEN** another running manifest-labelled Profile B test stack exists before preflight
- **THEN** the harness SHALL refuse the new stage before creating resources and SHALL emit only content-free phase progress markers for read-only monitoring

#### Scenario: Redacted event preview reaches its storage cap
- **WHEN** a valid stream has more event classes than the retained redacted preview can store
- **THEN** the harness SHALL validate the complete stream with aggregate protocol state and SHALL NOT classify preview truncation alone as a protocol failure

### Requirement: Recovery, evidence, and production isolation
After every Profile B stage, the harness SHALL collect ten minutes of recovery evidence before tearing down only resources verified by the manifest ID, run label, and Compose project label. It SHALL separately classify query-gate and recovery-collector outcomes, and recovery pass SHALL require exactly 120 host and healthy permitted-production-probe samples, one clean collection summary, and no resource stop. It SHALL emit only sanitized per-rung resource, timing, terminal classification, fixed recovery-failure category, probe, and cleanup evidence. A Profile B result SHALL be limited to the exact mock-backed, single-process resource profile and SHALL NOT establish production capacity, a production SLO, real-model behavior, browser behavior, Worker capacity, multi-instance behavior, or authorization to deploy.

#### Scenario: Recovery and cleanup complete
- **WHEN** a rung ends without a hard stop and ten minutes of recovery retain healthy permitted production probes with no owned restart or OOM
- **THEN** the harness SHALL persist sanitized evidence, remove only triple-verified owned temporary resources, and permit the next ordered rung

#### Scenario: Production isolation is challenged
- **WHEN** a runner operation would read or mutate production configuration, credentials, database, volumes, logs, processes, model endpoints, or data
- **THEN** the harness SHALL refuse that operation and leave the production target untouched
