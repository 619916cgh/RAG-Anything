import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { chromium } from 'playwright-core'

const base = process.env.VIDEO_BROWSER_BASE_URL || ''
const accountsPath = process.env.VIDEO_BROWSER_ACCOUNTS_PATH || ''
const evidencePath = process.env.VIDEO_BROWSER_EVIDENCE_PATH || ''
const fixture = process.env.VIDEO_BROWSER_FIXTURE || ''
const compatibilityFixtures = (process.env.VIDEO_BROWSER_COMPAT_FIXTURES || '').split(',').filter(Boolean)
const legacyResourcePath = process.env.VIDEO_BROWSER_LEGACY_RESOURCE_PATH || ''
const citationDiagnosisOnly = process.env.VIDEO_BROWSER_CITATION_DIAGNOSIS_ONLY === '1'
const citationResourcePath = process.env.VIDEO_BROWSER_CITATION_RESOURCE_PATH || ''
const uploadDiagnosisMode = process.env.VIDEO_BROWSER_UPLOAD_DIAGNOSIS === '1'
const viewports = {
  desktop: { width: 1440, height: 900 },
  mobile: { width: 390, height: 844, isMobile: true },
}
let currentStage = 'bootstrap'
let citationDiagnosis = null
let apiResourceParity = null
let threadNavigationDiagnosis = null
let citationOnlyState = null
let phaseAEvidence = null
let setupNavigationObservation = null

const OBSERVATION_SAMPLE_LIMIT = 8
const OBSERVATION_TEXT_LIMIT = 320
const OBSERVATION_STACK_LIMIT = 1_200

const PHASE_A_FAILURE_CLASSES = new Set([
  'navigation', 'query_submit', 'sse_response', 'sse_body', 'sse_framing', 'sse_json', 'sse_done',
  'persisted_conversation', 'persisted_assistant', 'persisted_citation', 'assistant_dom', 'citation_dom', 'player_dom', 'visibility', 'reload', 'media', 'range',
  'upload_progress_locator_no_match', 'upload_progress_locator_multiple_match',
])

const HARNESS_OWNED_FAILURE_CLASSES = new Set([
  'upload_progress_locator_no_match',
  'upload_progress_locator_multiple_match',
])

const PHASE_A_STAGES = [
  'navigation', 'query_submit', 'sse_response', 'sse_body', 'sse_framing', 'sse_json', 'sse_done',
  'persisted_conversation', 'persisted_assistant', 'persisted_citation', 'assistant_dom', 'citation_dom', 'player_dom', 'visibility', 'reload', 'media', 'range',
]

const CITATION_PROBE_PHASES = [
  'query_submit_started',
  'query_submit_completed',
  'target_query_identity_observed',
  'response_wait_started',
  'response_received',
  'response_status',
  'response_content_type',
  'body_read_started',
  'body_read_completed',
  'body_read_error_class',
  'body_byte_count',
  'request_finished',
  'request_failed',
  'done_received',
  'done_thread_matches_target',
  'done_citation_count',
  'response_body_read_started',
  'response_body_read_completed',
  'response_body_byte_count',
  'sse_event_framing',
  'sse_line_count',
  'sse_data_line_count',
  'sse_json_parse_error_count',
  'stream_response_started',
  'stream_response_completed',
  'sse_done_received',
  'sse_done_thread_matches_target',
  'sse_done_citation_count',
  'streaming_assistant_found',
  'streaming_citation_found',
  'streaming_video_player_found',
  'player_visible',
  'persisted_conversation_get',
  'persisted_assistant_found',
  'persisted_video_segments_found',
  'reload_started',
  'reload_completed',
  'reloaded_player_visible',
  'authorized_media_status',
  'range_status',
  'timeout_stage',
  'failure_class',
]

const THREAD_NAVIGATION_FAILURE_CLASSES = new Set([
  'goto_timeout',
  'detail_response_timeout',
  'conversation_locator_timeout',
  'active_thread_mismatch',
  'target_response_timeout',
  'target_active_thread_timeout',
  'decoy_response_timeout',
  'stale_state_assertion',
  'reload_detail_timeout',
  'stale_response_overwrite',
  'unknown',
])

const CITATION_DIAGNOSIS_CLASSES = new Set([
  'query_not_started',
  'stream_not_completed',
  'stream_citation_state_missing',
  'persisted_refresh_overwrite',
  'locator_binding_mismatch',
  'player_render_missing',
  'legacy_contract_mismatch',
  'nonvideo_player_leak',
  'no_sse_done',
  'done_without_citations',
  'citations_without_video_segments',
  'conversation_get_failure',
  'persisted_assistant_missing',
  'persisted_citations_missing',
  'persisted_video_segments_missing',
  'video_player_props_mismatch',
  'conversation_refresh_loss',
  'session_auth_mismatch',
  'frontend_render_mismatch',
  'harness_contract_mismatch',
  'persisted_query_identity_mismatch',
])

function stage(prefix, suffix) {
  currentStage = `${prefix}-${suffix}`
  if (phaseAEvidence) phaseAEvidence.current_stage = currentStage
  if (setupNavigationObservation) setupNavigationObservation.current_stage = currentStage
}

function updateCurrentStage(value) {
  currentStage = value
  if (phaseAEvidence) phaseAEvidence.current_stage = currentStage
  if (setupNavigationObservation) setupNavigationObservation.current_stage = currentStage
}

function safeLocation(rawUrl) {
  try {
    const url = new URL(String(rawUrl || ''), base || undefined)
    let pathname = url.pathname || '/'
    pathname = pathname.replace(/^\/agents\/[^/]+/, '/agents/:agent')
    pathname = pathname.replace(/\/conversations\/[^/]+/g, '/conversations/:thread')
    return { origin: url.origin === 'null' ? '' : url.origin, pathname }
  } catch {
    return { origin: '', pathname: '' }
  }
}

function sanitizeObservationText(value, limit = OBSERVATION_TEXT_LIMIT) {
  let text = String(value || '')
  text = text.replace(/https?:\/\/[^\s'"<>]+/gi, match => {
    const location = safeLocation(match)
    return location.origin ? `${location.origin}${location.pathname}` : '[url]'
  })
  text = text.replace(/\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+/gi, '$1 [redacted]')
  text = text.replace(/([?&;\s,](?:access_?token|authorization|cookie|password|refresh_?token|secret|token|jwt)=)[^&\s,;]+/gi, '$1[redacted]')
  text = text.replace(/(["'](?:access_?token|authorization|cookie|password|refresh_?token|secret|token|jwt)["']\s*:\s*["'])[^"']*/gi, '$1[redacted]')
  return text.replace(/[\r\n\t]+/g, ' ').slice(0, limit)
}

function shortAutomationError(error) {
  return {
    name: sanitizeObservationText((error && error.name) || 'Error', 80),
    message: sanitizeObservationText((error && error.message) || '', OBSERVATION_TEXT_LIMIT),
    stack: sanitizeObservationText((error && error.stack) || '', OBSERVATION_STACK_LIMIT),
  }
}

function appendObservationSample(samples, value) {
  if (samples.length < OBSERVATION_SAMPLE_LIMIT) samples.push(value)
}

function createSetupNavigationObservation() {
  return {
    current_stage: currentStage,
    target_url: { origin: '', pathname: '' },
    final_location: { origin: '', pathname: '' },
    navigation: { response_count: 0, responses: [], redirect_count: 0, redirects: [], goto_status: 0 },
    client: {
      console_error_count: 0, console_errors: [], page_error_count: 0, page_errors: [],
      request_failed_count: 0, request_failed: [],
    },
    automation_error: null,
    artifacts: {
      screenshot: { generated: false, path: '' },
      html: { generated: false, reason: 'not-captured-no-redaction-guarantee' },
      trace: { generated: false, reason: 'not-captured-no-redaction-guarantee' },
    },
  }
}

function installSetupNavigationObservability(page, observation) {
  const onResponse = response => {
    try {
      const request = response.request()
      if (!request.isNavigationRequest()) return
      observation.navigation.response_count = boundedCount(observation.navigation.response_count + 1)
      appendObservationSample(observation.navigation.responses, {
        url: safeLocation(response.url()), status: boundedCount(response.status()),
      })
      const previous = request.redirectedFrom()
      if (previous) {
        observation.navigation.redirect_count = boundedCount(observation.navigation.redirect_count + 1)
        appendObservationSample(observation.navigation.redirects, {
          from: safeLocation(previous.url()), to: safeLocation(request.url()), status: boundedCount(response.status()),
        })
      }
    } catch { /* diagnostics must not affect the navigation under test */ }
  }
  const onConsole = message => {
    if (message.type() !== 'error') return
    observation.client.console_error_count = boundedCount(observation.client.console_error_count + 1)
    appendObservationSample(observation.client.console_errors, sanitizeObservationText(message.text()))
  }
  const onPageError = error => {
    observation.client.page_error_count = boundedCount(observation.client.page_error_count + 1)
    appendObservationSample(observation.client.page_errors, sanitizeObservationText((error && error.message) || error))
  }
  const onRequestFailed = request => {
    observation.client.request_failed_count = boundedCount(observation.client.request_failed_count + 1)
    appendObservationSample(observation.client.request_failed, {
      url: safeLocation(request.url()), reason: sanitizeObservationText(request.failure()?.errorText || ''),
    })
  }
  page.on('response', onResponse)
  page.on('console', onConsole)
  page.on('pageerror', onPageError)
  page.on('requestfailed', onRequestFailed)
  return () => {
    page.off('response', onResponse)
    page.off('console', onConsole)
    page.off('pageerror', onPageError)
    page.off('requestfailed', onRequestFailed)
  }
}

async function captureSetupNavigationFailure(page, inputs, observation) {
  if (!page || !inputs?.runRoot) return
  try {
    const artifactDir = path.join(inputs.runRoot, 'navigation-evidence')
    const screenshotPath = path.join(artifactDir, 'navigation-failure.png')
    fs.mkdirSync(artifactDir, { recursive: true })
    assertExistingRunOwnedPath(inputs.runRoot, artifactDir, 'navigation-evidence')
    await page.screenshot({ path: screenshotPath, fullPage: false })
    observation.artifacts.screenshot = { generated: true, path: 'navigation-evidence/navigation-failure.png' }
  } catch {
    observation.artifacts.screenshot = { generated: false, path: '' }
  }
}

function matrixObservation({ role, viewport, path, fields = {} }) {
  return {
    role,
    viewport,
    path,
    passed: true,
    failure_class: null,
    query_started: true,
    stream_completed: true,
    stream_citation_state_present: true,
    persisted_refresh_preserved: true,
    locator_binding_matches: true,
    player_rendered: true,
    legacy_contract_ok: true,
    nonvideo_player_absent: true,
    citation_count: 0,
    video_segment_count: 0,
    player_count: 0,
    range_label_count: 0,
    ...fields,
  }
}

function fail(code) {
  const normalized = String(code || 'browser-uat-failed').replace(/^browser-/, '')
  const failureClass = currentStage.startsWith('browser-')
    ? `${currentStage}-${normalized}`
    : normalized
  const error = new Error(failureClass)
  error.code = failureClass
  throw error
}

function writeEvidence(payload) {
  const safePayload = {
    ...payload,
    ...(apiResourceParity ? { api_resource_parity: apiResourceParity } : {}),
    ...(citationDiagnosis ? { citation_diagnosis: citationDiagnosis } : {}),
    ...(threadNavigationDiagnosis ? { thread_navigation_contract: threadNavigationDiagnosis } : {}),
  }
  fs.writeFileSync(evidencePath, JSON.stringify(safePayload, null, 2), 'utf8')
}

function writeCitationOnlyFallback(failureClass) {
  if (!citationOnlyMode() || !evidencePath || citationOnlyState?.written) return
  const state = citationOnlyState || {}
  const probe = state.probe || createCitationProbe()
  setCitationProbeFailure(probe, 'failure_class', failureClass)
  try {
    writeEvidence({
      schema_version: 3,
      browser: 'playwright',
      browser_citation_only: true,
      run_id: String(state.inputs?.runId || process.env.VIDEO_BROWSER_CITATION_RUN_ID || ''),
      owner: String(state.inputs?.owner || process.env.VIDEO_BROWSER_CITATION_OWNER || ''),
      compose_project: String(state.inputs?.composeProject || process.env.VIDEO_BROWSER_CITATION_COMPOSE_PROJECT || ''),
      runtime_status: 'run_failed',
      browser_profile: state.profile || { created: false, used: false, context_closed: false, cleaned: false },
      browser_fixture: { owned_by_run: true, created: true },
      old_run_evidence_used_as_result: false,
      probe_process_created_docker_resources: 0,
      citation_probe: probe,
    })
    if (citationOnlyState) citationOnlyState.written = true
  } catch {
    // A write failure stays a runner-classified, path-free harness failure.
  }
}

function boundedCount(value) {
  return Math.max(0, Math.min(999, Number.isInteger(value) ? value : 0))
}

function phaseAFailureClass(error) {
  const code = String(error?.code || '')
  for (const failureClass of HARNESS_OWNED_FAILURE_CLASSES) {
    if (code.endsWith(`-${failureClass}`) || code === failureClass) return failureClass
  }
  return ''
}

function arrayFieldObservation(value, present) {
  if (!present) return { shape: 'absent', count: null }
  if (!Array.isArray(value)) return { shape: 'non_array', count: null }
  return { shape: 'array', count: boundedCount(value.length) }
}

function retrievalContextObservation(event) {
  if (!event || typeof event !== 'object') {
    return { shape: 'unknown', detection: 'unavailable' }
  }
  if (!Object.prototype.hasOwnProperty.call(event, 'context')) {
    return { shape: 'absent', detection: 'unavailable' }
  }
  const context = event.context
  if (typeof context === 'string') {
    return {
      shape: 'string',
      detection: /\[VIDEO_SEGMENT\s+segment_id=[^\s\]]+\s+media_id=[^\s\]]+\s+start_ms=\d+\s+end_ms=\d+\s+document_id=[^\s\]]+\]/.test(context) ? 'matched' : 'not_matched',
    }
  }
  if (Array.isArray(context)) return { shape: 'array', detection: 'unavailable' }
  if (context !== null && typeof context === 'object') return { shape: 'object', detection: 'unavailable' }
  return { shape: 'unknown', detection: 'unavailable' }
}

function citationVideoSegmentObservation(citations) {
  const result = { shape: 'absent', count: 0, mediaIdPresent: false, documentIdPresent: false }
  if (!Array.isArray(citations)) return result
  for (const citation of citations) {
    if (!citation || typeof citation !== 'object') continue
    const hasSegments = Object.prototype.hasOwnProperty.call(citation, 'video_segments')
    const hasSegment = Object.prototype.hasOwnProperty.call(citation, 'video_segment')
    if (!hasSegments && !hasSegment) continue
    const segments = citation.video_segments
    if (Array.isArray(segments)) {
      result.shape = 'array'
      result.count = boundedCount(result.count + segments.length)
    } else if (citation.video_segment && typeof citation.video_segment === 'object') {
      if (result.shape === 'absent') result.shape = 'object'
      result.count = boundedCount(result.count + 1)
    } else if (result.shape === 'absent') {
      result.shape = 'unknown'
    }
    if (typeof citation.media_id === 'string' && citation.media_id) result.mediaIdPresent = true
    if (typeof citation.document_id === 'string' && citation.document_id) result.documentIdPresent = true
  }
  return result
}

function elapsedBucket(startedAt, endedAt = Date.now()) {
  const elapsed = Math.max(0, endedAt - startedAt)
  if (elapsed < 1_000) return 'lt_1s'
  if (elapsed < 5_000) return 'lt_5s'
  if (elapsed < 30_000) return 'lt_30s'
  return 'gte_30s'
}

function phaseAMode() {
  return process.env.VIDEO_BROWSER_PHASE_A === '1'
}

function createPhaseAEvidence() {
  return {
    status: 'running',
    failure_class: null,
    timeout_stage: '',
    current_stage: currentStage,
    setup_navigation: null,
    observations: {
      upload_batch_status: 0, task_count: 0, final_task_status: 'not_reached',
      upload_progress_locator_match_count: 0,
      upload_progress_locator_scope: 'not_reached',
      upload_progress_locator_resolution: 'not_reached',
      kb_agent_binding_match: false, agent_thread_binding_match: false,
      retrieval_ready: false, video_segment_count: 0,
      retrieval_context_shape: 'unknown', retrieval_video_anchor_detection: 'unavailable',
      sse_done_citations_shape: 'absent', sse_done_citations_count: null,
      persisted_assistant_citations_shape: 'absent', persisted_assistant_citations_count: null,
      persisted_video_segment_shape: 'absent', persisted_video_segment_count: 0,
      media_id_present: false, document_id_present: false, query_thread_matches_target: false,
      request_failure: { stage: 'not_reached', path: '', reason_class: '' },
    },
    stages: Object.fromEntries(PHASE_A_STAGES.map(name => [name, {
      state: 'not_reached', started_at: 0, ended_at: 0, elapsed_bucket: 'lt_1s', count: 0, http_status: 0,
    }])),
    client: { console_error_count: 0, page_error_count: 0, dom_mutation_count: 0, locator_count: 0 },
  }
}

function recordPhaseA(stageName, state, startedAt, extra = {}) {
  if (!phaseAEvidence || !PHASE_A_STAGES.includes(stageName)) return
  const previous = phaseAEvidence.stages[stageName]
  const start = Number.isInteger(startedAt) && startedAt > 0
    ? startedAt
    : (Number.isInteger(previous?.started_at) && previous.started_at > 0 ? previous.started_at : Date.now())
  const suppliedEnd = Number.isInteger(extra.ended_at) && extra.ended_at >= start ? extra.ended_at : 0
  const end = suppliedEnd || Date.now()
  phaseAEvidence.stages[stageName] = {
    state,
    started_at: start,
    ended_at: end,
    elapsed_bucket: elapsedBucket(start, end),
    count: boundedCount(extra.count),
    http_status: boundedCount(extra.http_status),
  }
}

function setPhaseAFailure(stageName, error) {
  if (!phaseAEvidence || !PHASE_A_FAILURE_CLASSES.has(stageName)) return
  phaseAEvidence.failure_class = stageName
  if (error?.name === 'TimeoutError' || error?.name === 'AbortError') phaseAEvidence.timeout_stage = stageName
}

function failPhaseA(stageName, error, startedAt) {
  recordPhaseA(stageName, 'failed', startedAt)
  setPhaseAFailure(stageName, error)
}

function phaseATimestamp(value, fallback) {
  return Number.isInteger(value) && value > 0 ? value : fallback
}

function recordPhaseASse(sse, fallbackStartedAt) {
  const responseStartedAt = phaseATimestamp(sse?.response_wait_started_at, fallbackStartedAt)
  const responseEndedAt = phaseATimestamp(sse?.response_received_at || sse?.failure_at, Date.now())
  const bodyStartedAt = phaseATimestamp(sse?.body_read_started_at, responseEndedAt)
  const bodyEndedAt = phaseATimestamp(sse?.body_read_completed_at || sse?.failure_at, Date.now())
  recordPhaseA('sse_response', sse?.response_received === true && sse?.response_status === 200 ? 'passed' : 'failed', responseStartedAt, { http_status: sse?.response_status, ended_at: responseEndedAt })
  recordPhaseA('sse_body', sse?.body_read_completed === true ? 'passed' : 'failed', bodyStartedAt, { count: sse?.body_byte_count, ended_at: bodyEndedAt })
  recordPhaseA('sse_framing', sse?.body_read_completed === true && sse?.sse_event_framing === true ? 'passed' : 'failed', bodyStartedAt, { count: sse?.sse_line_count, ended_at: bodyEndedAt })
  recordPhaseA('sse_json', sse?.body_read_completed === true && Number(sse?.json_parse_error_count || 0) === 0 ? 'passed' : 'failed', bodyStartedAt, { count: sse?.json_parse_error_count, ended_at: bodyEndedAt })
  recordPhaseA('sse_done', sse?.done_received === true && sse?.done_thread_matches_target === true ? 'passed' : 'failed', bodyStartedAt, { count: sse?.done_citation_count, ended_at: bodyEndedAt })
  if (phaseAEvidence?.observations) {
    phaseAEvidence.observations.sse_done_citations_shape = sse?.sse_done_citations_shape || 'absent'
    phaseAEvidence.observations.sse_done_citations_count = Number.isInteger(sse?.sse_done_citations_count) ? boundedCount(sse.sse_done_citations_count) : null
  }
  return PHASE_A_STAGES.find(name => name.startsWith('sse_') && phaseAEvidence?.stages[name]?.state === 'failed') || ''
}

function recordPhaseAPersisted(persistedResult) {
  if (!persistedResult?.attempted) return ''
  const startedAt = persistedResult.started_at
  const endedAt = persistedResult.ended_at
  const persisted = persistedResult.value
  recordPhaseA('persisted_conversation', persisted?.conversationGetOk === true ? 'passed' : 'failed', startedAt, { count: persisted?.persistedCitationCount, ended_at: endedAt })
  recordPhaseA('persisted_assistant', persisted?.lastAssistantPresent === true ? 'passed' : 'failed', startedAt, { count: persisted?.lastAssistantPresent ? 1 : 0, ended_at: endedAt })
  recordPhaseA('persisted_citation', Number(persisted?.persistedCitationCount || 0) > 0 && Number(persisted?.persistedVideoSegmentCount || 0) > 0 ? 'passed' : 'failed', startedAt, { count: persisted?.persistedCitationCount, ended_at: endedAt })
  if (phaseAEvidence?.observations) {
    phaseAEvidence.observations.persisted_assistant_citations_shape = persisted?.persistedAssistantCitationsShape || 'absent'
    phaseAEvidence.observations.persisted_assistant_citations_count = Number.isInteger(persisted?.persistedCitationCount) ? boundedCount(persisted.persistedCitationCount) : null
    phaseAEvidence.observations.persisted_video_segment_shape = persisted?.citationVideoSegmentShape || 'absent'
    phaseAEvidence.observations.persisted_video_segment_count = boundedCount(persisted?.citationVideoSegmentCount)
    phaseAEvidence.observations.media_id_present = persisted?.citationMediaIdPresent === true
    phaseAEvidence.observations.document_id_present = persisted?.citationDocumentIdPresent === true
  }
  return ['persisted_conversation', 'persisted_assistant', 'persisted_citation'].find(name => phaseAEvidence?.stages[name]?.state === 'failed') || ''
}

function createNavigationTrace() {
  return { phases: [], failure_class: null, timeout_stage: '', timeout_or_abort: false }
}

function traceNavigation(trace, phase, status, extra = {}, startedAt = Date.now()) {
  trace.phases.push({ phase, status, elapsed_bucket: elapsedBucket(startedAt), ...extra })
}

function recordNavigationFailure(trace, failureClass, timeoutStage = '') {
  trace.failure_class = THREAD_NAVIGATION_FAILURE_CLASSES.has(failureClass) ? failureClass : 'unknown'
  trace.timeout_stage = timeoutStage
}

function isPathInside(root, candidate) {
  const relative = path.relative(root, candidate)
  return Boolean(relative) && !relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative)
}

function resolveRunOwnedPath(runRoot, candidate, label) {
  if (!runRoot || !candidate) fail(`browser-navigation-${label}-path`)
  const root = path.resolve(runRoot)
  const resolved = path.resolve(candidate)
  if (!fs.existsSync(root) || !fs.statSync(root).isDirectory() || !isPathInside(root, resolved)) {
    fail(`browser-navigation-${label}-path`)
  }
  return { root, resolved }
}

function assertExistingRunOwnedPath(runRoot, candidate, label) {
  const root = fs.realpathSync(runRoot)
  const resolved = fs.realpathSync(candidate)
  if (!isPathInside(root, resolved)) fail(`browser-navigation-${label}-escape`)
}

function matchesExactDetailResponse(response, detailPath) {
  try {
    return response.request().method() === 'GET' && new URL(response.url()).pathname === detailPath
  } catch {
    return false
  }
}

function recordCitationDiagnosis(category, observations = {}) {
  if (!CITATION_DIAGNOSIS_CLASSES.has(category)) fail('browser-citation-diagnosis-class')
  citationDiagnosis = {
    category,
    session_auth_ok: observations.sessionAuthOk === true,
    agent_created: observations.agentCreated === true,
    agent_create_status: boundedCount(observations.agentCreateStatus),
    agent_list_accessible: observations.agentListAccessible === true,
    agent_list_count: boundedCount(observations.agentListCount),
    agent_kb_match: observations.agentKbMatch === true,
    conversation_bound: observations.conversationBound === true,
    upload_terminal_count: boundedCount(observations.uploadTerminalCount),
    retrieval_ready: observations.retrievalReady === true,
    retrieval_context_present: observations.retrievalContextPresent === true,
    retrieval_video_anchor_count: boundedCount(observations.retrievalVideoAnchorCount),
    retrieval_thread_context_present: observations.retrievalThreadContextPresent === true,
    retrieval_thread_video_anchor_count: boundedCount(observations.retrievalThreadVideoAnchorCount),
    retrieval_unthreaded_context_present: observations.retrievalUnthreadedContextPresent === true,
    retrieval_unthreaded_video_anchor_count: boundedCount(observations.retrievalUnthreadedVideoAnchorCount),
    done_received: observations.doneReceived === true,
    done_fallback: observations.doneFallback === true,
    citation_count: boundedCount(observations.citationCount),
    video_segment_citation_count: boundedCount(observations.videoSegmentCitationCount),
    conversation_get_ok: observations.conversationGetOk === true,
    last_assistant_present: observations.lastAssistantPresent === true,
    persisted_citation_count: boundedCount(observations.persistedCitationCount),
    persisted_video_segment_count: boundedCount(observations.persistedVideoSegmentCount),
    page_conversation_get_completed: observations.pageConversationGetCompleted === true,
    dom_video_segments_label: observations.domVideoSegmentsLabel === true,
    dom_no_video_segments_label: observations.domNoVideoSegmentsLabel === true,
    player_segment_count: boundedCount(observations.playerSegmentCount),
  }
  return category
}

function summarizeSse(body, expectedThreadId = '') {
  const summary = {
    doneReceived: false,
    doneFallback: false,
    doneThreadBound: false,
    doneThreadMatchesTarget: false,
    citationCount: 0,
    videoSegmentCitationCount: 0,
    retrievalContextPresent: false,
    retrievalVideoAnchorCount: 0,
    doneQueryId: '',
    lineCount: 0,
    dataLineCount: 0,
    jsonParseErrorCount: 0,
  }
  for (const line of String(body || '').split('\n')) {
    summary.lineCount = boundedCount(summary.lineCount + 1)
    if (!line.startsWith('data: ')) continue
    summary.dataLineCount = boundedCount(summary.dataLineCount + 1)
    let event
    try { event = JSON.parse(line.slice(6)) } catch {
      summary.jsonParseErrorCount = boundedCount(summary.jsonParseErrorCount + 1)
      continue
    }
    if (event?.type === 'retrieval') {
      summary.retrievalContextPresent = event.context_present === true
      summary.retrievalVideoAnchorCount = boundedCount(event.video_segment_anchor_count)
    }
    if (event?.type === 'done') {
      summary.doneReceived = true
      summary.doneFallback = event.fallback === true
      summary.doneThreadBound = typeof event.thread_id === 'string' && event.thread_id.length > 0
      summary.doneThreadMatchesTarget = Boolean(expectedThreadId) && event.thread_id === expectedThreadId
      summary.doneQueryId = typeof event.id === 'string' ? event.id : ''
      const citations = Array.isArray(event.citations) ? event.citations : []
      summary.citationCount = boundedCount(citations.length)
      summary.videoSegmentCitationCount = boundedCount(citations.reduce((count, citation) => (
        count + (Array.isArray(citation?.video_segments) ? citation.video_segments.length : citation?.video_segment ? 1 : 0)
      ), 0))
    }
  }
  return summary
}

function createCitationProbe() {
  return {
    query_submit_started: false,
    query_submit_completed: false,
    target_query_identity_observed: false,
    dom_query_identity_available: false,
    dom_query_identity_diagnostic: '',
    persisted_query_identity_matches_done: false,
    client_message_id_present: false,
    client_message_id_format: 'not_exposed_to_dom',
    server_done_query_id_present: false,
    server_done_query_id_hash_or_bounded_presence: 'absent',
    streaming_assistant_count: 0,
    streaming_assistant_query_id_attribute_count: 0,
    streaming_assistant_client_id_attribute_count: 0,
    streaming_assistant_state: 'not_exposed_to_dom',
    streaming_assistant_text_present: false,
    query_id_to_dom_mapping: 'unavailable_streaming_dom_identity',
    persisted_assistant_query_id_present: false,
    persisted_assistant_matches_done_id: false,
    reload_assistant_matches_done_id: 'not_exposed_to_dom',
    locator_contract_class: 'harness_contract_mismatch',
    response_wait_started: false,
    response_received: false,
    response_status: 0,
    response_content_type: '',
    body_read_started: false,
    body_read_completed: false,
    body_read_error_class: '',
    body_byte_count: 0,
    request_finished: false,
    request_failed: false,
    done_received: false,
    done_thread_matches_target: false,
    done_citation_count: 0,
    response_body_read_started: false,
    response_body_read_completed: false,
    response_body_byte_count: 0,
    sse_event_framing: false,
    sse_line_count: 0,
    sse_data_line_count: 0,
    sse_json_parse_error_count: 0,
    stream_response_started: false,
    stream_response_completed: false,
    sse_done_received: false,
    sse_done_thread_matches_target: false,
    sse_done_citations_shape: 'absent',
    sse_done_citations_count: null,
    persisted_assistant_citations_shape: 'absent',
    persisted_assistant_citations_count: null,
    retrieval_context_shape: 'unknown',
    retrieval_video_anchor_detection: 'unavailable',
    citation_video_segment_shape: 'absent',
    citation_video_segment_count: 0,
    citation_media_id_present: false,
    citation_document_id_present: false,
    query_thread_matches_target: false,
    query_id_thread_id_match: false,
    request_failure: { stage: '', path: '', reason_class: '' },
    sse_done_citation_count: 0,
    streaming_assistant_found: false,
    streaming_citation_found: false,
    streaming_video_player_found: false,
    player_visible: false,
    persisted_conversation_get: false,
    persisted_assistant_found: false,
    persisted_video_segments_found: false,
    reload_started: false,
    reload_completed: false,
    reloaded_player_visible: false,
    authorized_media_status: 0,
    range_status: 0,
    timeout_stage: '',
    failure_class: null,
    phases: [],
  }
}

function recordCitationProbe(probe, phase, startedAt, fields = {}) {
  if (!CITATION_PROBE_PHASES.includes(phase)) fail('browser-citation-probe-phase')
  const entry = { phase, elapsed_bucket: elapsedBucket(startedAt) }
  for (const [key, value] of Object.entries(fields)) {
    if (typeof value === 'boolean') entry.observed = value
    if (Number.isInteger(value)) {
      if (key === 'status') entry.http_status = boundedCount(value)
      else entry.count = boundedCount(value)
    }
  }
  probe.phases.push(entry)
}

function citationProbeFailure(probe, stageName, failureClass) {
  probe.timeout_stage = stageName
  probe.failure_class = failureClass
  const startedAt = Date.now()
  recordCitationProbe(probe, 'timeout_stage', startedAt, { observed: Boolean(stageName) })
  recordCitationProbe(probe, 'failure_class', startedAt, { observed: true })
}

function chromiumExecutablePath() {
  const root = '/ms-playwright'
  const candidates = fs.readdirSync(root)
    .filter(name => /^chromium_headless_shell-\d+$/.test(name) || /^chromium-\d+$/.test(name))
    .sort()
    .reverse()
  for (const candidate of candidates) {
    for (const suffix of ['chrome-linux/headless_shell', 'chrome-linux64/headless_shell', 'chrome-linux/chrome', 'chrome-linux64/chrome']) {
      const executable = `${root}/${candidate}/${suffix}`
      if (fs.existsSync(executable)) return executable
    }
  }
  fail('browser-chromium-executable')
}

async function api(path, options = {}) {
  const response = await fetch(`${base}${path}`, options)
  const text = await response.text()
  let body = {}
  try { body = text ? JSON.parse(text) : {} } catch { body = {} }
  return { status: response.status, body }
}

async function installCitationResponseObserver(page, queryPath, expectedThreadId) {
  await page.evaluate(({ targetPath, targetThreadId }) => {
    const key = '__ragCitationResponseObserver'
    const originalFetch = window.fetch.bind(window)
    const state = {
      response_wait_started: true,
      response_wait_started_at: 0,
      response_received: false,
      response_received_at: 0,
      response_status: 0,
      response_content_type: '',
      body_read_started: false,
      body_read_started_at: 0,
      body_read_completed: false,
      body_read_completed_at: 0,
      body_read_error_class: '',
      body_byte_count: 0,
      sse_event_framing: false,
      sse_line_count: 0,
      sse_data_line_count: 0,
      json_parse_error_count: 0,
      done_received: false,
      done_thread_matches_target: false,
      sse_done_citations_shape: 'absent',
      sse_done_citations_count: null,
      retrieval_context_shape: 'unknown',
      retrieval_video_anchor_detection: 'unavailable',
      done_citation_count: 0,
      done_query_id: '',
      request_finished: false,
      request_failed: false,
      failure_at: 0,
      failure_class: null,
      timeout_stage: '',
      request_failure: { stage: '', path: '', reason_class: '' },
    }
    let settle
    const settled = new Promise(resolve => { settle = resolve })
    const bounded = value => Math.max(0, Math.min(999, Number.isInteger(value) ? value : 0))
    const observeArrayField = (value, present) => {
      if (!present) return { shape: 'absent', count: null }
      if (!Array.isArray(value)) return { shape: 'non_array', count: null }
      return { shape: 'array', count: bounded(value.length) }
    }
    const finish = () => {
      if (state.request_finished || state.request_failed) return
      state.request_finished = true
      settle()
    }
    const fail = (failureClass, errorClass, stage) => {
      if (state.failure_class === null) state.failure_class = failureClass
      state.failure_at = Date.now()
      if (state.body_read_started && !state.body_read_completed_at) state.body_read_completed_at = state.failure_at
      state.body_read_error_class = errorClass
      state.timeout_stage = stage
      state.request_failure = {
        stage: String(stage || '').replace(/[^a-z0-9_-]/gi, '').slice(0, 80),
        path: String(targetPath || '').replace(/\/agents\/[^/]+/, '/agents/:agent').slice(0, 160),
        reason_class: String(errorClass || failureClass || 'unknown').replace(/[^a-z0-9_-]/gi, '').slice(0, 80),
      }
      state.request_failed = true
      settle()
    }
    const isTarget = (input, init) => {
      try {
        const request = input instanceof Request ? input : null
        const url = new URL(request ? request.url : String(input), window.location.href)
        const method = String(init?.method || request?.method || 'GET').toUpperCase()
        return method === 'POST' && url.pathname === targetPath
      } catch {
        return false
      }
    }
    const observeClone = async response => {
      state.response_received = true
      state.response_received_at = Date.now()
      state.response_status = bounded(response.status)
      const contentType = String(response.headers.get('content-type') || '').split(';', 1)[0].trim().toLowerCase()
      state.response_content_type = contentType === 'text/event-stream' ? contentType : 'other'
      let reader
      try {
        const clone = response.clone()
        reader = clone.body?.getReader()
        if (!reader) throw new Error('clone-body-unavailable')
      } catch {
        fail('sse_body_read_failure', 'clone_unavailable', 'body_read_started')
        return
      }
      state.body_read_started = true
      state.body_read_started_at = Date.now()
      try {
        const decoder = new TextDecoder()
        let pending = ''
        const processLine = line => {
          state.sse_line_count = bounded(state.sse_line_count + 1)
          if (!line.startsWith('data: ')) return false
          state.sse_data_line_count = bounded(state.sse_data_line_count + 1)
          let event
          try {
            event = JSON.parse(line.slice(6))
          } catch {
            state.json_parse_error_count = bounded(state.json_parse_error_count + 1)
            return false
          }
          if (event?.type === 'retrieval') {
            const retrieval = retrievalContextObservation(event)
            state.retrieval_context_shape = retrieval.shape
            state.retrieval_video_anchor_detection = retrieval.detection
            return false
          }
          if (event?.type !== 'done') return false
          state.done_received = true
          state.done_thread_matches_target = Boolean(targetThreadId) && event.thread_id === targetThreadId
          state.done_query_id = typeof event.id === 'string' ? event.id : ''
          const citations = observeArrayField(event.citations, Object.prototype.hasOwnProperty.call(event, 'citations'))
          state.sse_done_citations_shape = citations.shape
          state.sse_done_citations_count = citations.count
          state.done_citation_count = citations.shape === 'array' ? citations.count : 0
          return true
        }
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          state.body_byte_count = bounded(state.body_byte_count + value.byteLength)
          pending += decoder.decode(value, { stream: true })
          if (pending.length > 64 * 1024) {
            fail('sse_event_parse_failure', 'line_overflow', 'sse_event_framing')
            await reader.cancel()
            return
          }
          let newline
          while ((newline = pending.indexOf('\n')) >= 0) {
            const line = pending.slice(0, newline).replace(/\r$/, '')
            pending = pending.slice(newline + 1)
            if (processLine(line) && state.json_parse_error_count > 0) {
              fail('sse_json_parse_failure', 'json_parse', 'json_parse_error_count')
              await reader.cancel()
              return
            }
            if (state.done_received && state.done_thread_matches_target) {
              state.sse_event_framing = state.sse_data_line_count > 0
              state.body_read_completed = true
              state.body_read_completed_at = Date.now()
              await reader.cancel()
              finish()
              return
            }
          }
        }
        pending += decoder.decode()
        if (pending) processLine(pending.replace(/\r$/, ''))
        state.body_read_completed = true
        state.body_read_completed_at = Date.now()
        state.sse_event_framing = state.sse_data_line_count > 0
        if (!state.sse_event_framing) fail('sse_event_parse_failure', 'event_framing', 'sse_event_framing')
        else if (state.json_parse_error_count > 0) fail('sse_json_parse_failure', 'json_parse', 'json_parse_error_count')
        else if (!state.done_received) fail('sse_done_missing', '', 'done_received')
        else if (!state.done_thread_matches_target) fail('sse_done_thread_mismatch', '', 'done_thread_matches_target')
        else finish()
      } catch (error) {
        const errorClass = error?.name === 'AbortError' ? 'abort' : 'body_unavailable'
        fail('sse_body_read_failure', errorClass, 'body_read_completed')
      }
    }
    window.fetch = async function citationObservedFetch(input, init) {
      const target = isTarget(input, init)
      try {
        if (target && !state.response_wait_started_at) state.response_wait_started_at = Date.now()
        const response = await originalFetch(input, init)
        if (target && !state.response_received) void observeClone(response)
        return response
      } catch (error) {
        if (target) fail('response_wait_timeout', error?.name === 'AbortError' ? 'abort' : 'request_failure', 'response_received')
        throw error
      }
    }
    window[key] = {
      snapshot: () => ({ ...state }),
      waitForCompletion: async timeoutMs => {
        await Promise.race([settled, new Promise(resolve => setTimeout(resolve, timeoutMs))])
        if (!state.request_finished && !state.request_failed) fail('sse_body_read_failure', 'observer_timeout', 'body_read_completed')
        return { ...state }
      },
      restore: () => { window.fetch = originalFetch },
    }
  }, { targetPath: queryPath, targetThreadId: expectedThreadId })
}

async function readCitationResponseObserver(page) {
  return page.evaluate(() => window.__ragCitationResponseObserver?.waitForCompletion(30_000) || null)
}

async function removeCitationResponseObserver(page) {
  await page.evaluate(() => window.__ragCitationResponseObserver?.restore?.())
}

function installPageDiagnostics(page) {
  let expectedDetailPath = ''
  let expectedThreadId = ''
  const details = []
  const queryThreadIds = []
  const detailWaiters = new Set()
  const errors = {
    console: 0,
    page: 0,
    expected_detail_request: 0,
    non_expected_request: 0,
    aborted: 0,
  }
  const isExpectedDetail = request => {
    if (!expectedDetailPath) return false
    try {
      const url = new URL(request.url())
      return request.method() === 'GET' && url.pathname === expectedDetailPath
    } catch {
      return false
    }
  }
  const onResponse = response => {
    if (!isExpectedDetail(response.request())) return
    const detail = { status: boundedCount(response.status()), ok: response.ok() }
    details.push(detail)
    for (const resolve of detailWaiters) resolve(detail)
    detailWaiters.clear()
  }
  const onConsole = message => {
    if (message.type() === 'error') errors.console += 1
  }
  const onPageError = () => { errors.page += 1 }
  const onRequestFailed = request => {
    const aborted = String(request.failure()?.errorText || '').includes('ERR_ABORTED')
    if (aborted) errors.aborted += 1
    if (isExpectedDetail(request)) errors.expected_detail_request += 1
    else errors.non_expected_request += 1
  }
  const onRequest = request => {
    try {
      const url = new URL(request.url())
      if (request.method() === 'POST' && url.pathname.endsWith('/query/stream')) {
        const payload = request.postDataJSON?.() || {}
        queryThreadIds.push(typeof payload.thread_id === 'string' ? payload.thread_id : '')
      }
    } catch { /* malformed request bodies are handled by the normal request diagnostics */ }
  }
  page.on('response', onResponse)
  page.on('console', onConsole)
  page.on('pageerror', onPageError)
  page.on('request', onRequest)
  page.on('requestfailed', onRequestFailed)
  return {
    expectThread: (agentId, threadId) => {
      expectedThreadId = threadId
      expectedDetailPath = `/api/agents/${encodeURIComponent(agentId)}/conversations/${encodeURIComponent(threadId)}`
    },
    clearExpectedThread: () => { expectedDetailPath = '' },
    detailCount: () => details.length,
    detail: () => ({
      response_count: boundedCount(details.length),
      status: boundedCount(details.at(-1)?.status),
      ok: details.at(-1)?.ok === true,
    }),
    queryThreadIds: () => [...queryThreadIds],
    queryThreadMatchesExpected: () => queryThreadIds.length === 1 && queryThreadIds[0] === expectedThreadId,
    errors: () => ({ ...errors }),
    waitForDetail: previousCount => new Promise((resolve, reject) => {
      if (details.length > previousCount) return resolve(details.at(-1))
      const timeout = setTimeout(() => {
        detailWaiters.delete(onDetail)
        reject(new Error('browser-page-conversation-detail'))
      }, 30_000)
      const onDetail = detail => {
        clearTimeout(timeout)
        resolve(detail)
      }
      detailWaiters.add(onDetail)
    }),
    dispose: () => {
      page.off('response', onResponse)
      page.off('console', onConsole)
      page.off('pageerror', onPageError)
      page.off('request', onRequest)
      page.off('requestfailed', onRequestFailed)
    },
  }
}

async function login(page, account, prefix) {
  // Login asserts its controls and authenticated transition below. Background
  // startup traffic must not make the page navigation itself wait indefinitely.
  currentStage = `${prefix}-login-page`
  await page.goto(`${base}/login`, { waitUntil: 'domcontentloaded', timeout: 30_000 })
  currentStage = `${prefix}-login-inputs`
  await page.getByPlaceholder('请输入用户名').fill(account.username)
  await page.getByPlaceholder('请输入密码').fill(account.current_password || account.initial_password || account.password)
  currentStage = `${prefix}-login-submit`
  await page.getByRole('button', { name: '登录' }).click()
  currentStage = `${prefix}-login-transition`
  const nextState = await page.waitForFunction(() => {
    if (document.querySelector('header.cockpit-topbar')) return 'authenticated'
    if (document.body?.innerText.includes('修改初始密码')) return 'password-change'
    return null
  }, null, { timeout: 30_000 }).then(handle => handle.jsonValue())
  if (nextState === 'password-change') {
    currentStage = `${prefix}-password-inputs`
    await page.getByPlaceholder('至少 8 位，含大小写字母、数字、特殊字符中的 3 类').fill(account.password)
    await page.getByPlaceholder('再次输入新密码').fill(account.password)
    currentStage = `${prefix}-password-submit`
    await page.getByRole('button', { name: '确认修改' }).click()
    account.current_password = account.password
    currentStage = `${prefix}-password-transition`
    await page.locator('header.cockpit-topbar').waitFor({ state: 'visible', timeout: 30_000 })
  }
}

async function sessionRole(page, role) {
  const result = await page.evaluate(async expected => {
    const saved = JSON.parse(localStorage.getItem('raganything_auth') || 'null')
    const response = await fetch('/api/auth/me', { headers: { Authorization: `Bearer ${saved?.token || ''}` } })
    const body = await response.json().catch(() => ({}))
    return response.ok && body?.user?.role?.name === expected
  }, role)
  if (!result) fail('browser-session-role')
}

async function logout(page, username) {
  const menu = page.locator('header button').filter({ hasText: username }).first()
  await menu.click()
  await page.getByRole('menuitem', { name: '退出登录' }).click()
  await page.waitForURL(url => new URL(url).pathname === '/login', { timeout: 30_000 })
}

async function createKnowledgeBaseAndUpload(page, fixturePath, prefix, { waitForTerminal = true } = {}) {
  const name = `videouat${Date.now().toString(36)}`
  const filename = fixturePath.split('/').pop()
  currentStage = `${prefix}-video-upload-list`
  await page.goto(`${base}/knowledge`, { waitUntil: 'domcontentloaded', timeout: 30_000 })
  currentStage = `${prefix}-video-upload-create`
  await page.getByRole('button', { name: '新建知识库' }).click()
  await page.getByPlaceholder('输入知识库名称…').fill(name)
  await page.getByRole('button', { name: '创建', exact: true }).click()
  currentStage = `${prefix}-video-upload-created`
  const knowledgeBaseCard = page.getByRole('button', { name: `打开知识库 ${name}` })
  await knowledgeBaseCard.waitFor({ state: 'visible', timeout: 30_000 })
  currentStage = `${prefix}-video-upload-select`
  await knowledgeBaseCard.click()
  await page.waitForURL(url => new URL(url).pathname.includes(`/knowledge/${encodeURIComponent(name)}`), { timeout: 30_000 })
  currentStage = `${prefix}-video-upload-panel`
  await page.getByRole('button', { name: /展开上传面板|收起上传面板/ }).click()
  currentStage = `${prefix}-video-upload-file`
  await page.locator('#knowledge-upload-panel input[type=file]').setInputFiles(fixturePath)
  currentStage = `${prefix}-video-upload-submit`
  const uploadResponse = page.waitForResponse(response => {
    try {
      return response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/upload/batch'
    } catch { return false }
  }, { timeout: 30_000 })
  await page.getByRole('button', { name: /全部上传 \(1\)/ }).click()
  const batchResponse = await uploadResponse
  if (!batchResponse.ok()) fail('browser-upload-batch')
  const batchBody = await batchResponse.json().catch(() => ({}))
  const batchTasks = Array.isArray(batchBody?.tasks) ? batchBody.tasks : []
  const batchTaskId = batchTasks.length === 1 ? String(batchTasks[0]?.task_id || '') : ''
  const batchTaskDocumentId = batchTasks.length === 1
    ? String(batchTasks[0]?.document_id || batchTasks[0]?.doc_id || batchTasks[0]?.documentId || '')
    : ''
  if (!batchTaskId) fail('browser-upload-batch-task')
  if (phaseAMode() && phaseAEvidence?.observations) phaseAEvidence.observations.upload_batch_status = boundedCount(batchResponse.status())
  currentStage = `${prefix}-video-upload-task`
  await page.getByText(/^上传任务 \(\d+\)$/).waitFor({ state: 'visible', timeout: 30_000 })
  await page.locator('#server-upload-tasks').waitFor({ state: 'visible', timeout: 30_000 })
  await page.getByText(filename, { exact: true }).waitFor({ state: 'visible', timeout: 30_000 })
  currentStage = `${prefix}-video-upload-progress`
  await waitForUploadProgress(page, filename)
  let uploadTerminal = false
  if (waitForTerminal) {
    currentStage = `${prefix}-video-upload-terminal`
    await page.getByText('已可检索').waitFor({ state: 'visible', timeout: 600_000 })
    uploadTerminal = true
  }
  return {
    name,
    task_id: batchTaskId,
    batch_document_id: batchTaskDocumentId,
    upload_progress: true,
    upload_terminal: uploadTerminal,
    batch_status: boundedCount(batchResponse.status()),
  }
}

async function waitForUploadProgress(page, filename) {
  const observations = phaseAEvidence?.observations
  const taskContainer = page.locator('#server-upload-tasks')
  const taskRows = taskContainer.locator(':scope > div').filter({ has: page.getByText(filename, { exact: true }) })
  const taskMatchCount = await taskRows.count()
  if (observations) {
    observations.upload_progress_locator_match_count = boundedCount(taskMatchCount)
    observations.upload_progress_locator_scope = 'server-upload-tasks/task-row[filename-exact]'
  }
  if (taskMatchCount === 0) {
    if (observations) observations.upload_progress_locator_resolution = 'no-task-row'
    fail('upload_progress_locator_no_match')
  }
  if (taskMatchCount !== 1) {
    if (observations) observations.upload_progress_locator_resolution = 'multiple-task-rows'
    fail('upload_progress_locator_multiple_match')
  }

  const taskRow = taskRows
  const progressLocator = taskRow.getByText(/^进度 [1-9]\d?%$/, { exact: true })
  const statusLocator = taskRow.getByText(/^(排队中|处理中|入库中)$/, { exact: true })
  const progressMatchCount = await progressLocator.count()
  const statusMatchCount = await statusLocator.count()
  if (progressMatchCount === 1) {
    if (observations) {
      observations.upload_progress_locator_match_count = boundedCount(progressMatchCount)
      observations.upload_progress_locator_resolution = 'progress-text-exact'
    }
    await progressLocator.waitFor({ state: 'visible', timeout: 60_000 })
    return
  }
  if (progressMatchCount > 1 || statusMatchCount > 1) {
    if (observations) {
      observations.upload_progress_locator_match_count = boundedCount(Math.max(progressMatchCount, statusMatchCount))
      observations.upload_progress_locator_resolution = 'multiple-progress-or-status'
    }
    fail('upload_progress_locator_multiple_match')
  }
  if (statusMatchCount === 1) {
    if (observations) {
      observations.upload_progress_locator_match_count = boundedCount(statusMatchCount)
      observations.upload_progress_locator_resolution = 'status-text-exact'
    }
    await statusLocator.waitFor({ state: 'visible', timeout: 60_000 })
    return
  }
  if (observations) observations.upload_progress_locator_resolution = 'no-progress-or-status'
  fail('upload_progress_locator_no_match')
}

async function phaseAResourceObservations(page, agentId, threadId, kb) {
  return page.evaluate(async ({ id, thread, kbName }) => {
    const saved = JSON.parse(localStorage.getItem('raganything_auth') || 'null')
    const headers = { Authorization: `Bearer ${saved?.token || ''}` }
    const [agentsReply, taskReply, healthReply, documentsReply] = await Promise.all([
      fetch('/api/agents', { headers }),
      fetch(`/api/upload/tasks?kb=${encodeURIComponent(kbName)}`, { headers }),
      fetch(`/api/knowledge/retrieval-health?kb=${encodeURIComponent(kbName)}`, { headers }),
      fetch(`/api/knowledge/documents?kb=${encodeURIComponent(kbName)}`, { headers }),
    ])
    const agents = (await agentsReply.json().catch(() => ({})))?.agents
    const tasks = (await taskReply.json().catch(() => ({})))?.tasks
    const health = await healthReply.json().catch(() => ({}))
    const documents = (await documentsReply.json().catch(() => ({})))?.documents
    const taskList = Array.isArray(tasks) ? tasks : []
    const documentList = Array.isArray(documents) ? documents : []
    const firstDocumentId = documentList.length === 1 ? String(documentList[0]?.id || '') : ''
    let segmentCount = 0
    if (firstDocumentId) {
      const segmentsReply = await fetch(`/api/knowledge/documents/${encodeURIComponent(firstDocumentId)}/video-segments?kb=${encodeURIComponent(kbName)}`, { headers })
      const segments = (await segmentsReply.json().catch(() => ({})))?.segments
      segmentCount = Array.isArray(segments) ? Math.min(999, segments.length) : 0
    }
    return {
      task_count: Math.min(999, taskList.length),
      final_task_status: taskList.length === 1 && ['completed', 'processed'].includes(String(taskList[0]?.status || '')) ? String(taskList[0].status) : 'not_ready',
      kb_agent_binding_match: agentsReply.ok && Array.isArray(agents) && agents.some(agent => String(agent?.id || '') === id && agent?.kb_name === kbName),
      agent_thread_binding_match: Boolean(thread),
      retrieval_ready: healthReply.ok && Array.isArray(health?.documents) && health.documents.length === 0,
      video_segment_count: segmentCount,
    }
  }, { id: agentId, thread: threadId, kbName: kb })
}

async function runUploadDiagnosis(page, account) {
  const prefix = 'browser-upload-diagnosis'
  await login(page, account, prefix)
  await sessionRole(page, 'super_admin')
  const upload = await createKnowledgeBaseAndUpload(page, fixture, prefix, { waitForTerminal: false })
  const result = await page.evaluate(async ({ kbName, taskId, batchDocumentId }) => {
    const saved = JSON.parse(localStorage.getItem('raganything_auth') || 'null')
    const headers = { Authorization: `Bearer ${saved?.token || ''}` }
    const started = Date.now()
    const timeline = []
    let taskReply
    let tasks = []
    const terminal = new Set(['completed', 'processed', 'failed', 'cancelling'])
    do {
      taskReply = await fetch(`/api/upload/tasks?kb=${encodeURIComponent(kbName)}`, { headers })
      tasks = (await taskReply.json().catch(() => ({})))?.tasks
      const task = Array.isArray(tasks) ? tasks.find(item => String(item?.task_id || '') === taskId) : null
      const status = ['queued', 'processing', 'retry_wait', 'completed', 'processed', 'failed', 'cancelling'].includes(String(task?.status || '')) ? String(task.status) : 'unknown'
      const phase = ['queued', 'processing', 'multimodal', 'finalize', 'retrieval_readiness'].includes(String(task?.phase || '')) ? String(task.phase) : 'unknown'
      const failureStage = ['multimodal', 'worker_timeout', 'finalize', 'retrieval_readiness', 'video_profile', 'graph_index', 'tagging'].includes(String(task?.failure_stage || '')) ? String(task.failure_stage) : 'none'
      timeline.push({ status, phase, failure_stage: failureStage, retryable: task?.retryable === true, retry_count: Math.max(0, Math.min(999, Number(task?.retry_count || 0))), progress: Math.max(0, Math.min(100, Number(task?.progress || 0))), time_bucket: Math.min(36, Math.floor((Date.now() - started) / 5000)) })
      if (terminal.has(status) || Date.now() - started >= 180000) break
      await new Promise(resolve => setTimeout(resolve, 2000))
    } while (true)
    const documentsReply = await fetch(`/api/knowledge/documents?kb=${encodeURIComponent(kbName)}`, { headers })
    const documents = (await documentsReply.json().catch(() => ({})))?.documents
    const task = Array.isArray(tasks) ? tasks.find(item => String(item?.task_id || '') === taskId) : null
    const documentList = Array.isArray(documents) ? documents : []
    const explicitDocumentId = value => {
      if (!value || typeof value !== 'object') return ''
      return String(value.document_id || value.doc_id || value.documentId
        || value.document?.document_id || value.document?.id || '').trim()
    }
    const taskDocumentId = explicitDocumentId(task)
    const batchDocumentIdValue = String(batchDocumentId || '').trim()
    const documentIds = document => [document?.full_id, document?.document_id, document?.id]
      .map(value => String(value || '').trim()).filter(Boolean)
    const isSyntheticTaskRow = document => String(document?.full_id || '').trim() === taskId
      && String(document?.upload_task_id || '').trim() === taskId
      && ['queued', 'processing', 'retry_wait'].includes(String(document?.status || ''))
      && Number(document?.chunks || document?.chunks_count || 0) === 0
    const taskProvenance = document => [
      ['document.upload_task_id', document?.upload_task_id],
      ['document.track_id', document?.track_id],
      ['document.metadata.task_id', document?.metadata?.task_id],
    ].map(([source, value]) => ({ source, value: String(value || '').trim() }))
      .filter(item => item.value)
    const findByDocumentId = (documentId, source) => {
      if (!documentId) return { doc: null, source, ambiguous: false }
      const matches = documentList.filter(document => !isSyntheticTaskRow(document) && documentIds(document).includes(documentId))
      return { doc: matches.length === 1 ? matches[0] : null, source, ambiguous: matches.length > 1 }
    }
    let mapping = { status: 'unavailable', matched: false, source: 'none', failure_reason_class: documentsReply.ok ? 'task_document_provenance_unavailable' : 'document_list_unavailable' }
    let doc = null
    let mappingCandidate = findByDocumentId(taskDocumentId, 'task.document_id')
    if (!documentsReply.ok) {
      mapping = { status: 'unavailable', matched: false, source: 'none', failure_reason_class: 'document_list_unavailable' }
    } else if (taskDocumentId) {
      mapping = mappingCandidate.doc
        ? { status: 'matched', matched: true, source: mappingCandidate.source, failure_reason_class: 'none' }
        : { status: 'unmatched', matched: false, source: mappingCandidate.source, failure_reason_class: mappingCandidate.ambiguous ? 'task_document_id_ambiguous' : 'task_document_id_not_found' }
      doc = mappingCandidate.doc
    } else if (batchDocumentIdValue) {
      mappingCandidate = findByDocumentId(batchDocumentIdValue, 'upload_batch.document_id')
      mapping = mappingCandidate.doc
        ? { status: 'matched', matched: true, source: mappingCandidate.source, failure_reason_class: 'none' }
        : { status: 'unmatched', matched: false, source: mappingCandidate.source, failure_reason_class: mappingCandidate.ambiguous ? 'batch_document_id_ambiguous' : 'batch_document_id_not_found' }
      doc = mappingCandidate.doc
    } else if (taskId && documentList.length) {
      const provenanceMatches = documentList.filter(document => !isSyntheticTaskRow(document) && taskProvenance(document).some(item => item.value === taskId))
      if (provenanceMatches.length === 1) {
        doc = provenanceMatches[0]
        const provenance = taskProvenance(doc).find(item => item.value === taskId)
        mapping = { status: 'matched', matched: true, source: provenance?.source || 'document.provenance', failure_reason_class: 'none' }
      } else if (provenanceMatches.length > 1) {
        mapping = { status: 'unmatched', matched: false, source: 'document.provenance', failure_reason_class: 'task_provenance_ambiguous' }
      } else {
        mapping = { status: 'unmatched', matched: false, source: 'document.provenance', failure_reason_class: 'task_provenance_not_found' }
      }
    }
    // Segment routes require the canonical full ID. A mapping match without it
    // remains diagnostically incomplete and must not fall back to a short ID.
    const fullDocumentId = doc ? String(doc.full_id || '').trim() : ''
    if (mapping.status === 'matched' && !fullDocumentId) {
      mapping = { status: 'unavailable', matched: false, source: mapping.source, failure_reason_class: 'full_document_id_unavailable' }
      doc = null
    }
    let healthReply = { status: 0, ok: false }
    let health = {}
    if (mapping.status === 'matched') {
      healthReply = await fetch(`/api/knowledge/retrieval-health?kb=${encodeURIComponent(kbName)}`, { headers })
      health = await healthReply.json().catch(() => ({}))
    }
    let segments = []
    let segmentsStatus = 0
    if (mapping.status === 'matched' && fullDocumentId) {
      const reply = await fetch(`/api/knowledge/documents/${encodeURIComponent(fullDocumentId)}/video-segments?kb=${encodeURIComponent(kbName)}`, { headers })
      segmentsStatus = reply.status
      segments = (await reply.json().catch(() => ({})))?.segments
    }
    return {
      task_http_status: taskReply.status,
      task_count: Array.isArray(tasks) ? Math.min(999, tasks.length) : 0,
      task_status: ['queued', 'processing', 'retry_wait', 'completed', 'processed', 'failed', 'cancelling'].includes(String(task?.status || '')) ? String(task.status) : 'unknown',
      task_phase: timeline.length ? timeline[timeline.length - 1].phase : 'unknown',
      task_failure_stage: timeline.length ? timeline[timeline.length - 1].failure_stage : 'none',
      task_retryable: task?.retryable === true,
      task_retry_count: Math.max(0, Math.min(999, Number(task?.retry_count || 0))),
      task_progress: Math.max(0, Math.min(100, Number(task?.progress || 0))),
      task_updated_at_bucket: task?.updated_at ? 'present' : 'absent',
      task_status_timeline: timeline.slice(-90),
      worker_consumed: timeline.some(item => ['processing', 'retry_wait', 'completed', 'processed', 'failed', 'cancelling'].includes(item.status)) || Number(task?.progress || 0) > 0,
      task_reason_class: timeline.length ? timeline[timeline.length - 1].failure_stage : 'none',
      task_id_present: Boolean(taskId),
      document_id_present: Boolean(fullDocumentId),
      full_document_id_present: Boolean(fullDocumentId),
      full_document_id_used: mapping.status === 'matched' && Boolean(fullDocumentId),
      document_id_candidate_present: Boolean(taskDocumentId || batchDocumentIdValue),
      task_document_mapping: mapping.status,
      task_document_mapping_match: mapping.matched,
      task_document_mapping_source: mapping.source,
      mapping_failure_reason_class: mapping.failure_reason_class,
      document_http_status: documentsReply.status,
      document_count: Array.isArray(documents) ? Math.min(999, documents.length) : 0,
      document_status: ['pending', 'processing', 'processed', 'failed'].includes(String(doc?.status || '')) ? String(doc.status) : 'not_found',
      document_chunks_count: Math.max(0, Math.min(999, Number(doc?.chunks_count || 0))),
      retrieval_http_status: healthReply.status,
      retrieval_ready: Boolean(doc) && healthReply.ok && Array.isArray(health?.documents) && !health.documents.some(item => String(item?.upload_task_id || '') === taskId),
      retrieval_unready_reason_count: health?.counts && typeof health.counts === 'object' ? Math.min(999, Object.keys(health.counts).length) : 0,
      video_segments_http_status: segmentsStatus,
      video_segment_count: Array.isArray(segments) ? Math.min(999, segments.length) : 0,
    }
  }, { kbName: upload.name, taskId: upload.task_id, batchDocumentId: upload.batch_document_id })
  const diagnosisComplete = result.task_document_mapping === 'matched'
  writeEvidence({
    schema_version: 2,
    browser: 'playwright',
    upload_diagnosis: true,
    runtime_status: diagnosisComplete ? 'passed' : 'incomplete',
    failure_class: diagnosisComplete ? null : `upload-diagnosis-mapping-${result.task_document_mapping}`,
    kb_created: true,
    upload_progress: upload.upload_progress,
    upload_terminal: upload.upload_terminal,
    upload_batch_status: upload.batch_status,
    observations: result,
  })
}

async function runPhaseARepresentative(page, account) {
  const prefix = 'browser-desktop-super_admin'
  await login(page, account, prefix)
  await sessionRole(page, 'super_admin')
  const video = await createKnowledgeBaseAndUpload(page, fixture, prefix)
  const agent = await createAgent(page, video.name)
  if (!agent.id || agent.status !== 200) fail('browser-phase-a-agent-create')
  const threadTitle = `${prefix}-thread`
  const threadId = await createConversation(page, agent.id, threadTitle)
  if (!threadId) fail('browser-phase-a-thread-create')
  const resources = await phaseAResourceObservations(page, agent.id, threadId, video.name)
  Object.assign(phaseAEvidence.observations, resources)
  if (resources.task_count !== 1 || !['completed', 'processed'].includes(resources.final_task_status)
    || !resources.kb_agent_binding_match || !resources.agent_thread_binding_match
    || !resources.retrieval_ready || resources.video_segment_count < 1) fail('browser-phase-a-resource-contract')
  const outcome = await verifyCitationRenderAndPlayback(page, agent.id, threadId, threadTitle, {}, prefix)
  return matrixObservation({ role: 'super_admin', viewport: 'desktop', path: 'new_video', fields: {
    query_started: outcome.query_started, stream_completed: outcome.stream_completed,
    citation_count: outcome.citation_count, video_segment_count: outcome.video_segment_count,
  } })
}

async function createCompatibilityKnowledgeBase(page, fixturePaths) {
  const name = `compat${Date.now().toString(36)}`
  const filenames = fixturePaths.map(path => path.split('/').pop())
  await page.goto(`${base}/knowledge`, { waitUntil: 'domcontentloaded', timeout: 30_000 })
  await page.getByRole('button', { name: '新建知识库' }).click()
  await page.getByPlaceholder('输入知识库名称…').fill(name)
  await page.getByRole('button', { name: '创建', exact: true }).click()
  const knowledgeBaseCard = page.getByRole('button', { name: `打开知识库 ${name}` })
  await knowledgeBaseCard.waitFor({ state: 'visible', timeout: 30_000 })
  await knowledgeBaseCard.click()
  await page.waitForURL(url => new URL(url).pathname.includes(`/knowledge/${encodeURIComponent(name)}`), { timeout: 30_000 })
  await page.getByRole('button', { name: /展开上传面板|收起上传面板/ }).click()
  await page.locator('#knowledge-upload-panel input[type=file]').setInputFiles(fixturePaths)
  await page.getByRole('button', { name: /全部上传 \(3\)/ }).click()
  for (const filename of filenames) {
    await page.getByText(filename, { exact: true }).waitFor({ state: 'visible', timeout: 30_000 })
  }
  const complete = await page.waitForFunction(async ({ kbName, expected }) => {
    const saved = JSON.parse(localStorage.getItem('raganything_auth') || 'null')
    const response = await fetch(`/api/upload/tasks?kb=${encodeURIComponent(kbName)}`, { headers: { Authorization: `Bearer ${saved?.token || ''}` } })
    const body = await response.json().catch(() => ({}))
    const tasks = Array.isArray(body?.tasks) ? body.tasks : []
    return expected.every(filename => tasks.some(task => task?.filename === filename && ['processed', 'completed'].includes(task?.status)))
  }, { kbName: name, expected: filenames }, { timeout: 600_000, polling: 1_000 }).then(() => true).catch(() => false)
  if (!complete) fail('browser-nonvideo-terminal')
  await page.getByText('已可检索').last().waitFor({ state: 'visible', timeout: 30_000 })
  return { name, filenames }
}

async function createAgent(page, kb) {
  return page.evaluate(async kbName => {
    const saved = JSON.parse(localStorage.getItem('raganything_auth') || 'null')
    const response = await fetch('/api/agents', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${saved?.token || ''}` },
      body: JSON.stringify({ name: 'video uat', kb_name: kbName, query_mode: 'hybrid', agent_mode: 'none', include_references: true }),
    })
    const body = await response.json().catch(() => ({}))
    return {
      id: response.ok ? String(body?.agent?.id || '') : '',
      status: response.status,
    }
  }, kb)
}

async function verifyAgentBinding(page, agentId, kb) {
  return page.evaluate(async ({ id, kbName }) => {
    const saved = JSON.parse(localStorage.getItem('raganything_auth') || 'null')
    const response = await fetch('/api/agents', {
      headers: { Authorization: `Bearer ${saved?.token || ''}` },
    })
    const body = await response.json().catch(() => ({}))
    const agents = Array.isArray(body?.agents) ? body.agents : []
    return {
      accessible: response.ok,
      count: agents.length,
      matches: response.ok && agents.some(agent => (
        String(agent?.id || '') === id && agent?.kb_name === kbName
      )),
    }
  }, { id: agentId, kbName: kb })
}

async function createConversation(page, agentId, title = 'video-uat') {
  return page.evaluate(async ({ id, conversationTitle }) => {
    const saved = JSON.parse(localStorage.getItem('raganything_auth') || 'null')
    const response = await fetch(`/api/agents/${encodeURIComponent(id)}/conversations?title=${encodeURIComponent(conversationTitle)}`, {
      method: 'POST', headers: { Authorization: `Bearer ${saved?.token || ''}` },
    })
    const body = await response.json().catch(() => ({}))
    return response.ok ? String(body?.thread?.id || '') : ''
  }, { id: agentId, conversationTitle: title })
}

async function verifyThreadNavigationContract(page, agentId, targetThreadId, prefix) {
  const decoyThreadId = await createConversation(page, agentId, `${prefix}-decoy`)
  if (!decoyThreadId || decoyThreadId === targetThreadId) fail('browser-thread-contract-fixture')
  const targetPath = `/api/agents/${encodeURIComponent(agentId)}/conversations/${encodeURIComponent(targetThreadId)}`
  const decoyPath = `/api/agents/${encodeURIComponent(agentId)}/conversations/${encodeURIComponent(decoyThreadId)}`
  const listPath = `/api/agents/${encodeURIComponent(agentId)}/conversations`
  const targetTitle = `${prefix}-target`
  const decoyTitle = `${prefix}-decoy`
  const targetMarker = `${prefix}-target-message`
  const decoyMarker = `${prefix}-decoy-message`
  const diagnosis = {
    thread_query_present: true,
    thread_query_value_present: Boolean(targetThreadId),
    thread_list_count: 0,
    thread_list_order_matches_expected: false,
    decoy_thread_present: false,
    target_thread_present: false,
    initial_navigation_path_matches_target: false,
    selected_thread_matches_target: false,
    detail_request_status: 0,
    detail_response_thread_matches_target: false,
    target_detail_request_count: 0,
    decoy_detail_request_count: 0,
    target_detail_response_count: 0,
    decoy_detail_response_count: 0,
    decoy_detail_response_thread_matches_decoy: false,
    stale_response_started: false,
    stale_response_released: false,
    stale_response_ignored: false,
    navigation_path_matches_target: false,
    active_thread_matches_target: false,
    query_started: false,
    query_completed: false,
    sse_done_received: false,
    persisted_message_thread_matches_target: false,
    console_error_count: 0,
    page_error_count: 0,
    timeout_or_abort: false,
    page_ready: false,
    sidebar_locator_count: 0,
    main_conversation_locator_count: 0,
    target_thread_locator_count: 0,
    active_thread_match: false,
    decoy_locator_count: 0,
    conversation_locator_unique_visible: false,
    request_response_counts_match_expected: false,
  }
  const navigationTrace = createNavigationTrace()
  diagnosis.navigation_trace = navigationTrace
  let tracePhase = 'unknown'
  let phaseStartedAt = Date.now()
  const startTracePhase = phase => {
    tracePhase = phase
    phaseStartedAt = Date.now()
    traceNavigation(navigationTrace, phase, 'started', {}, phaseStartedAt)
  }
  let releaseDecoy
  const decoyGate = new Promise(resolve => { releaseDecoy = resolve })
  let decoyEntered
  const decoyRequest = new Promise(resolve => { decoyEntered = resolve })
  let consoleErrorCount = 0
  let pageErrorCount = 0
  const onConsole = message => { if (message.type() === 'error') consoleErrorCount += 1 }
  const onPageError = () => { pageErrorCount += 1 }
  const json = payload => ({ contentType: 'application/json', body: JSON.stringify(payload) })
  try {
    page.on('console', onConsole)
    page.on('pageerror', onPageError)
    await page.route(`**${listPath}`, route => route.fulfill(json({
      threads: [
        { id: decoyThreadId, title: decoyTitle },
        { id: targetThreadId, title: targetTitle },
      ],
    })))
    await page.route(`**${targetPath}`, route => {
      if (route.request().method() !== 'GET') return route.fallback()
      diagnosis.target_detail_request_count += 1
      diagnosis.target_detail_response_count += 1
      return route.fulfill(json({
      thread: { id: targetThreadId, messages: [{ msg_id: `${prefix}-target-id`, role: 'assistant', content: targetMarker }] },
      }))
    })
    await page.route(`**${decoyPath}`, async route => {
      if (route.request().method() !== 'GET') return route.fallback()
      diagnosis.decoy_detail_request_count += 1
      decoyEntered()
      await decoyGate
      diagnosis.decoy_detail_response_count += 1
      await route.fulfill(json({
        thread: { id: decoyThreadId, messages: [{ msg_id: `${prefix}-decoy-id`, role: 'assistant', content: decoyMarker }] },
      }))
    })

    startTracePhase('goto_started')
    const initialDetail = page.waitForResponse(response => matchesExactDetailResponse(response, targetPath), { timeout: 30_000 })
    traceNavigation(navigationTrace, 'detail_wait_started', 'started', {}, phaseStartedAt)
    await page.goto(`${base}/agents/${encodeURIComponent(agentId)}?thread=${encodeURIComponent(targetThreadId)}`, { waitUntil: 'domcontentloaded', timeout: 30_000 })
    traceNavigation(navigationTrace, 'goto_completed', 'completed', { final_safe_pathname: '/agents/:agent?thread=:target' }, phaseStartedAt)
    tracePhase = 'detail_wait_started'
    phaseStartedAt = Date.now()
    const initialResponse = await initialDetail
    traceNavigation(navigationTrace, 'detail_response_resolved', 'completed', {}, phaseStartedAt)
    const initialBody = await initialResponse.json().catch(() => ({}))
    diagnosis.detail_request_status = boundedCount(initialResponse.status())
    traceNavigation(navigationTrace, 'detail_response_status', 'observed', { http_status: diagnosis.detail_request_status }, phaseStartedAt)
    diagnosis.detail_response_thread_matches_target = initialResponse.ok()
      && String(initialBody?.thread?.id || '') === String(targetThreadId)
    if (!diagnosis.detail_response_thread_matches_target) {
      recordNavigationFailure(navigationTrace, 'active_thread_mismatch', 'detail_response_identity')
      fail('browser-thread-contract-detail-response')
    }
    diagnosis.initial_navigation_path_matches_target = new URL(page.url()).pathname === `/agents/${encodeURIComponent(agentId)}`
      && new URL(page.url()).searchParams.get('thread') === targetThreadId
    if (!diagnosis.initial_navigation_path_matches_target) {
      recordNavigationFailure(navigationTrace, 'active_thread_mismatch', 'initial_navigation_path')
      fail('browser-thread-contract-initial-navigation-path')
    }
    const conversation = navigationConversationLocator(page)
    const threadList = navigationThreadListLocator(page)
    startTracePhase('page_ready')
    await page.waitForFunction(() => document.readyState !== 'loading' && Boolean(document.querySelector('.agent-chat-page')), null, { timeout: 30_000 })
    diagnosis.page_ready = true
    traceNavigation(navigationTrace, 'page_ready', 'completed', { ready: true, agent_page_present: true }, phaseStartedAt)
    startTracePhase('conversation_wait_started')
    diagnosis.main_conversation_locator_count = boundedCount(await conversation.count())
    traceNavigation(navigationTrace, 'main_conversation_locator_count', 'observed', { count: diagnosis.main_conversation_locator_count }, phaseStartedAt)
    await conversation.waitFor({ state: 'visible', timeout: 30_000 })
    const conversationLocatorCount = boundedCount(await conversation.count())
    diagnosis.conversation_locator_unique_visible = conversationLocatorCount === 1
    traceNavigation(navigationTrace, 'conversation_locator_count', 'observed', { count: conversationLocatorCount }, phaseStartedAt)
    traceNavigation(navigationTrace, 'conversation_wait_completed', 'completed', {}, phaseStartedAt)
    if (!diagnosis.conversation_locator_unique_visible) {
      recordNavigationFailure(navigationTrace, 'conversation_locator_timeout', 'conversation_locator_count')
      fail('browser-thread-contract-conversation-locator')
    }
    startTracePhase('active_thread_assertion_started')
    diagnosis.sidebar_locator_count = boundedCount(await threadList.count())
    traceNavigation(navigationTrace, 'sidebar_locator_count', 'observed', { count: diagnosis.sidebar_locator_count }, phaseStartedAt)
    await threadList.waitFor({ state: 'visible', timeout: 30_000 })
    const targetThread = threadList.getByRole('button', { name: `对话: ${targetTitle}` })
    const decoyThread = threadList.getByRole('button', { name: `对话: ${decoyTitle}` })
    diagnosis.target_thread_locator_count = boundedCount(await targetThread.count())
    diagnosis.decoy_locator_count = boundedCount(await decoyThread.count())
    traceNavigation(navigationTrace, 'target_thread_locator_count', 'observed', { count: diagnosis.target_thread_locator_count }, phaseStartedAt)
    traceNavigation(navigationTrace, 'decoy_locator_count', 'observed', { count: diagnosis.decoy_locator_count }, phaseStartedAt)
    const listed = await threadList.getByRole('button').evaluateAll(nodes => nodes.map(node => String(node.getAttribute('aria-label') || '')))
    const threadLabels = listed.filter(label => label.startsWith('对话:'))
    diagnosis.thread_list_count = boundedCount(threadLabels.length)
    diagnosis.decoy_thread_present = threadLabels.includes(`对话: ${decoyTitle}`)
    diagnosis.target_thread_present = threadLabels.includes(`对话: ${targetTitle}`)
    diagnosis.thread_list_order_matches_expected = threadLabels.length === 2
      && threadLabels[0] === `对话: ${decoyTitle}`
      && threadLabels[1] === `对话: ${targetTitle}`
    diagnosis.selected_thread_matches_target = await navigationActiveThreadMatches(page, targetTitle)
    diagnosis.active_thread_match = diagnosis.selected_thread_matches_target
    traceNavigation(navigationTrace, 'active_thread_match', 'observed', { matches_target: diagnosis.active_thread_match }, phaseStartedAt)
    traceNavigation(navigationTrace, 'active_thread_matches_target', 'observed', { matches_target: diagnosis.selected_thread_matches_target }, phaseStartedAt)
    if (!diagnosis.selected_thread_matches_target || !diagnosis.thread_list_order_matches_expected || !diagnosis.decoy_thread_present || !diagnosis.target_thread_present) {
      recordNavigationFailure(navigationTrace, 'active_thread_mismatch', 'active_thread_assertion')
      fail('browser-thread-contract-selection')
    }
    startTracePhase('decoy_click_started')
    await decoyThread.click()
    traceNavigation(navigationTrace, 'decoy_click_completed', 'completed', {}, phaseStartedAt)
    tracePhase = 'decoy_request_entered'
    phaseStartedAt = Date.now()
    await decoyRequest
    traceNavigation(navigationTrace, 'decoy_request_entered', 'completed', {}, phaseStartedAt)
    const targetResponse = page.waitForResponse(response => matchesExactDetailResponse(response, targetPath), { timeout: 30_000 })
    startTracePhase('target_click_started')
    await targetThread.click()
    traceNavigation(navigationTrace, 'target_click_completed', 'completed', {}, phaseStartedAt)
    tracePhase = 'target_response_wait_started'
    phaseStartedAt = Date.now()
    await targetResponse
    traceNavigation(navigationTrace, 'target_response_resolved', 'completed', {}, phaseStartedAt)
    startTracePhase('target_active_wait_started')
    await page.waitForFunction(title => [...document.querySelectorAll('[role="button"][aria-current="true"]')].some(node => node.getAttribute('aria-label') === `对话: ${title}`), targetTitle, { timeout: 30_000 })
    traceNavigation(navigationTrace, 'target_active_wait_completed', 'completed', {}, phaseStartedAt)
    const staleResponse = page.waitForResponse(response => matchesExactDetailResponse(response, decoyPath), { timeout: 30_000 })
    diagnosis.stale_response_started = true
    startTracePhase('decoy_response_release_started')
    releaseDecoy()
    diagnosis.stale_response_released = true
    traceNavigation(navigationTrace, 'decoy_response_release_completed', 'completed', {}, phaseStartedAt)
    tracePhase = 'decoy_response_wait_started'
    phaseStartedAt = Date.now()
    const decoyResponse = await staleResponse
    traceNavigation(navigationTrace, 'decoy_response_resolved', 'completed', {}, phaseStartedAt)
    const decoyBody = await decoyResponse.json().catch(() => ({}))
    diagnosis.decoy_detail_response_thread_matches_decoy = decoyResponse.ok()
      && String(decoyBody?.thread?.id || '') === String(decoyThreadId)
    startTracePhase('stale_state_assertion_started')
    await page.waitForFunction(({ threadTitle, targetText, decoyText }) => {
      const root = document.querySelector('.agent-chat-main')
      const sidebar = document.querySelector('.agent-chat-sidebar')
      const text = root?.textContent || ''
      const active = [...(sidebar?.querySelectorAll('[role="button"][aria-current="true"]') || [])].some(node => node.getAttribute('aria-label') === `对话: ${threadTitle}`)
      return active && text.includes(targetText) && !text.includes(decoyText)
    }, { threadTitle: targetTitle, targetText: targetMarker, decoyText: decoyMarker }, { timeout: 30_000 })
    traceNavigation(navigationTrace, 'stale_state_assertion', 'completed', { target_preserved: true }, phaseStartedAt)
    traceNavigation(navigationTrace, 'stale_state_assertion_completed', 'completed', {}, phaseStartedAt)
    diagnosis.stale_response_ignored = diagnosis.decoy_detail_response_thread_matches_decoy
    if (!diagnosis.stale_response_ignored) {
      recordNavigationFailure(navigationTrace, 'stale_response_overwrite', 'stale_response')
      fail('browser-thread-contract-stale-response')
    }
    startTracePhase('reload_detail_wait_started')
    traceNavigation(navigationTrace, 'reload_started', 'started', {}, phaseStartedAt)
    const reloadedDetail = page.waitForResponse(response => matchesExactDetailResponse(response, targetPath), { timeout: 30_000 })
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 30_000 })
    const reloadResponse = await reloadedDetail
    traceNavigation(navigationTrace, 'reload_completed', 'completed', { http_status: boundedCount(reloadResponse.status()) }, phaseStartedAt)
    traceNavigation(navigationTrace, 'reload_detail_completed', 'completed', { http_status: boundedCount(reloadResponse.status()) }, phaseStartedAt)
    diagnosis.navigation_path_matches_target = new URL(page.url()).pathname === `/agents/${encodeURIComponent(agentId)}`
      && new URL(page.url()).searchParams.get('thread') === targetThreadId
    diagnosis.active_thread_matches_target = await navigationActiveThreadMatches(page, targetTitle)
    diagnosis.persisted_message_thread_matches_target = await page.waitForFunction(({ threadTitle, targetText }) => {
      const root = document.querySelector('.agent-chat-main')
      const sidebar = document.querySelector('.agent-chat-sidebar')
      const active = [...(sidebar?.querySelectorAll('[role="button"][aria-current="true"]') || [])].some(node => node.getAttribute('aria-label') === `对话: ${threadTitle}`)
      return active && (root?.textContent || '').includes(targetText)
    }, { threadTitle: targetTitle, targetText: targetMarker }, { timeout: 30_000 }).then(() => true).catch(() => false)
    diagnosis.request_response_counts_match_expected = diagnosis.target_detail_request_count === 3
      && diagnosis.target_detail_response_count === 3
      && diagnosis.decoy_detail_request_count === 1
      && diagnosis.decoy_detail_response_count === 1
    if (!diagnosis.navigation_path_matches_target || !diagnosis.active_thread_matches_target || !diagnosis.persisted_message_thread_matches_target || !diagnosis.request_response_counts_match_expected) {
      recordNavigationFailure(navigationTrace, 'stale_response_overwrite', 'reload_state')
      fail('browser-thread-contract-reload')
    }
    if (consoleErrorCount !== 0 || pageErrorCount !== 0) {
      recordNavigationFailure(navigationTrace, 'active_thread_mismatch', 'client_error_counts')
      fail('browser-thread-contract-client-errors')
    }
    navigationTrace.failure_class = null
    traceNavigation(navigationTrace, 'timeout_stage', 'observed', { value: 'none' }, phaseStartedAt)
    traceNavigation(navigationTrace, 'failure_class', 'observed', { value: 'none' }, phaseStartedAt)
  } catch (error) {
    diagnosis.timeout_or_abort = error?.name === 'TimeoutError' || error?.name === 'AbortError'
    navigationTrace.timeout_or_abort = diagnosis.timeout_or_abort
    if (!navigationTrace.failure_class) {
      const failureClass = tracePhase === 'goto_started'
        ? 'goto_timeout'
        : tracePhase === 'detail_wait_started'
          ? 'detail_response_timeout'
          : tracePhase === 'conversation_wait_started'
            ? 'conversation_locator_timeout'
            : tracePhase === 'active_thread_assertion_started'
              ? 'active_thread_mismatch'
              : tracePhase === 'target_click_started' || tracePhase === 'target_response_wait_started'
              ? 'target_response_timeout'
              : tracePhase === 'target_active_wait_started'
                ? 'target_active_thread_timeout'
                : tracePhase === 'decoy_click_started' || tracePhase === 'decoy_request_entered' || tracePhase === 'decoy_response_release_started' || tracePhase === 'decoy_response_wait_started'
                  ? 'decoy_response_timeout'
                  : tracePhase === 'stale_state_assertion_started'
                    ? 'stale_state_assertion'
                  : tracePhase === 'reload_detail_wait_started'
                    ? 'reload_detail_timeout'
                    : 'unknown'
      recordNavigationFailure(navigationTrace, failureClass, tracePhase)
    }
    traceNavigation(navigationTrace, 'timeout_stage', 'observed', { value: navigationTrace.timeout_stage || 'unknown' }, phaseStartedAt)
    traceNavigation(navigationTrace, 'failure_class', 'observed', { value: navigationTrace.failure_class || 'unknown' }, phaseStartedAt)
    throw error
  } finally {
    releaseDecoy?.()
    diagnosis.console_error_count = consoleErrorCount
    diagnosis.page_error_count = pageErrorCount
    page.off('console', onConsole)
    page.off('pageerror', onPageError)
    await page.unroute(`**${listPath}`).catch(() => {})
    await page.unroute(`**${targetPath}`).catch(() => {})
    await page.unroute(`**${decoyPath}`).catch(() => {})
    threadNavigationDiagnosis = diagnosis
  }
  return diagnosis
}

async function createNavigationFixture(page, runId) {
  return page.evaluate(async probeRunId => {
    const saved = JSON.parse(localStorage.getItem('raganything_auth') || 'null')
    const headers = { Authorization: `Bearer ${saved?.token || ''}` }
    const kb = `nav${String(probeRunId).replace(/[^a-z0-9]/gi, '').slice(-16)}`
    const createKb = await fetch(`/api/kb/create?kb_name=${encodeURIComponent(kb)}`, { method: 'POST', headers })
    if (!createKb.ok) return { created: false, agentId: '' }
    const createAgent = await fetch('/api/agents', {
      method: 'POST',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'navigation probe', kb_name: kb, query_mode: 'hybrid', agent_mode: 'none', include_references: true }),
    })
    const body = await createAgent.json().catch(() => ({}))
    return { created: createAgent.ok, agentId: createAgent.ok ? String(body?.agent?.id || '') : '' }
  }, runId)
}

function navigationOnlyMode() {
  return process.env.VIDEO_BROWSER_NAVIGATION_ONLY === '1'
}

function setupNavigationOnlyMode() {
  return process.env.VIDEO_BROWSER_SETUP_NAVIGATION_ONLY === '1'
}

function citationOnlyMode() {
  return process.env.VIDEO_BROWSER_CITATION_ONLY === '1'
}

function navigationConversationLocator(page) {
  return page.locator('.agent-chat-main')
}

function navigationThreadListLocator(page) {
  return page.locator('.agent-chat-sidebar')
}

async function navigationActiveThreadMatches(page, title) {
  return await navigationThreadListLocator(page)
    .getByRole('button', { name: `对话: ${title}` })
    .getAttribute('aria-current') === 'true'
}

function navigationOnlyInputs() {
  const runId = String(process.env.VIDEO_BROWSER_NAVIGATION_RUN_ID || '')
  const owner = String(process.env.VIDEO_BROWSER_NAVIGATION_OWNER || '')
  const composeProject = String(process.env.VIDEO_BROWSER_NAVIGATION_COMPOSE_PROJECT || '')
  const runOwned = process.env.VIDEO_BROWSER_NAVIGATION_RUN_OWNED === 'true'
  const runRoot = String(process.env.VIDEO_BROWSER_NAVIGATION_RUN_ROOT || '')
  const profilePath = String(process.env.VIDEO_BROWSER_NAVIGATION_PROFILE_DIR || '')
  const manifestPath = String(process.env.VIDEO_BROWSER_NAVIGATION_MANIFEST_PATH || '')
  if (!base || !accountsPath || !evidencePath || !runId || !owner || !composeProject || !runOwned || !fs.existsSync(accountsPath)) {
    fail('browser-navigation-only-input')
  }

  const { root, resolved: profileDir } = resolveRunOwnedPath(runRoot, profilePath, 'profile')
  const { resolved: resolvedManifestPath } = resolveRunOwnedPath(root, manifestPath, 'manifest')
  const runtimeDirectories = [
    ['home', String(process.env.HOME || '')],
    ['cache', String(process.env.XDG_CACHE_HOME || '')],
    ['config', String(process.env.XDG_CONFIG_HOME || '')],
  ]
  if (fs.existsSync(profileDir) || !fs.existsSync(resolvedManifestPath)) fail('browser-navigation-only-profile')
  for (const [label, directory] of runtimeDirectories) {
    const { resolved } = resolveRunOwnedPath(root, directory, label)
    fs.mkdirSync(resolved, { recursive: true })
    assertExistingRunOwnedPath(root, resolved, label)
  }

  let manifest = {}
  try {
    manifest = JSON.parse(fs.readFileSync(resolvedManifestPath, 'utf8'))
  } catch {
    fail('browser-navigation-only-manifest')
  }
  const manifestProfile = String(manifest?.browser_profile?.path || manifest?.artifacts?.browser_profile || '')
  if (String(manifest?.run_id || '') !== runId
    || String(manifest?.owner || '') !== owner
    || String(manifest?.compose_project || '') !== composeProject
    || manifestProfile !== 'browser-profile') {
    fail('browser-navigation-only-identity')
  }
  assertExistingRunOwnedPath(root, resolvedManifestPath, 'manifest')
  return { runId, owner, composeProject, runRoot: root, profileDir, manifestPath: resolvedManifestPath }
}

function setupNavigationResource(inputs) {
  let manifest = {}
  try {
    manifest = JSON.parse(fs.readFileSync(inputs.manifestPath, 'utf8'))
  } catch {
    fail('browser-setup-navigation-manifest')
  }
  const resource = manifest?.browser_setup_navigation
  if (!resource || resource.owned_by_run !== true) fail('browser-setup-navigation-resource-unavailable')
  const agentId = String(resource.agent_id || '')
  const threadId = String(resource.target_thread_id || '')
  if (!agentId || !threadId) fail('browser-setup-navigation-resource-unavailable')
  return { agentId, threadId }
}

async function runSetupNavigationOnly() {
  updateCurrentStage('browser-setup-navigation-input')
  setupNavigationObservation = createSetupNavigationObservation()
  let inputs
  let context
  let page
  let dispose = () => {}
  let runError
  try {
    inputs = navigationOnlyInputs()
    updateCurrentStage('browser-setup-navigation-manifest')
    const resource = setupNavigationResource(inputs)
    const accounts = JSON.parse(fs.readFileSync(accountsPath, 'utf8'))
    if (!accounts?.admin) fail('browser-setup-navigation-accounts')
    updateCurrentStage('browser-setup-navigation-browser-launch')
    context = await chromium.launchPersistentContext(inputs.profileDir, {
      headless: true, executablePath: chromiumExecutablePath(), viewport: viewports.desktop,
    })
    assertExistingRunOwnedPath(inputs.runRoot, inputs.profileDir, 'setup-navigation-profile')
    updateCurrentStage('browser-setup-navigation-page-create')
    page = await context.newPage()
    dispose = installSetupNavigationObservability(page, setupNavigationObservation)
    updateCurrentStage('browser-setup-navigation-login')
    await login(page, accounts.admin, 'browser-setup-navigation')
    updateCurrentStage('browser-setup-navigation-target-goto-start')
    const targetUrl = `${base}/agents/${encodeURIComponent(resource.agentId)}?thread=${encodeURIComponent(resource.threadId)}`
    setupNavigationObservation.target_url = safeLocation(targetUrl)
    const response = await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 30_000 })
    setupNavigationObservation.navigation.goto_status = boundedCount(response?.status())
    updateCurrentStage('browser-setup-navigation-target-goto-complete')
  } catch (error) {
    runError = error
    setupNavigationObservation.automation_error = shortAutomationError(error)
  } finally {
    if (page) {
      setupNavigationObservation.final_location = safeLocation(page.url())
      if (runError) await captureSetupNavigationFailure(page, inputs, setupNavigationObservation)
    }
    dispose()
    if (context) {
      try { await context.close() } catch (error) { runError = runError || error }
    }
    if (inputs?.profileDir) {
      try { fs.rmSync(inputs.profileDir, { recursive: true, force: true }) } catch (error) { runError = runError || error }
    }
  }
  if (runError && !setupNavigationObservation.automation_error) setupNavigationObservation.automation_error = shortAutomationError(runError)
  const blocked = String(runError?.code || '').includes('resource-unavailable')
  writeEvidence({
    schema_version: 4,
    browser: 'playwright',
    browser_setup_navigation_only: true,
    runtime_status: blocked ? 'blocked' : (runError ? 'run_failed' : 'passed'),
    failure_class: runError ? 'navigation' : null,
    current_stage: setupNavigationObservation.current_stage,
    setup_navigation: setupNavigationObservation,
    old_run_evidence_used_as_result: false,
    probe_process_created_docker_resources: 0,
  })
  if (runError) process.exitCode = 1
}

async function runNavigationOnly() {
  currentStage = 'browser-navigation-only-input'
  let inputs
  let context
  let navigationError
  let fixtureCreated = false
  const profile = { created: false, used: false, context_closed: false, cleaned: false }
  try {
    inputs = navigationOnlyInputs()
    const accounts = JSON.parse(fs.readFileSync(accountsPath, 'utf8'))
    if (!accounts?.admin) fail('browser-navigation-only-accounts')
    context = await chromium.launchPersistentContext(inputs.profileDir, {
      headless: true,
      executablePath: chromiumExecutablePath(),
      viewport: viewports.desktop,
    })
    profile.created = fs.existsSync(inputs.profileDir)
    if (!profile.created) fail('browser-navigation-only-profile-create')
    assertExistingRunOwnedPath(inputs.runRoot, inputs.profileDir, 'profile')
    const page = await context.newPage()
    profile.used = Boolean(page)
    await login(page, accounts.admin, 'browser-navigation-only')
    const fixture = await createNavigationFixture(page, inputs.runId)
    if (!fixture.created || !fixture.agentId) fail('browser-navigation-only-fixture')
    fixtureCreated = true
    const manifest = JSON.parse(fs.readFileSync(inputs.manifestPath, 'utf8'))
    manifest.browser_navigation_fixture = { owned_by_run: true, created: true }
    fs.writeFileSync(inputs.manifestPath, JSON.stringify(manifest, null, 2), 'utf8')
    const targetThreadId = await createConversation(page, fixture.agentId, `${inputs.runId}-target`)
    if (!targetThreadId) fail('browser-navigation-only-target-thread')
    currentStage = 'browser-navigation-only-probe'
    await verifyThreadNavigationContract(page, fixture.agentId, targetThreadId, inputs.runId)
  } catch (error) {
    navigationError = error
  } finally {
    if (context) {
      try {
        await context.close()
        profile.context_closed = true
      } catch (error) {
        navigationError = navigationError || error
      }
    }
    if (inputs?.profileDir) {
      try {
        fs.rmSync(inputs.profileDir, { recursive: true, force: true })
        profile.cleaned = !fs.existsSync(inputs.profileDir)
      } catch (error) {
        navigationError = navigationError || error
      }
    }
  }

  const trace = threadNavigationDiagnosis?.navigation_trace
  const explicitFailure = String(navigationError?.code || '')
  const traceFailure = String(trace?.failure_class || '')
  const failureClass = explicitFailure || traceFailure || (navigationError ? 'unknown' : '')
  const complete = !navigationError && profile.created && profile.used && profile.context_closed && profile.cleaned
  writeEvidence({
    schema_version: 2,
    browser: 'playwright',
    browser_navigation_only: true,
    run_id: String(inputs?.runId || ''),
    owner: String(inputs?.owner || ''),
    compose_project: String(inputs?.composeProject || ''),
    runtime_status: complete ? 'passed' : 'run_failed',
    browser_profile: profile,
    browser_fixture: { owned_by_run: fixtureCreated, created: fixtureCreated },
    old_run_evidence_used_as_result: false,
    probe_process_created_docker_resources: 0,
    navigation_probe: threadNavigationDiagnosis || null,
    ...(complete ? {} : { failure_class: failureClass || 'unknown' }),
  })
  if (!complete || failureClass === 'unknown') process.exitCode = 1
}

function citationOnlyInputs() {
  const runId = String(process.env.VIDEO_BROWSER_CITATION_RUN_ID || '')
  const owner = String(process.env.VIDEO_BROWSER_CITATION_OWNER || '')
  const composeProject = String(process.env.VIDEO_BROWSER_CITATION_COMPOSE_PROJECT || '')
  const runOwned = process.env.VIDEO_BROWSER_CITATION_RUN_OWNED === 'true'
  const runRoot = String(process.env.VIDEO_BROWSER_CITATION_RUN_ROOT || '')
  const profilePath = String(process.env.VIDEO_BROWSER_CITATION_PROFILE_DIR || '')
  const manifestPath = String(process.env.VIDEO_BROWSER_CITATION_MANIFEST_PATH || '')
  if (!base || !accountsPath || !evidencePath || !runId || !owner || !composeProject || !runOwned || !fs.existsSync(accountsPath)) {
    fail('browser-citation-only-input')
  }
  const { root, resolved: profileDir } = resolveRunOwnedPath(runRoot, profilePath, 'citation-profile')
  const { resolved: resolvedManifestPath } = resolveRunOwnedPath(root, manifestPath, 'citation-manifest')
  if (fs.existsSync(profileDir) || !fs.existsSync(resolvedManifestPath)) fail('browser-citation-only-profile')
  const manifest = JSON.parse(fs.readFileSync(resolvedManifestPath, 'utf8'))
  const manifestProfile = String(manifest?.browser_profile?.path || manifest?.artifacts?.browser_profile || '')
  if (String(manifest?.run_id || '') !== runId
    || String(manifest?.owner || '') !== owner
    || String(manifest?.compose_project || manifest?.project || '') !== composeProject
    || manifestProfile !== 'browser-profile') {
    fail('browser-citation-only-identity')
  }
  return { runId, owner, composeProject, runRoot: root, profileDir, resourcePath: citationResourcePath }
}

function citationProbePassed(probe) {
  const required = [
    'query_submit_started', 'query_submit_completed', 'target_query_identity_observed',
    'stream_response_started', 'stream_response_completed', 'sse_done_received',
    'sse_done_thread_matches_target', 'streaming_assistant_found', 'streaming_citation_found',
    'streaming_video_player_found', 'player_visible', 'persisted_conversation_get',
    'persisted_assistant_found', 'persisted_video_segments_found', 'reload_started',
    'reload_completed', 'reloaded_player_visible',
  ]
  return probe.failure_class === null
    && required.every(field => probe[field] === true)
    && probe.sse_done_citation_count > 0
    && probe.authorized_media_status === 200
    && probe.range_status === 206
}

function citationDiagnosisPassed(probe) {
  return probe.failure_class === null
    && probe.query_submit_started === true
    && probe.query_submit_completed === true
    && probe.target_query_identity_observed === true
    && probe.query_thread_matches_target === true
    && probe.sse_done_received === true
    && probe.sse_done_thread_matches_target === true
    && ['absent', 'non_array', 'array'].includes(probe.sse_done_citations_shape)
    && ['absent', 'non_array', 'array'].includes(probe.persisted_assistant_citations_shape)
    && ['absent', 'string', 'array', 'object', 'unknown'].includes(probe.retrieval_context_shape)
    && ['matched', 'not_matched', 'unavailable'].includes(probe.retrieval_video_anchor_detection)
    && probe.persisted_conversation_get === true
    && probe.persisted_assistant_found === true
    && probe.persisted_query_identity_matches_done === true
    && probe.query_id_thread_id_match === true
}

function setCitationProbeFailure(probe, stageName, failureClass) {
  if (probe.failure_class !== null) return
  citationProbeFailure(probe, stageName, failureClass)
}

async function verifyCitationOnlyPage(page, resource, probe) {
  const diagnostics = installPageDiagnostics(page)
  let targetQueryId = ''
  try {
    diagnostics.expectThread(resource.agentId, resource.threadId)
    const detailPath = `/api/agents/${encodeURIComponent(resource.agentId)}/conversations/${encodeURIComponent(resource.threadId)}`
    const initialDetail = page.waitForResponse(response => matchesExactDetailResponse(response, detailPath), { timeout: 30_000 })
    await page.goto(`${base}/agents/${encodeURIComponent(resource.agentId)}?thread=${encodeURIComponent(resource.threadId)}`, { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await initialDetail
    const conversation = navigationConversationLocator(page)
    await conversation.waitFor({ state: 'visible', timeout: 30_000 })
    if (!await navigationActiveThreadMatches(page, resource.threadTitle)) {
      setCitationProbeFailure(probe, 'target_query_identity_observed', 'active_thread_mismatch')
      return
    }
    const queryPath = `/api/agents/${encodeURIComponent(resource.agentId)}/query/stream`
    const responseStartedAt = Date.now()
    probe.response_wait_started = true
    recordCitationProbe(probe, 'response_wait_started', responseStartedAt, { observed: true })
    await installCitationResponseObserver(page, queryPath, resource.threadId)
    const existingAssistantCount = await conversation.locator('.agent-chat-messages > div.group').count()
    const submitStartedAt = Date.now()
    probe.query_submit_started = true
    recordCitationProbe(probe, 'query_submit_started', submitStartedAt, { observed: true })
    await conversation.locator('textarea').first().fill('如何检查腐蚀漏液')
    await conversation.locator('textarea').first().press('Enter')
    probe.query_submit_completed = true
    recordCitationProbe(probe, 'query_submit_completed', submitStartedAt, { observed: true })

    let observed
    try {
      await page.waitForFunction(() => {
        const state = window.__ragCitationResponseObserver?.snapshot()
        return state?.response_received === true || state?.request_failed === true
      }, { timeout: 30_000 })
      observed = await readCitationResponseObserver(page)
    } catch {
      setCitationProbeFailure(probe, 'response_received', 'response_wait_timeout')
      return
    }
    if (!observed) {
      setCitationProbeFailure(probe, 'response_received', 'response_wait_timeout')
      return
    }
    probe.response_received = observed.response_received === true
    probe.response_status = boundedCount(observed.response_status)
    probe.response_content_type = observed.response_content_type === 'text/event-stream' ? 'text/event-stream' : 'other'
    probe.stream_response_started = probe.response_status === 200 && probe.response_content_type === 'text/event-stream'
    probe.body_read_started = observed.body_read_started === true
    probe.body_read_completed = observed.body_read_completed === true
    probe.body_read_error_class = typeof observed.body_read_error_class === 'string' ? observed.body_read_error_class : ''
    probe.body_byte_count = boundedCount(observed.body_byte_count)
    probe.request_finished = observed.request_finished === true
    probe.request_failed = observed.request_failed === true
    probe.request_failure = observed.request_failure && typeof observed.request_failure === 'object'
      ? {
        stage: String(observed.request_failure.stage || '').replace(/[^a-z0-9_-]/gi, '').slice(0, 80),
        path: String(observed.request_failure.path || '').replace(/\/agents\/[^/]+/, '/agents/:agent').slice(0, 160),
        reason_class: String(observed.request_failure.reason_class || '').replace(/[^a-z0-9_-]/gi, '').slice(0, 80),
      }
      : { stage: '', path: '', reason_class: '' }
    probe.done_received = observed.done_received === true
    probe.done_thread_matches_target = observed.done_thread_matches_target === true
    probe.done_citation_count = boundedCount(observed.done_citation_count)
    probe.sse_done_citations_shape = ['absent', 'non_array', 'array'].includes(observed.sse_done_citations_shape) ? observed.sse_done_citations_shape : 'absent'
    probe.sse_done_citations_count = probe.sse_done_citations_shape === 'array' ? boundedCount(observed.sse_done_citations_count) : null
    probe.retrieval_context_shape = ['absent', 'string', 'array', 'object', 'unknown'].includes(observed.retrieval_context_shape)
      ? observed.retrieval_context_shape
      : 'unknown'
    probe.retrieval_video_anchor_detection = ['matched', 'not_matched', 'unavailable'].includes(observed.retrieval_video_anchor_detection)
      ? observed.retrieval_video_anchor_detection
      : 'unavailable'
    probe.response_body_read_started = probe.body_read_started
    probe.response_body_read_completed = probe.body_read_completed
    probe.response_body_byte_count = probe.body_byte_count
    probe.sse_event_framing = observed.sse_event_framing === true
    probe.sse_line_count = boundedCount(observed.sse_line_count)
    probe.sse_data_line_count = boundedCount(observed.sse_data_line_count)
    probe.sse_json_parse_error_count = boundedCount(observed.json_parse_error_count)
    probe.stream_response_completed = probe.request_finished
    probe.sse_done_received = probe.done_received
    probe.sse_done_thread_matches_target = probe.done_thread_matches_target
    probe.sse_done_citation_count = probe.done_citation_count
    recordCitationProbe(probe, 'response_received', responseStartedAt, { observed: probe.response_received })
    recordCitationProbe(probe, 'response_status', responseStartedAt, { status: probe.response_status })
    recordCitationProbe(probe, 'response_content_type', responseStartedAt, { observed: probe.response_content_type === 'text/event-stream' })
    recordCitationProbe(probe, 'stream_response_started', responseStartedAt, { observed: probe.stream_response_started, status: probe.response_status })
    recordCitationProbe(probe, 'body_read_started', responseStartedAt, { observed: probe.body_read_started })
    recordCitationProbe(probe, 'body_read_completed', responseStartedAt, { observed: probe.body_read_completed })
    recordCitationProbe(probe, 'body_read_error_class', responseStartedAt, { observed: Boolean(probe.body_read_error_class) })
    recordCitationProbe(probe, 'body_byte_count', responseStartedAt, { count: probe.body_byte_count })
    recordCitationProbe(probe, 'request_finished', responseStartedAt, { observed: probe.request_finished })
    recordCitationProbe(probe, 'request_failed', responseStartedAt, { observed: probe.request_failed })
    recordCitationProbe(probe, 'response_body_read_started', responseStartedAt, { observed: probe.response_body_read_started })
    recordCitationProbe(probe, 'response_body_read_completed', responseStartedAt, { observed: probe.response_body_read_completed })
    recordCitationProbe(probe, 'response_body_byte_count', responseStartedAt, { count: probe.response_body_byte_count })
    recordCitationProbe(probe, 'sse_event_framing', responseStartedAt, { observed: probe.sse_event_framing })
    recordCitationProbe(probe, 'sse_line_count', responseStartedAt, { count: probe.sse_line_count })
    recordCitationProbe(probe, 'sse_data_line_count', responseStartedAt, { count: probe.sse_data_line_count })
    recordCitationProbe(probe, 'sse_json_parse_error_count', responseStartedAt, { count: probe.sse_json_parse_error_count })
    recordCitationProbe(probe, 'done_received', responseStartedAt, { observed: probe.done_received })
    recordCitationProbe(probe, 'done_thread_matches_target', responseStartedAt, { observed: probe.done_thread_matches_target })
    recordCitationProbe(probe, 'done_citation_count', responseStartedAt, { count: probe.done_citation_count })
    recordCitationProbe(probe, 'stream_response_completed', responseStartedAt, { observed: probe.stream_response_completed })
    recordCitationProbe(probe, 'sse_done_received', responseStartedAt, { observed: probe.sse_done_received })
    recordCitationProbe(probe, 'sse_done_thread_matches_target', responseStartedAt, { observed: probe.sse_done_thread_matches_target })
    recordCitationProbe(probe, 'sse_done_citation_count', responseStartedAt, { count: probe.sse_done_citation_count })
    if (probe.request_failed) {
      setCitationProbeFailure(probe, observed.timeout_stage || 'body_read_completed', observed.failure_class || 'sse_body_read_failure')
      return
    }
    if (!probe.sse_event_framing) {
      setCitationProbeFailure(probe, 'sse_event_framing', 'sse_event_parse_failure')
      return
    }
    probe.query_thread_matches_target = diagnostics.queryThreadMatchesExpected() && probe.done_thread_matches_target
    if (!probe.stream_response_started || !probe.query_thread_matches_target) {
      setCitationProbeFailure(probe, 'stream_response_started', 'sse_contract_mismatch')
      return
    }
    if (!probe.sse_done_received) {
      setCitationProbeFailure(probe, 'sse_done_received', 'sse_done_missing')
      return
    }
    if (!probe.sse_done_thread_matches_target) {
      setCitationProbeFailure(probe, 'sse_done_thread_matches_target', 'sse_done_thread_mismatch')
      return
    }
    const sseCitationsMissing = !probe.sse_done_citation_count
    targetQueryId = String(observed.done_query_id || '')
    probe.target_query_identity_observed = Boolean(targetQueryId)
    probe.server_done_query_id_present = probe.target_query_identity_observed
    probe.server_done_query_id_hash_or_bounded_presence = probe.target_query_identity_observed ? 'present' : 'absent'
    probe.dom_query_identity_available = false
    probe.dom_query_identity_diagnostic = 'product_dom_does_not_expose_server_query_id'
    recordCitationProbe(probe, 'target_query_identity_observed', submitStartedAt, { observed: probe.target_query_identity_observed })
    try {
      await page.waitForFunction(previousCount => document.querySelectorAll('.agent-chat-messages > div.group').length > previousCount, existingAssistantCount, { timeout: 30_000 })
    } catch {
      if (!sseCitationsMissing) {
        setCitationProbeFailure(probe, 'streaming_assistant_found', 'harness_contract_mismatch')
        return
      }
    }
    const assistant = conversation.locator('.agent-chat-messages > div.group').last()
    const streamingIdentity = await page.evaluate(() => {
      const root = document.querySelector('.agent-chat-main')
      const assistants = [...(root?.querySelectorAll('.agent-chat-messages > div.group') || [])]
      const current = assistants.at(-1)
      return {
        assistant_count: assistants.length,
        query_id_attribute_count: assistants.filter(node => node.hasAttribute('data-message-query-id')).length,
        client_id_attribute_count: assistants.filter(node => node.hasAttribute('data-message-id')).length,
        state: current?.getAttribute('data-message-state') || 'not_exposed_to_dom',
        text_present: Boolean(current?.textContent?.trim()),
      }
    })
    probe.streaming_assistant_count = boundedCount(streamingIdentity.assistant_count)
    probe.streaming_assistant_query_id_attribute_count = boundedCount(streamingIdentity.query_id_attribute_count)
    probe.streaming_assistant_client_id_attribute_count = boundedCount(streamingIdentity.client_id_attribute_count)
    probe.streaming_assistant_state = String(streamingIdentity.state || 'not_exposed_to_dom')
    probe.streaming_assistant_text_present = streamingIdentity.text_present === true
    probe.streaming_assistant_found = await assistant.count() === 1
    recordCitationProbe(probe, 'streaming_assistant_found', submitStartedAt, { observed: probe.streaming_assistant_found })
    const citation = assistant.locator('[data-video-segment-id]').first()
    probe.streaming_citation_found = await citation.count() === 1
    recordCitationProbe(probe, 'streaming_citation_found', submitStartedAt, { observed: probe.streaming_citation_found })
    const player = citation
    probe.streaming_video_player_found = await player.count() === 1
    recordCitationProbe(probe, 'streaming_video_player_found', submitStartedAt, { observed: probe.streaming_video_player_found })
    if (!probe.streaming_assistant_found || !probe.streaming_citation_found || !probe.streaming_video_player_found) {
      if (sseCitationsMissing) {
        // Continue to persisted inspection so a zero SSE citation is distinguishable from a persistence zero.
      } else {
      setCitationProbeFailure(probe, 'streaming_video_player_found', 'streaming_citation_render_missing')
      return
      }
    }
    try {
      await player.waitFor({ state: 'visible', timeout: 30_000 })
      probe.player_visible = true
      recordCitationProbe(probe, 'player_visible', submitStartedAt, { observed: true })
    } catch {
      recordCitationProbe(probe, 'player_visible', submitStartedAt, { observed: false })
      if (!sseCitationsMissing) {
        setCitationProbeFailure(probe, 'player_visible', 'player_render_missing')
        return
      }
    }
    const persistedStartedAt = Date.now()
    const persisted = await inspectPersistedConversation(page, resource.agentId, resource.threadId, targetQueryId)
    probe.persisted_conversation_get = persisted.conversationGetOk === true
    probe.persisted_assistant_found = persisted.lastAssistantPresent === true
    probe.persisted_video_segments_found = persisted.persistedVideoSegmentCount > 0
    probe.persisted_assistant_citations_shape = persisted.persistedAssistantCitationsShape
    probe.persisted_assistant_citations_count = persisted.persistedAssistantCitationsShape === 'array'
      ? boundedCount(persisted.persistedAssistantCitationsCount)
      : null
    probe.citation_video_segment_shape = persisted.citationVideoSegmentShape
    probe.citation_video_segment_count = boundedCount(persisted.citationVideoSegmentCount)
    probe.citation_media_id_present = persisted.citationMediaIdPresent === true
    probe.citation_document_id_present = persisted.citationDocumentIdPresent === true
    probe.persisted_query_identity_matches_done = persisted.lastAssistantQueryId === targetQueryId
    probe.persisted_assistant_query_id_present = Boolean(persisted.lastAssistantQueryId)
    probe.persisted_assistant_matches_done_id = probe.persisted_query_identity_matches_done
    probe.query_id_thread_id_match = probe.persisted_query_identity_matches_done && probe.query_thread_matches_target
    recordCitationProbe(probe, 'persisted_conversation_get', persistedStartedAt, { observed: probe.persisted_conversation_get })
    recordCitationProbe(probe, 'persisted_assistant_found', persistedStartedAt, { observed: probe.persisted_assistant_found })
    recordCitationProbe(probe, 'persisted_video_segments_found', persistedStartedAt, { observed: probe.persisted_video_segments_found })
    if (!citationDiagnosisOnly && sseCitationsMissing && !probe.persisted_assistant_citations_count) {
      setCitationProbeFailure(probe, 'persisted_video_segments_found', probe.retrieval_video_anchor_detection === 'matched' ? 'persisted_citation_missing' : 'retrieval_anchor_missing')
    }
    if (!probe.persisted_query_identity_matches_done) {
      setCitationProbeFailure(probe, 'persisted_assistant_found', 'persisted_query_identity_mismatch')
      return
    }
    if (citationDiagnosisOnly) return
    if (!probe.persisted_conversation_get || !probe.persisted_assistant_found || !probe.persisted_video_segments_found || !persisted.mediaPath) {
      setCitationProbeFailure(probe, 'persisted_video_segments_found', 'persisted_citation_missing')
      return
    }
    const reloadStartedAt = Date.now()
    probe.reload_started = true
    recordCitationProbe(probe, 'reload_started', reloadStartedAt, { observed: true })
    const detailCount = diagnostics.detailCount()
    const reloadDetail = diagnostics.waitForDetail(detailCount)
    try {
      await page.reload({ waitUntil: 'domcontentloaded', timeout: 30_000 })
      await reloadDetail
      probe.reload_completed = true
      recordCitationProbe(probe, 'reload_completed', reloadStartedAt, { observed: true })
    } catch {
      recordCitationProbe(probe, 'reload_completed', reloadStartedAt, { observed: false })
      setCitationProbeFailure(probe, 'reload_completed', 'reload_timeout')
      return
    }
    const reloadedPlayer = page.locator('.agent-chat-messages > div.group').last().locator('[data-video-segment-id]').first()
    try {
      await reloadedPlayer.waitFor({ state: 'visible', timeout: 30_000 })
      probe.reloaded_player_visible = true
      probe.reload_assistant_matches_done_id = probe.persisted_query_identity_matches_done ? 'persisted_query_id_match' : 'not_exposed_to_dom'
      recordCitationProbe(probe, 'reloaded_player_visible', reloadStartedAt, { observed: true })
    } catch {
      recordCitationProbe(probe, 'reloaded_player_visible', reloadStartedAt, { observed: false })
      setCitationProbeFailure(probe, 'reloaded_player_visible', 'reloaded_player_missing')
      return
    }
    const mediaStartedAt = Date.now()
    const media = await page.evaluate(async mediaPath => {
      const saved = JSON.parse(localStorage.getItem('raganything_auth') || 'null')
      const headers = { Authorization: `Bearer ${saved?.token || ''}` }
      const [normal, ranged] = await Promise.all([
        fetch(mediaPath, { headers }),
        fetch(mediaPath, { headers: { ...headers, Range: 'bytes=0-1' } }),
      ])
      return { normal_status: normal.status, range_status: ranged.status }
    }, persisted.mediaPath)
    probe.authorized_media_status = boundedCount(media.normal_status)
    probe.range_status = boundedCount(media.range_status)
    recordCitationProbe(probe, 'authorized_media_status', mediaStartedAt, { status: probe.authorized_media_status })
    recordCitationProbe(probe, 'range_status', mediaStartedAt, { status: probe.range_status })
    if (probe.authorized_media_status !== 200 || probe.range_status !== 206) {
      setCitationProbeFailure(probe, 'range_status', 'authorized_media_range_failure')
    }
  } catch (error) {
    const timeout = error?.name === 'TimeoutError'
    setCitationProbeFailure(probe, 'failure_class', timeout ? 'citation_probe_timeout' : 'citation_probe_automation')
  } finally {
    try {
      await removeCitationResponseObserver(page)
    } catch {
      if (probe.failure_class === null) {
        setCitationProbeFailure(probe, 'failure_class', 'citation_probe_automation')
      }
    }
    diagnostics.dispose()
  }
  if (probe.failure_class === null) {
    const completedAt = Date.now()
    recordCitationProbe(probe, 'timeout_stage', completedAt, { observed: false })
    recordCitationProbe(probe, 'failure_class', completedAt, { observed: false })
  }
}

async function runCitationOnly() {
  currentStage = 'browser-citation-only-input'
  let inputs
  let context
  let runError
  const profile = { created: false, used: false, context_closed: false, cleaned: false }
  const probe = createCitationProbe()
  citationOnlyState = { inputs: null, profile, probe, written: false }
  try {
    inputs = citationOnlyInputs()
    citationOnlyState.inputs = inputs
    const accounts = JSON.parse(fs.readFileSync(accountsPath, 'utf8'))
    if (!accounts?.admin) fail('browser-citation-only-accounts')
    context = await chromium.launchPersistentContext(inputs.profileDir, { headless: true, executablePath: chromiumExecutablePath(), viewport: viewports.desktop })
    profile.created = fs.existsSync(inputs.profileDir)
    if (!profile.created) fail('browser-citation-only-profile-create')
    assertExistingRunOwnedPath(inputs.runRoot, inputs.profileDir, 'citation-profile')
    const page = await context.newPage()
    profile.used = Boolean(page)
    await login(page, accounts.admin, 'browser-citation-only')
    const located = await findApiAcceptanceResource(page)
    if (citationDiagnosisOnly && inputs.resourcePath && fs.existsSync(inputs.resourcePath)) {
      try {
        const prepared = JSON.parse(fs.readFileSync(inputs.resourcePath, 'utf8'))
        if (prepared?.agent_id && prepared?.thread_id) {
          located.resource = {
            agentId: String(prepared.agent_id),
            threadId: String(prepared.thread_id),
            threadTitle: 'video-uat-api',
          }
          located.observations = { ...located.observations, agentKbMatch: true, conversationBound: true, uploadTerminalCount: 1, retrievalReady: true }
        }
      } catch { /* runner validates the bounded resource file */ }
    }
    if (!located.resource || !located.observations.sessionAuthOk || !located.observations.agentKbMatch || !located.observations.conversationBound || located.observations.uploadTerminalCount < 1 || !located.observations.retrievalReady) {
      setCitationProbeFailure(probe, 'failure_class', 'citation_resource_unavailable')
    } else {
      await verifyCitationOnlyPage(page, located.resource, probe)
    }
  } catch (error) {
    runError = error
    setCitationProbeFailure(probe, 'failure_class', error?.name === 'TimeoutError' ? 'citation_probe_timeout' : 'citation_probe_automation')
  } finally {
    if (context) {
      try {
        await context.close()
        profile.context_closed = true
      } catch {
        runError = runError || new Error('citation-context-close')
      }
    }
    if (inputs?.profileDir) {
      try {
        fs.rmSync(inputs.profileDir, { recursive: true, force: true })
        profile.cleaned = !fs.existsSync(inputs.profileDir)
      } catch {
        runError = runError || new Error('citation-profile-cleanup')
      }
    }
  }
  const complete = !runError && profile.created && profile.used && profile.context_closed && profile.cleaned
    && (citationDiagnosisOnly ? citationDiagnosisPassed(probe) : citationProbePassed(probe))
  if (!complete && probe.failure_class === null) setCitationProbeFailure(probe, 'failure_class', 'citation_probe_lifecycle_failure')
  writeEvidence({
    schema_version: 3,
    browser: 'playwright',
    browser_citation_only: true,
    browser_citation_diagnosis_only: citationDiagnosisOnly,
    run_id: String(inputs?.runId || ''),
    owner: String(inputs?.owner || ''),
    compose_project: String(inputs?.composeProject || ''),
    runtime_status: complete ? 'passed' : 'run_failed',
    browser_profile: profile,
    browser_fixture: { owned_by_run: true, created: true },
    old_run_evidence_used_as_result: false,
    probe_process_created_docker_resources: 0,
    citation_probe: probe,
  })
  citationOnlyState.written = true
  if (!complete) process.exitCode = 1
}

async function installSseSummary(page) {
  await page.evaluate(() => {
    window.__ragVideoSseSummary = (body, expectedThreadId = '') => {
      const summary = { doneReceived: false, doneFallback: false, doneThreadBound: false, doneThreadMatchesTarget: false, citationCount: 0, videoSegmentCitationCount: 0, retrievalContextPresent: false, retrievalVideoAnchorCount: 0 }
      for (const line of String(body || '').split('\n')) {
        if (!line.startsWith('data: ')) continue
        let event
        try { event = JSON.parse(line.slice(6)) } catch { continue }
        if (event?.type === 'retrieval') {
          summary.retrievalContextPresent = event.context_present === true
          summary.retrievalVideoAnchorCount = Number.isInteger(event.video_segment_anchor_count) ? event.video_segment_anchor_count : 0
        }
        if (event?.type === 'done') {
          summary.doneReceived = true
          summary.doneFallback = event.fallback === true
          summary.doneThreadBound = typeof event.thread_id === 'string' && event.thread_id.length > 0
          summary.doneThreadMatchesTarget = Boolean(expectedThreadId) && event.thread_id === expectedThreadId
          const citations = Array.isArray(event.citations) ? event.citations : []
          summary.citationCount = citations.length
          summary.videoSegmentCitationCount = citations.reduce((count, citation) => count + (Array.isArray(citation?.video_segments) ? citation.video_segments.length : citation?.video_segment ? 1 : 0), 0)
        }
      }
      return summary
    }
  })
}

async function queryAgentSse(page, agentId, threadId, retrievalOnly = false) {
  return page.evaluate(async ({ id, thread, onlyRetrieval }) => {
    const saved = JSON.parse(localStorage.getItem('raganything_auth') || 'null')
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 90_000)
    try {
      const response = await fetch(`/api/agents/${encodeURIComponent(id)}/query/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', Authorization: `Bearer ${saved?.token || ''}` },
        body: JSON.stringify({ query: '如何检查腐蚀漏液', ...(thread ? { thread_id: thread } : {}), ...(onlyRetrieval ? { retrieval_only: true } : {}) }),
        signal: controller.signal,
      })
      return { httpOk: response.ok, summary: window.__ragVideoSseSummary(await response.text(), thread) }
    } finally {
      clearTimeout(timer)
    }
  }, { id: agentId, thread: threadId, onlyRetrieval: retrievalOnly })
}

async function findApiAcceptanceResource(page) {
  return page.evaluate(async () => {
    const saved = JSON.parse(localStorage.getItem('raganything_auth') || 'null')
    const headers = { Authorization: `Bearer ${saved?.token || ''}` }
    const [identity, agentsReply] = await Promise.all([
      fetch('/api/auth/me', { headers }),
      fetch('/api/agents', { headers }),
    ])
    const agentsBody = await agentsReply.json().catch(() => ({}))
    const candidates = Array.isArray(agentsBody?.agents)
      ? agentsBody.agents.filter(agent => agent?.name === 'video acceptance')
      : []
    const agent = candidates.length === 1 ? candidates[0] : null
    if (!agent?.id || !agent?.kb_name) {
      return {
        resource: null,
        observations: {
          sessionAuthOk: identity.ok,
          agentCreated: false,
          agentListAccessible: agentsReply.ok,
          agentListCount: candidates.length,
        },
      }
    }
    const [threadsReply, tasksReply, healthReply] = await Promise.all([
      fetch(`/api/agents/${encodeURIComponent(agent.id)}/conversations`, { headers }),
      fetch(`/api/upload/tasks?kb=${encodeURIComponent(agent.kb_name)}`, { headers }),
      fetch(`/api/knowledge/retrieval-health?kb=${encodeURIComponent(agent.kb_name)}`, { headers }),
    ])
    const [threadsBody, tasksBody, healthBody] = await Promise.all([
      threadsReply.json().catch(() => ({})),
      tasksReply.json().catch(() => ({})),
      healthReply.json().catch(() => ({})),
    ])
    const threads = Array.isArray(threadsBody?.threads) ? threadsBody.threads : []
    const conversations = threads.filter(thread => thread?.title === 'video-uat-api')
    const tasks = Array.isArray(tasksBody?.tasks) ? tasksBody.tasks : []
    const terminal = tasks.filter(task => ['processed', 'completed'].includes(task?.status)).length
    return {
      resource: conversations.length === 1
        ? { agentId: String(agent.id), threadId: String(conversations[0].id), threadTitle: String(conversations[0].title) }
        : null,
      observations: {
        sessionAuthOk: identity.ok,
        agentCreated: Boolean(agent?.id),
        agentListAccessible: agentsReply.ok,
        agentListCount: candidates.length,
        agentKbMatch: Boolean(agent?.kb_name),
        conversationBound: conversations.length === 1,
        uploadTerminalCount: terminal,
        retrievalReady: healthReply.ok && Array.isArray(healthBody?.documents) && healthBody.documents.length === 0,
      },
    }
  })
}

async function inspectPersistedConversation(page, agentId, threadId, queryId) {
  return page.evaluate(async ({ id, thread, expectedQueryId }) => {
    const saved = JSON.parse(localStorage.getItem('raganything_auth') || 'null')
    const response = await fetch(`/api/agents/${encodeURIComponent(id)}/conversations/${encodeURIComponent(thread)}`, {
      headers: { Authorization: `Bearer ${saved?.token || ''}` },
    })
    const body = await response.json().catch(() => ({}))
    const messages = Array.isArray(body?.thread?.messages) ? body.thread.messages : []
    const assistant = messages.find(message => (
      message?.role === 'assistant' && String(message?.query_id || '') === String(expectedQueryId)
    ))
    const citationsPresent = Boolean(assistant) && Object.prototype.hasOwnProperty.call(assistant, 'citations')
    const citationsObservation = !citationsPresent
      ? { shape: 'absent', count: null }
      : (Array.isArray(assistant.citations) ? { shape: 'array', count: assistant.citations.length } : { shape: 'non_array', count: null })
    const citations = citationsObservation.shape === 'array' ? assistant.citations : []
    const videoObservation = { shape: 'absent', count: 0, mediaIdPresent: false, documentIdPresent: false }
    for (const citation of citations) {
      if (!citation || typeof citation !== 'object') continue
      const hasSegments = Object.prototype.hasOwnProperty.call(citation, 'video_segments')
      const hasSegment = Object.prototype.hasOwnProperty.call(citation, 'video_segment')
      if (!hasSegments && !hasSegment) continue
      if (Array.isArray(citation.video_segments)) {
        videoObservation.shape = 'array'
        videoObservation.count = Math.max(0, Math.min(999, videoObservation.count + citation.video_segments.length))
      } else if (citation.video_segment && typeof citation.video_segment === 'object') {
        if (videoObservation.shape === 'absent') videoObservation.shape = 'object'
        videoObservation.count = Math.max(0, Math.min(999, videoObservation.count + 1))
      } else if (videoObservation.shape === 'absent') {
        videoObservation.shape = 'unknown'
      }
      if (typeof citation.media_id === 'string' && citation.media_id) videoObservation.mediaIdPresent = true
      if (typeof citation.document_id === 'string' && citation.document_id) videoObservation.documentIdPresent = true
    }
    const segmentCounts = citations.map(citation => Array.isArray(citation?.video_segments) ? citation.video_segments.length : 0)
    const videoCitation = citations.find(citation => (
      Array.isArray(citation?.video_segments) && citation.video_segments.length > 0 && typeof citation?.media_url === 'string'
    ))
    return {
      conversationGetOk: response.ok,
      lastAssistantPresent: Boolean(assistant),
      lastAssistantId: String(assistant?.msg_id || assistant?.id || ''),
      lastAssistantQueryId: String(assistant?.query_id || ''),
      persistedCitationCount: citations.length,
      persistedAssistantCitationsShape: citationsObservation.shape,
      persistedAssistantCitationsCount: citationsObservation.count,
      citationVideoSegmentShape: videoObservation.shape,
      citationVideoSegmentCount: videoObservation.count,
      citationMediaIdPresent: videoObservation.mediaIdPresent,
      citationDocumentIdPresent: videoObservation.documentIdPresent,
      persistedVideoSegmentCount: segmentCounts.reduce((total, count) => total + count, 0),
      expectedPlayerSegmentCount: Array.isArray(videoCitation?.video_segments) ? videoCitation.video_segments.length : 0,
      expectedRanges: Array.isArray(videoCitation?.video_segments) ? videoCitation.video_segments.map(segment => ({
        start_seconds: Math.floor(Number(segment?.start_ms || 0) / 1000),
        end_seconds: Math.floor(Number(segment?.end_ms || 0) / 1000),
      })) : [],
      mediaPath: typeof videoCitation?.media_url === 'string' ? videoCitation.media_url : '',
      documentNames: citations.map(citation => String(citation?.document_name || '')).filter(Boolean),
    }
  }, { id: agentId, thread: threadId, expectedQueryId: queryId })
}

async function verifyCitationRenderAndPlayback(page, agentId, threadId, threadTitle, observations, prefix) {
  observations = observations || {}
  const recordPhaseAPath = phaseAMode() && prefix === 'browser-desktop-super_admin'
  if (recordPhaseAPath && !phaseAEvidence) phaseAEvidence = createPhaseAEvidence()
  stage(prefix, 'new-video-agent-navigation')
  const navigationTrace = createNavigationTrace()
  threadNavigationDiagnosis = { source: 'new-video-agent-navigation', navigation_trace: navigationTrace }
  const diagnostics = installPageDiagnostics(page)
  const navigationStartedAt = Date.now()
  if (recordPhaseAPath) {
    updateCurrentStage('browser-phase-a-navigation-start')
    if (setupNavigationObservation) setupNavigationObservation.target_url = safeLocation(`${base}/agents/${encodeURIComponent(agentId)}?thread=${encodeURIComponent(threadId)}`)
  }
  diagnostics.expectThread(agentId, threadId)
  const detailPath = `/api/agents/${encodeURIComponent(agentId)}/conversations/${encodeURIComponent(threadId)}`
  const detailStartedAt = Date.now()
  const detailResponse = page.waitForResponse(response => matchesExactDetailResponse(response, detailPath), { timeout: 30_000 })
  traceNavigation(navigationTrace, 'detail_wait_started', 'started', {}, detailStartedAt)
  try {
    const gotoStartedAt = Date.now()
    traceNavigation(navigationTrace, 'goto_started', 'started', {}, gotoStartedAt)
    const navigationResponse = await page.goto(`${base}/agents/${encodeURIComponent(agentId)}?thread=${encodeURIComponent(threadId)}`, { waitUntil: 'domcontentloaded', timeout: 30_000 })
    if (recordPhaseAPath && setupNavigationObservation) setupNavigationObservation.navigation.goto_status = boundedCount(navigationResponse?.status())
    traceNavigation(navigationTrace, 'goto_completed', 'completed', { final_safe_pathname: '/agents/:agent?thread=:target' }, gotoStartedAt)
  } catch (error) {
    if (recordPhaseAPath) failPhaseA('navigation', error, navigationStartedAt)
    recordNavigationFailure(navigationTrace, error?.name === 'TimeoutError' ? 'goto_timeout' : 'unknown', 'goto')
    navigationTrace.timeout_or_abort = error?.name === 'TimeoutError' || error?.name === 'AbortError'
    throw error
  }
  let initialDetail
  try {
    initialDetail = await detailResponse
    traceNavigation(navigationTrace, 'detail_response_resolved', 'completed', {}, detailStartedAt)
    traceNavigation(navigationTrace, 'detail_response_status', 'observed', { http_status: boundedCount(initialDetail.status()) }, detailStartedAt)
    observations.pageConversationGetCompleted = true
  } catch (error) {
    if (recordPhaseAPath) failPhaseA('navigation', error, navigationStartedAt)
    recordNavigationFailure(navigationTrace, error?.name === 'TimeoutError' ? 'detail_response_timeout' : 'unknown', 'detail_response')
    navigationTrace.timeout_or_abort = error?.name === 'TimeoutError' || error?.name === 'AbortError'
    throw error
  }
  const conversation = navigationConversationLocator(page)
  try {
    const conversationStartedAt = Date.now()
    traceNavigation(navigationTrace, 'conversation_wait_started', 'started', {}, conversationStartedAt)
    await conversation.waitFor({ state: 'visible', timeout: 30_000 })
    traceNavigation(navigationTrace, 'conversation_locator_count', 'observed', { count: boundedCount(await conversation.count()) }, conversationStartedAt)
    traceNavigation(navigationTrace, 'conversation_wait_completed', 'completed', {}, conversationStartedAt)
  } catch (error) {
    if (recordPhaseAPath) failPhaseA('navigation', error, navigationStartedAt)
    recordNavigationFailure(navigationTrace, error?.name === 'TimeoutError' ? 'conversation_locator_timeout' : 'unknown', 'conversation_locator')
    navigationTrace.timeout_or_abort = error?.name === 'TimeoutError' || error?.name === 'AbortError'
    throw error
  }
  const activeThreadStartedAt = Date.now()
  traceNavigation(navigationTrace, 'active_thread_assertion_started', 'started', {}, activeThreadStartedAt)
  observations.conversationBound = await navigationActiveThreadMatches(page, threadTitle)
  traceNavigation(navigationTrace, 'active_thread_matches_target', 'observed', { matches_target: observations.conversationBound }, activeThreadStartedAt)
  if (!observations.conversationBound) {
    recordNavigationFailure(navigationTrace, 'active_thread_mismatch', 'active_thread_assertion')
    if (recordPhaseAPath) failPhaseA('navigation', new Error('active_thread_mismatch'), navigationStartedAt)
    fail('browser-active-thread-mismatch')
  }
  if (recordPhaseAPath) {
    updateCurrentStage('browser-phase-a-navigation-complete')
    recordPhaseA('navigation', 'passed', navigationStartedAt, { count: 1 })
  }
  const existingQueryIds = await conversation.locator('[data-testid="assistant-message"][data-message-query-id]').evaluateAll(nodes => (
    nodes.map(node => node.getAttribute('data-message-query-id')).filter(Boolean)
  ))
  const input = conversation.locator('textarea').first()
  stage(prefix, 'new-video-query-submit')
  const querySubmitStartedAt = Date.now()
  try {
    if (recordPhaseAPath) await installCitationResponseObserver(page, `/api/agents/${encodeURIComponent(agentId)}/query/stream`, threadId)
    await input.fill('如何检查腐蚀漏液')
    await input.press('Enter')
    if (recordPhaseAPath) recordPhaseA('query_submit', 'passed', querySubmitStartedAt, { count: 1 })
  } catch (error) {
    if (recordPhaseAPath) failPhaseA('query_submit', error, querySubmitStartedAt)
    throw error
  }
  stage(prefix, 'new-video-citation-render')
  let targetQueryId
  let phaseAPersisted = null
  let assistantDomStartedAt = 0
  if (recordPhaseAPath) {
    assistantDomStartedAt = Date.now()
    const assistantLocator = page.waitForFunction(previousQueryIds => {
      const root = document.querySelector('.agent-chat-main')
      const assistant = [...(root?.querySelectorAll('[data-testid="assistant-message"]') || [])].find(node => {
        const queryId = node.getAttribute('data-message-query-id')
        return queryId && !previousQueryIds.includes(queryId)
      })
      return assistant?.getAttribute('data-message-query-id') || null
    }, existingQueryIds, { timeout: 90_000 }).then(async handle => ({ query_id: await handle.jsonValue(), ended_at: Date.now() }))
    const observerWaitStartedAt = Date.now()
    const observerWait = readCitationResponseObserver(page)
    const persistedWait = observerWait.then(async sse => {
      if (!sse?.done_query_id) return { attempted: false, started_at: 0, ended_at: 0, value: null }
      const persistedStartedAt = Date.now()
      try {
        const value = await inspectPersistedConversation(page, agentId, threadId, sse.done_query_id)
        return { attempted: true, started_at: persistedStartedAt, ended_at: Date.now(), value }
      } catch {
        return { attempted: true, started_at: persistedStartedAt, ended_at: Date.now(), value: null }
      }
    })
    const [assistantResult, sseResult, persistedResult] = await Promise.allSettled([assistantLocator, observerWait, persistedWait])
    await removeCitationResponseObserver(page)
    const sse = sseResult.status === 'fulfilled' ? sseResult.value : null
    const failedSseStage = recordPhaseASse(sse, observerWaitStartedAt)
    if (failedSseStage) {
      setPhaseAFailure(failedSseStage, String(sse?.timeout_stage || '') ? { name: 'TimeoutError' } : null)
      fail(`browser-phase-a-${failedSseStage}`)
    }
    phaseAPersisted = persistedResult.status === 'fulfilled'
      ? persistedResult.value
      : { attempted: true, started_at: observerWaitStartedAt, ended_at: Date.now(), value: null }
    const failedPersistedStage = recordPhaseAPersisted(phaseAPersisted)
    if (failedPersistedStage) {
      setPhaseAFailure(failedPersistedStage, null)
      fail(`browser-phase-a-${failedPersistedStage}`)
    }
    if (assistantResult.status !== 'fulfilled') {
      failPhaseA('assistant_dom', assistantResult.reason, assistantDomStartedAt)
      throw assistantResult.reason
    }
    targetQueryId = assistantResult.value.query_id
    recordPhaseA('assistant_dom', 'passed', assistantDomStartedAt, { count: 1, ended_at: assistantResult.value.ended_at })
    if (targetQueryId !== sse.done_query_id) {
      recordPhaseA('assistant_dom', 'failed', assistantDomStartedAt)
      setPhaseAFailure('assistant_dom', null)
      fail('browser-phase-a-assistant_dom')
    }
  } else {
    targetQueryId = await page.waitForFunction(previousQueryIds => {
      const root = document.querySelector('.agent-chat-main')
      const assistant = [...(root?.querySelectorAll('[data-testid="assistant-message"]') || [])].find(node => {
        const queryId = node.getAttribute('data-message-query-id')
        return queryId && !previousQueryIds.includes(queryId)
      })
      return assistant?.getAttribute('data-message-query-id') || null
    }, existingQueryIds, { timeout: 90_000 }).then(handle => handle.jsonValue())
  }
  if (!targetQueryId) fail(recordCitationDiagnosis('query_not_started', observations))
  observations.queryThreadMatchesTarget = diagnostics.queryThreadMatchesExpected()
  if (recordPhaseAPath && phaseAEvidence?.observations) phaseAEvidence.observations.query_thread_matches_target = observations.queryThreadMatchesTarget === true
  if (!observations.queryThreadMatchesTarget) fail(recordCitationDiagnosis('locator_binding_mismatch', observations))
  const targetAssistant = conversation.locator(`[data-testid="assistant-message"][data-message-query-id="${targetQueryId}"]`)
  const targetCitation = targetAssistant.locator('[data-testid="citation-block"]:has([data-testid="video-segment-player"])').first()
  const renderedVideoPlayer = targetAssistant.locator('[data-testid="citation-block"]:has([data-testid="video-segment-player"])').first().getByTestId('video-segment-player').first()
  const citationDomStartedAt = Date.now()
  const streamingCitationState = await page.waitForFunction(queryId => {
    const assistant = document.querySelector(`[data-testid="assistant-message"][data-message-query-id="${queryId}"]`)
    return assistant?.getAttribute('data-message-state') === 'streaming'
      && Boolean(assistant.querySelector('[data-testid="citation-block"] [data-testid="video-segment-player"]'))
  }, targetQueryId, { timeout: 30_000 }).then(() => true).catch(() => false)
  observations.domVideoSegmentsLabel = streamingCitationState
  if (!streamingCitationState) {
    if (recordPhaseAPath) failPhaseA('citation_dom', new Error('stream_citation_state_missing'), citationDomStartedAt)
    fail(recordCitationDiagnosis('stream_citation_state_missing', observations))
  }
  if (recordPhaseAPath) recordPhaseA('citation_dom', 'passed', citationDomStartedAt, { count: 1 })
  const playerDomStartedAt = Date.now()
  try {
    await renderedVideoPlayer.waitFor({ state: 'visible', timeout: 90_000 })
    if (recordPhaseAPath) recordPhaseA('player_dom', 'passed', playerDomStartedAt, { count: 1 })
  } catch (error) {
    if (recordPhaseAPath) failPhaseA('player_dom', error, playerDomStartedAt)
    fail(recordCitationDiagnosis('player_render_missing', observations))
  }
  const visibilityStartedAt = Date.now()
  const dom = await page.evaluate(({ expectedThreadTitle, queryId }) => {
    const facts = node => {
      if (!node) return { present: false, visible: false, display: '', visibility: '', opacity: '' }
      const style = window.getComputedStyle(node)
      const rect = node.getBoundingClientRect()
      return {
        present: true,
        visible: style.display !== 'none' && style.visibility === 'visible' && style.opacity !== '0' && rect.width > 0 && rect.height > 0,
        display: style.display,
        visibility: style.visibility,
        opacity: style.opacity,
      }
    }
    const conversation = document.querySelector('.agent-chat-main')
    const sidebar = document.querySelector('.agent-chat-sidebar')
    const assistants = [...(conversation?.querySelectorAll('[data-testid="assistant-message"]') || [])]
    const assistant = assistants.find(assistant => assistant.getAttribute('data-message-query-id') === queryId)
    const citations = [...(assistant?.querySelectorAll('[data-testid="citation-block"]') || [])]
    const citationIndex = citations.findIndex(citation => citation.querySelector('[data-testid="video-segment-player"]'))
    const citation = citations[citationIndex]
    const player = citation?.querySelector('[data-testid="video-segment-player"]')
    const ranges = [...(player?.querySelectorAll('button') || [])].map(button => {
      const match = String(button.textContent || '').match(/(\d+):(\d{2})\s*-\s*(\d+):(\d{2})/)
      return match ? {
        start_seconds: Number(match[1]) * 60 + Number(match[2]),
        end_seconds: Number(match[3]) * 60 + Number(match[4]),
      } : null
    }).filter(Boolean)
    return {
      expected_active_thread_match: [...(sidebar?.querySelectorAll('[role="button"][aria-current="true"]') || [])]
        .some(node => node.getAttribute('aria-label') === `对话: ${expectedThreadTitle}`),
      assistant_message_id: assistant?.getAttribute('data-message-id') || '',
      assistant_query_id: assistant?.getAttribute('data-message-query-id') || '',
      citation_media_id: citation?.getAttribute('data-citation-media-id') || '',
      assistant: { ...facts(assistant), count: boundedCount(assistants.length) },
      citation: { ...facts(citation), count: boundedCount(citations.length) },
      player: { ...facts(player), segment_count: boundedCount(Number(player?.getAttribute('data-video-segment-count') || 0)) },
      ranges,
    }
  }, { expectedThreadTitle: threadTitle, queryId: targetQueryId })
  observations.playerSegmentCount = dom.player.segment_count
  observations.videoSegmentCitationCount = dom.player.segment_count
  observations.citationCount = dom.citation.count
  if (recordPhaseAPath) {
    recordPhaseA('visibility', dom.assistant.visible && dom.citation.visible && dom.player.visible ? 'passed' : 'failed', visibilityStartedAt, { count: Number(dom.assistant.visible) + Number(dom.citation.visible) + Number(dom.player.visible) })
  }
  if (!dom.expected_active_thread_match || !dom.assistant.present || !dom.citation.present || !dom.player.present || !dom.assistant_message_id || dom.assistant_query_id !== targetQueryId || !dom.citation_media_id || !dom.player.segment_count) fail(recordCitationDiagnosis('locator_binding_mismatch', observations))
  if (!dom.assistant.visible || !dom.citation.visible || !dom.player.visible) fail('browser-dom-visibility')
  stage(prefix, 'new-video-range-assertion')
  const ordered = dom.ranges.length >= 2 && dom.ranges.every((range, index) => index === 0 || range.start_seconds >= dom.ranges[index - 1].start_seconds) && new Set(dom.ranges.map(range => `${range.start_seconds}-${range.end_seconds}`)).size === dom.ranges.length
  if (!ordered) fail('browser-video-adjacent-ranges')
  const segmentIndex = dom.ranges.findIndex(range => range.start_seconds > 0)
  const expectedStart = dom.ranges[segmentIndex]?.start_seconds
  if (!Number.isFinite(expectedStart) || expectedStart <= 0) fail('browser-video-nonzero-range')
  const player = targetCitation.getByTestId('video-segment-player').first()
  const segmentButtons = player.locator('button')
  stage(prefix, 'new-video-segment-click')
  await segmentButtons.nth(segmentIndex).click()
  const video = player.locator('video')
  stage(prefix, 'new-video-element')
  await video.waitFor({ state: 'visible', timeout: 30_000 })
  stage(prefix, 'new-video-seek')
  const seek = await video.evaluate(async (element, start) => {
    const until = Date.now() + 30_000
    while (Date.now() < until) {
      if (element.readyState >= HTMLMediaElement.HAVE_METADATA && !element.seeking) {
        const actual = Number(element.currentTime)
        const delta = Math.abs(actual - start)
        if (Number.isFinite(actual) && delta <= 1) return { actual_seconds: actual, delta_seconds: delta, controlled_blob: element.currentSrc.startsWith('blob:') }
      }
      await new Promise(resolve => setTimeout(resolve, 50))
    }
    return null
  }, expectedStart)
  if (!seek || !seek.controlled_blob) fail('browser-video-seek-tolerance')
  stage(prefix, 'new-video-playing')
  const playing = await video.evaluate(element => !element.paused && element.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA)
  if (!playing) fail('browser-video-playback')
  if (await targetCitation.getByRole('alert').isVisible().catch(() => false)) fail('browser-video-playback-alert')
  stage(prefix, 'new-video-conversation-refresh')
  const reloadStartedAt = Date.now()
  const reloadDetailCount = diagnostics.detailCount()
  const reloadDetailWait = diagnostics.waitForDetail(reloadDetailCount)
  try {
    traceNavigation(navigationTrace, 'reload_detail_wait_started', 'started', {}, reloadStartedAt)
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 30_000 })
    const reloadDetail = await reloadDetailWait
    traceNavigation(navigationTrace, 'reload_detail_completed', 'completed', { http_status: boundedCount(reloadDetail.status) }, reloadStartedAt)
  } catch (error) {
    if (recordPhaseAPath) failPhaseA('reload', error, reloadStartedAt)
    recordNavigationFailure(navigationTrace, error?.name === 'TimeoutError' ? 'reload_detail_timeout' : 'unknown', 'reload_detail')
    navigationTrace.timeout_or_abort = error?.name === 'TimeoutError' || error?.name === 'AbortError'
    throw error
  }
  const reloadedAssistant = page.locator(`[data-testid="assistant-message"][data-message-query-id="${targetQueryId}"]`)
  try {
    await reloadedAssistant.waitFor({ state: 'visible', timeout: 30_000 })
    if (recordPhaseAPath) recordPhaseA('reload', 'passed', reloadStartedAt)
  } catch (error) {
    if (recordPhaseAPath) failPhaseA('reload', error, reloadStartedAt)
    throw error
  }
  if (await reloadedAssistant.getAttribute('data-message-state') !== 'persisted') fail(recordCitationDiagnosis('stream_not_completed', observations))
  const reloadedCitation = reloadedAssistant.locator(`[data-testid="citation-block"][data-citation-media-id="${dom.citation_media_id}"]`)
  await reloadedCitation.getByTestId('video-segment-player').waitFor({ state: 'visible', timeout: 30_000 })
  diagnostics.clearExpectedThread()
  const persisted = recordPhaseAPath
    ? phaseAPersisted?.value
    : await inspectPersistedConversation(page, agentId, threadId, targetQueryId)
  if (!persisted.conversationGetOk || !persisted.lastAssistantPresent || !persisted.persistedCitationCount || !persisted.persistedVideoSegmentCount) fail(recordCitationDiagnosis('persisted_refresh_overwrite', observations))
  if (persisted.lastAssistantId !== dom.assistant_message_id || persisted.lastAssistantQueryId !== targetQueryId || persisted.expectedPlayerSegmentCount !== dom.player.segment_count || JSON.stringify(persisted.expectedRanges) !== JSON.stringify(dom.ranges)) fail(recordCitationDiagnosis('persisted_refresh_overwrite', observations))
  stage(prefix, 'new-video-authorized-media')
  const authorizedMediaObservation = await page.evaluate(async mediaPath => {
    const saved = JSON.parse(localStorage.getItem('raganything_auth') || 'null')
    const headers = { Authorization: `Bearer ${saved?.token || ''}` }
    const media_started_at = Date.now()
    const normal = fetch(mediaPath, { headers })
    const range_started_at = Date.now()
    const ranged = fetch(mediaPath, { headers: { ...headers, Range: 'bytes=0-1' } })
    const [normalReply, rangedReply] = await Promise.all([normal, ranged])
    const ended_at = Date.now()
    return { media: normalReply.status, media_range: rangedReply.status, content_range: rangedReply.headers.get('content-range') || '', media_started_at, range_started_at, ended_at }
  }, persisted.mediaPath)
  const { media_started_at, range_started_at, ended_at, ...authorizedMedia } = authorizedMediaObservation
  if (recordPhaseAPath) {
    recordPhaseA('media', authorizedMedia.media === 200 ? 'passed' : 'failed', media_started_at, { http_status: authorizedMedia.media, ended_at })
    recordPhaseA('range', authorizedMedia.media_range === 206 && Boolean(authorizedMedia.content_range) ? 'passed' : 'failed', range_started_at, { http_status: authorizedMedia.media_range, ended_at })
  }
  if (authorizedMedia.media !== 200 || authorizedMedia.media_range !== 206 || !authorizedMedia.content_range) fail('browser-authorized-media-range')
  const errors = diagnostics.errors()
  if (recordPhaseAPath) {
    phaseAEvidence.client = {
      console_error_count: boundedCount(errors.console), page_error_count: boundedCount(errors.page),
      dom_mutation_count: boundedCount(dom.assistant.count + dom.citation.count + dom.player.segment_count),
      locator_count: boundedCount(await conversation.count() + await targetAssistant.count() + await targetCitation.count() + await renderedVideoPlayer.count()),
    }
    phaseAEvidence.status = 'passed'
  }
  if (Object.values(errors).some(value => value !== 0)) fail('browser-client-errors')
  navigationTrace.failure_class = null
  return {
    adjacent_ranges: true,
    video_playback: true,
    seek,
    expected_thread_id: threadId,
    expected_active_thread_match: dom.expected_active_thread_match,
    page_detail_get: diagnostics.detail(),
    assistant_message_id: dom.assistant_message_id,
    assistant: dom.assistant,
    citation: dom.citation,
    player: dom.player,
      ranges: dom.ranges,
      query_id: targetQueryId,
      query_thread_matches_target: observations.queryThreadMatchesTarget === true,
      query_started: true,
      stream_completed: true,
      stream_citation_state_present: streamingCitationState,
      persisted_refresh_preserved: true,
      locator_binding_matches: true,
      player_rendered: true,
      citation_count: persisted.persistedCitationCount,
      video_segment_count: persisted.persistedVideoSegmentCount,
      player_count: 1,
    range_label_count: dom.ranges.length,
    navigation_trace: navigationTrace,
    errors,
    media_path: persisted.mediaPath,
    authorized_media: authorizedMedia,
  }
}

async function verifyApiResourceParity(browser, admin) {
  const context = await browser.newContext({ viewport: viewports.desktop })
  const page = await context.newPage()
  const prefix = 'browser-desktop-super_admin-api-resource'
  try {
    currentStage = `${prefix}-login`
    await login(page, admin, prefix)
    currentStage = `${prefix}-discover`
    const located = await findApiAcceptanceResource(page)
    const observations = {
      ...located.observations,
      retrievalContextPresent: false,
      retrievalVideoAnchorCount: 0,
      doneReceived: false,
      doneFallback: false,
      citationCount: 0,
      videoSegmentCitationCount: 0,
    }
    if (!located.resource || !observations.sessionAuthOk || !observations.agentKbMatch || !observations.conversationBound || observations.uploadTerminalCount < 1 || !observations.retrievalReady) {
      fail(recordCitationDiagnosis('session_auth_mismatch', observations))
    }
    await installSseSummary(page)
    currentStage = `${prefix}-retrieval`
    const retrieval = await queryAgentSse(page, located.resource.agentId, located.resource.threadId, true)
    if (!retrieval.httpOk || !retrieval.summary.doneReceived || !retrieval.summary.doneThreadMatchesTarget) {
      fail(recordCitationDiagnosis(retrieval.httpOk ? 'no_sse_done' : 'session_auth_mismatch', observations))
    }
    observations.retrievalContextPresent = retrieval.summary.retrievalContextPresent
    observations.retrievalVideoAnchorCount = retrieval.summary.retrievalVideoAnchorCount
    currentStage = `${prefix}-prewarm`
    const prewarm = await queryAgentSse(page, located.resource.agentId, located.resource.threadId)
    Object.assign(observations, prewarm.summary)
    if (!prewarm.httpOk || !observations.doneReceived || !observations.doneThreadMatchesTarget) {
      fail(recordCitationDiagnosis(prewarm.httpOk ? 'no_sse_done' : 'session_auth_mismatch', observations))
    }
    if (!observations.citationCount) fail(recordCitationDiagnosis('done_without_citations', observations))
    if (!observations.videoSegmentCitationCount) fail(recordCitationDiagnosis('citations_without_video_segments', observations))
    const playback = await verifyCitationRenderAndPlayback(
      page,
      located.resource.agentId,
      located.resource.threadId,
      located.resource.threadTitle,
      observations,
      `${prefix}-new-video`,
    )
    apiResourceParity = {
      same_agent: true,
      same_conversation: true,
      same_kb: true,
      upload_terminal_count: boundedCount(observations.uploadTerminalCount),
      retrieval_ready: observations.retrievalReady === true,
      retrieval_context_present: observations.retrievalContextPresent === true,
      retrieval_video_anchor_count: boundedCount(observations.retrievalVideoAnchorCount),
      done_received: observations.doneReceived === true,
      done_fallback: observations.doneFallback === true,
      citation_count: boundedCount(observations.citationCount),
      video_segment_citation_count: boundedCount(observations.videoSegmentCitationCount),
      citation_rendered: playback.adjacent_ranges === true,
      video_playback: playback.video_playback === true,
    }
  } finally {
    await context.close()
  }
}

async function verifyVideoRetrievalAndPlayback(page, kb, prefix = 'browser-api-resource-new-video', sharedObservations = null) {
  stage(prefix, 'retrieval-ready')
  const observations = sharedObservations || {}
  Object.assign(observations, {
    sessionAuthOk: false,
    agentCreated: false,
    agentCreateStatus: 0,
    agentListAccessible: false,
    agentListCount: 0,
    agentKbMatch: false,
    conversationBound: false,
    uploadTerminalCount: 0,
    retrievalReady: false,
    retrievalContextPresent: false,
    retrievalVideoAnchorCount: 0,
    retrievalThreadContextPresent: false,
    retrievalThreadVideoAnchorCount: 0,
    retrievalUnthreadedContextPresent: false,
    retrievalUnthreadedVideoAnchorCount: 0,
    doneReceived: false,
    doneFallback: false,
    citationCount: 0,
    videoSegmentCitationCount: 0,
  })
  const session = await page.evaluate(async kbName => {
    const saved = JSON.parse(localStorage.getItem('raganything_auth') || 'null')
    const headers = { Authorization: `Bearer ${saved?.token || ''}` }
    const [identity, tasks] = await Promise.all([
      fetch('/api/auth/me', { headers }),
      fetch(`/api/upload/tasks?kb=${encodeURIComponent(kbName)}`, { headers }),
    ])
    const taskBody = await tasks.json().catch(() => ({}))
    const terminal = Array.isArray(taskBody?.tasks)
      ? taskBody.tasks.filter(task => ['processed', 'completed'].includes(task?.status)).length
      : 0
    return { authOk: identity.ok, uploadTerminalCount: terminal }
  }, kb)
  observations.sessionAuthOk = session.authOk === true
  observations.uploadTerminalCount = boundedCount(session.uploadTerminalCount)
  if (!observations.sessionAuthOk) {
    fail(recordCitationDiagnosis('session_auth_mismatch', observations))
  }
  const retrievalReady = await page.waitForFunction(async kbName => {
    const saved = JSON.parse(localStorage.getItem('raganything_auth') || 'null')
    const response = await fetch(`/api/knowledge/retrieval-health?kb=${encodeURIComponent(kbName)}`, {
      headers: { Authorization: `Bearer ${saved?.token || ''}` },
    })
    const body = await response.json().catch(() => ({}))
    return response.ok && Array.isArray(body?.documents) && body.documents.length === 0
  }, kb, { timeout: 60_000, polling: 1_000 }).then(() => true).catch(() => false)
  observations.retrievalReady = retrievalReady
  if (!retrievalReady) fail('browser-video-retrieval-not-ready')
  stage(prefix, 'agent-create')
  const agent = await createAgent(page, kb)
  observations.agentCreateStatus = boundedCount(agent.status)
  observations.agentCreated = Boolean(agent.id)
  const binding = agent.id
    ? await verifyAgentBinding(page, agent.id, kb)
    : { accessible: false, count: 0, matches: false }
  observations.agentListAccessible = binding.accessible === true
  observations.agentListCount = boundedCount(binding.count)
  observations.agentKbMatch = binding.matches === true
  if (!agent.id || !observations.agentKbMatch) fail(recordCitationDiagnosis('session_auth_mismatch', observations))
  const conversationTitle = `${prefix}-thread`
  const conversationId = await createConversation(page, agent.id, conversationTitle)
  observations.conversationBound = Boolean(conversationId)
  if (!conversationId) fail(recordCitationDiagnosis('session_auth_mismatch', observations))
  await installSseSummary(page)
  stage(prefix, 'retrieval-probe')
  const retrievalProbe = await queryAgentSse(page, agent.id, conversationId, true)
    if (!retrievalProbe.httpOk || !retrievalProbe.summary.doneReceived || !retrievalProbe.summary.doneThreadMatchesTarget) {
    fail(recordCitationDiagnosis(retrievalProbe.httpOk ? 'no_sse_done' : 'session_auth_mismatch', observations))
  }
  observations.retrievalThreadContextPresent = retrievalProbe.summary.retrievalContextPresent
  observations.retrievalThreadVideoAnchorCount = retrievalProbe.summary.retrievalVideoAnchorCount
  stage(prefix, 'retrieval-unthreaded-probe')
  const unthreadedRetrievalProbe = await queryAgentSse(page, agent.id, '', true)
  if (!unthreadedRetrievalProbe.httpOk || !unthreadedRetrievalProbe.summary.doneReceived) {
    fail(recordCitationDiagnosis(unthreadedRetrievalProbe.httpOk ? 'no_sse_done' : 'session_auth_mismatch', observations))
  }
  observations.retrievalUnthreadedContextPresent = unthreadedRetrievalProbe.summary.retrievalContextPresent
  observations.retrievalUnthreadedVideoAnchorCount = unthreadedRetrievalProbe.summary.retrievalVideoAnchorCount
  observations.retrievalContextPresent = observations.retrievalThreadContextPresent
  observations.retrievalVideoAnchorCount = observations.retrievalThreadVideoAnchorCount
  stage(prefix, 'api-prewarm')
  const prewarm = await queryAgentSse(page, agent.id, conversationId)
  Object.assign(observations, prewarm.summary)
    if (!prewarm.httpOk || !observations.doneReceived || !observations.doneThreadMatchesTarget) {
    fail(recordCitationDiagnosis(prewarm.httpOk ? 'no_sse_done' : 'session_auth_mismatch', observations))
  }
  if (!observations.citationCount) fail(recordCitationDiagnosis('done_without_citations', observations))
  if (!observations.videoSegmentCitationCount) fail(recordCitationDiagnosis('citations_without_video_segments', observations))
  return verifyCitationRenderAndPlayback(page, agent.id, conversationId, conversationTitle, observations, prefix)
}

async function verifyNonVideoCompatibilityUi(page, agentId, fixtureNames, prefix) {
  stage(prefix, 'nonvideo-thread-create')
  const threadTitle = `${prefix}-thread`
  const threadId = await createConversation(page, agentId, threadTitle)
  if (!threadId) fail('browser-nonvideo-thread-create')
  const diagnostics = installPageDiagnostics(page)
  diagnostics.expectThread(agentId, threadId)
  const detailWait = diagnostics.waitForDetail(diagnostics.detailCount())
  stage(prefix, 'nonvideo-agent-navigation')
  await page.goto(`${base}/agents/${encodeURIComponent(agentId)}?thread=${encodeURIComponent(threadId)}`, { waitUntil: 'domcontentloaded', timeout: 30_000 })
  await detailWait
  const conversation = navigationConversationLocator(page)
  await conversation.waitFor({ state: 'visible', timeout: 30_000 })
  if (!await navigationActiveThreadMatches(page, threadTitle)) fail('browser-nonvideo-active-thread')
  const existingQueryIds = await conversation.locator('[data-testid="assistant-message"][data-message-query-id]').evaluateAll(nodes => (
    nodes.map(node => node.getAttribute('data-message-query-id')).filter(Boolean)
  ))
  stage(prefix, 'nonvideo-query')
  await conversation.locator('textarea').first().fill(`兼容文件包含什么内容？${fixtureNames.join(' ')}`)
  await conversation.locator('textarea').first().press('Enter')
  const targetQueryId = await page.waitForFunction(previousQueryIds => {
    const root = document.querySelector('.agent-chat-main')
    const assistant = [...(root?.querySelectorAll('[data-testid="assistant-message"]') || [])].find(node => {
      const queryId = node.getAttribute('data-message-query-id')
      return queryId && !previousQueryIds.includes(queryId) && node.querySelector('[data-testid="citation-block"]')
    })
    return assistant?.getAttribute('data-message-query-id') || null
  }, existingQueryIds, { timeout: 90_000 }).then(handle => handle.jsonValue())
  if (!targetQueryId) fail('query_not_started')
  const targetAssistant = conversation.locator(`[data-testid="assistant-message"][data-message-query-id="${targetQueryId}"]`)
  const renderedCitation = targetAssistant.getByTestId('citation-block')
  await renderedCitation.waitFor({ state: 'visible', timeout: 90_000 })
  const streamingCitationState = await page.waitForFunction(queryId => {
    const assistant = document.querySelector(`[data-testid="assistant-message"][data-message-query-id="${queryId}"]`)
    return assistant?.getAttribute('data-message-state') === 'streaming'
      && Boolean(assistant.querySelector('[data-testid="citation-block"]'))
  }, targetQueryId, { timeout: 30_000 }).then(() => true).catch(() => false)
  if (!streamingCitationState) fail('stream_citation_state_missing')
  const rendered = await page.evaluate(({ expectedThreadTitle, queryId }) => {
    const root = document.querySelector('.agent-chat-main')
    const sidebar = document.querySelector('.agent-chat-sidebar')
    const assistants = [...(root?.querySelectorAll('[data-testid="assistant-message"]') || [])]
    const assistant = assistants.find(node => node.getAttribute('data-message-query-id') === queryId)
    const style = assistant ? window.getComputedStyle(assistant) : null
    return {
      active_thread_match: [...(sidebar?.querySelectorAll('[role="button"][aria-current="true"]') || [])]
        .some(node => node.getAttribute('aria-label') === `对话: ${expectedThreadTitle}`),
      assistant_message_id: assistant?.getAttribute('data-message-id') || '',
      citation_count: assistant?.querySelectorAll('[data-testid="citation-block"]').length || 0,
      player_count: assistant?.querySelectorAll('[data-testid="video-segment-player"]').length || 0,
      range_label_count: [...(assistant?.querySelectorAll('button') || [])].filter(button => /\d+:\d{2}\s*-\s*\d+:\d{2}/.test(String(button.textContent || ''))).length,
      visible: Boolean(style && style.display !== 'none' && style.visibility === 'visible' && style.opacity !== '0'),
    }
  }, { expectedThreadTitle: threadTitle, queryId: targetQueryId })
  if (!rendered.active_thread_match || !rendered.assistant_message_id || !rendered.visible || !rendered.citation_count) fail('locator_binding_mismatch')
  if (rendered.player_count || rendered.range_label_count) fail('nonvideo_player_leak')
  stage(prefix, 'nonvideo-reload')
  const reloadDetailCount = diagnostics.detailCount()
  const reloadDetailWait = diagnostics.waitForDetail(reloadDetailCount)
  await page.reload({ waitUntil: 'domcontentloaded', timeout: 30_000 })
  await reloadDetailWait
  await page.locator(`[data-testid="assistant-message"][data-message-query-id="${targetQueryId}"]`).waitFor({ state: 'visible', timeout: 30_000 })
  const persisted = await inspectPersistedConversation(page, agentId, threadId, targetQueryId)
  diagnostics.clearExpectedThread()
  const errors = diagnostics.errors()
  diagnostics.dispose()
  const citedNames = new Set(persisted.documentNames.map(name => name.toLowerCase()))
  if (!persisted.conversationGetOk || !persisted.lastAssistantPresent || !persisted.persistedCitationCount || persisted.persistedVideoSegmentCount || !fixtureNames.every(name => citedNames.has(name.toLowerCase()))) fail('persisted_refresh_overwrite')
  if (Object.values(errors).some(value => value !== 0)) fail('browser-nonvideo-client-errors')
  return {
    query_id: targetQueryId,
    query_started: true,
    stream_completed: true,
    stream_citation_state_present: streamingCitationState,
    persisted_refresh_preserved: true,
    locator_binding_matches: true,
    player_rendered: false,
    legacy_contract_ok: true,
    nonvideo_player_absent: true,
    citation_count: rendered.citation_count,
    video_segment_count: 0,
    player_count: rendered.player_count,
    range_label_count: rendered.range_label_count,
    fixture_citations: fixtureNames,
    page_detail_get: diagnostics.detail(),
    errors,
  }
}

async function verifyLegacyVideoUi(page, resource, prefix) {
  stage(prefix, 'legacy-video-contract')
  const diagnostics = installPageDiagnostics(page)
  const legacy = await page.evaluate(async ({ kbName, taskId }) => {
    const saved = JSON.parse(localStorage.getItem('raganything_auth') || 'null')
    const response = await fetch(`/api/upload/tasks?kb=${encodeURIComponent(kbName)}`, {
      headers: { Authorization: `Bearer ${saved?.token || ''}` },
    })
    const body = await response.json().catch(() => ({}))
    const task = (Array.isArray(body?.tasks) ? body.tasks : []).find(item => String(item?.task_id || '') === taskId)
    return {
      ok: response.ok,
      rejected: task?.status === 'failed' && String(task?.error_message || '').includes('video_profile_retired'),
      has_video_segments: Object.hasOwn(task || {}, 'video_segments') || Object.hasOwn(task || {}, 'video_segment'),
    }
  }, { kbName: resource.kb, taskId: resource.task_id })
  stage(prefix, 'legacy-video-task-ui')
  await page.goto(`${base}/knowledge/${encodeURIComponent(resource.kb)}`, { waitUntil: 'domcontentloaded', timeout: 30_000 })
  await page.getByText('legacy-video.mp4', { exact: true }).waitFor({ state: 'visible', timeout: 30_000 })
  stage(prefix, 'legacy-video-agent-thread')
  const threadTitle = `${prefix}-thread`
  const threadId = await createConversation(page, resource.agent_id, threadTitle)
  if (!threadId) fail('browser-legacy-thread-create')
  diagnostics.expectThread(resource.agent_id, threadId)
  const detailWait = diagnostics.waitForDetail(diagnostics.detailCount())
  await page.goto(`${base}/agents/${encodeURIComponent(resource.agent_id)}?thread=${encodeURIComponent(threadId)}`, { waitUntil: 'domcontentloaded', timeout: 30_000 })
  await detailWait
  const conversation = navigationConversationLocator(page)
  await conversation.waitFor({ state: 'visible', timeout: 30_000 })
  if (!await navigationActiveThreadMatches(page, threadTitle)) fail('browser-legacy-active-thread')
  const before = await conversation.locator('[data-testid="assistant-message"][data-message-query-id]').evaluateAll(nodes => nodes.map(node => node.getAttribute('data-message-query-id')).filter(Boolean))
  stage(prefix, 'legacy-video-query')
  await conversation.locator('textarea').first().fill('legacy video rejection fixture')
  await conversation.locator('textarea').first().press('Enter')
  const queryId = await page.waitForFunction(previousQueryIds => {
    const root = document.querySelector('.agent-chat-main')
    const assistant = [...(root?.querySelectorAll('[data-testid="assistant-message"]') || [])].find(node => {
      const candidate = node.getAttribute('data-message-query-id')
      return candidate && !previousQueryIds.includes(candidate) && node.getAttribute('data-message-state') === 'persisted'
    })
    return assistant?.getAttribute('data-message-query-id') || null
  }, before, { timeout: 90_000 }).then(handle => handle.jsonValue())
  const target = conversation.locator(`[data-testid="assistant-message"][data-message-query-id="${queryId}"]`)
  const playerCount = await target.getByTestId('video-segment-player').count()
  const rangeLabelCount = await target.locator('button').filter({ hasText: /\d+:\d{2}\s*-\s*\d+:\d{2}/ }).count()
  stage(prefix, 'legacy-video-reload')
  const reloadDetailCount = diagnostics.detailCount()
  const reloadDetailWait = diagnostics.waitForDetail(reloadDetailCount)
  await page.reload({ waitUntil: 'domcontentloaded', timeout: 30_000 })
  await reloadDetailWait
  await page.locator(`[data-testid="assistant-message"][data-message-query-id="${queryId}"]`).waitFor({ state: 'visible', timeout: 30_000 })
  diagnostics.clearExpectedThread()
  const errors = diagnostics.errors()
  diagnostics.dispose()
  if (!queryId || !legacy.ok || !legacy.rejected || legacy.has_video_segments || playerCount || rangeLabelCount || Object.values(errors).some(value => value !== 0)) fail('legacy_contract_mismatch')
  return {
    legacy_result: 'rejected',
    query_started: true,
    stream_completed: true,
    stream_citation_state_present: true,
    persisted_refresh_preserved: true,
    locator_binding_matches: true,
    player_rendered: false,
    legacy_contract_ok: true,
    nonvideo_player_absent: true,
    citation_count: 0,
    video_segment_count: 0,
    player_count: 0,
    range_label_count: 0,
    errors,
    page_detail_get: diagnostics.detail(),
  }
}

async function verifyRole(page, account, viewport, shared) {
  const prefix = `browser-${viewport}-${account.role}`
  const lifecycleDiagnostics = installPageDiagnostics(page)
  await login(page, account, prefix)
  currentStage = `${prefix}-session`
  await sessionRole(page, account.role)
  currentStage = `${prefix}-knowledge-list`
  await page.goto(`${base}/knowledge`, { waitUntil: 'domcontentloaded', timeout: 30_000 })
  await page.getByRole('heading', { name: '知识库' }).waitFor({ state: 'visible', timeout: 30_000 })
  let sharedKbRead = false
  if (shared.kb) {
    await page.getByText(shared.kb).first().waitFor({ state: 'visible', timeout: 30_000 })
    sharedKbRead = true
  }
  let userManagement = 'denied'
  if (['super_admin', 'dept_admin'].includes(account.role)) {
    currentStage = `${prefix}-user-management`
    await page.goto(`${base}/admin/users`, { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await page.getByText('用户管理').first().waitFor({ state: 'visible', timeout: 30_000 })
    userManagement = 'allowed'
  } else {
    currentStage = `${prefix}-user-denial`
    const usersStatus = await page.evaluate(async () => {
      const saved = JSON.parse(localStorage.getItem('raganything_auth') || 'null')
      const response = await fetch('/api/admin/users', { headers: { Authorization: `Bearer ${saved?.token || ''}` } })
      return response.status
    })
    if (usersStatus !== 403) fail('browser-user-admin-denial')
  }
  currentStage = `${prefix}-write-policy`
  await page.goto(`${base}/knowledge`, { waitUntil: 'domcontentloaded', timeout: 30_000 })
  const canWrite = account.role !== 'student'
  const writeStatus = await page.evaluate(async kbName => {
    const saved = JSON.parse(localStorage.getItem('raganything_auth') || 'null')
    const response = await fetch(`/api/kb/create?kb_name=${encodeURIComponent(kbName)}`, {
      method: 'POST', headers: { Authorization: `Bearer ${saved?.token || ''}` },
    })
    return response.status
  }, `rolewrite${Date.now().toString(36)}`)
  if ((canWrite && writeStatus !== 200) || (!canWrite && writeStatus !== 403)) fail('browser-kb-write-policy')
  if (!canWrite) {
    const buttonVisible = await page.getByRole('button', { name: '新建知识库' }).isVisible().catch(() => false)
    if (buttonVisible) fail('browser-student-write-visible')
  }
  let video = null
  let nonVideo = null
  let legacyVideo = null
  if (account.role === 'super_admin' && viewport === 'desktop') {
    currentStage = `${prefix}-video-upload`
    const upload = await createKnowledgeBaseAndUpload(page, fixture, prefix)
    shared.kb = upload.name
    sharedKbRead = true
    shared.upload_progress = upload.upload_progress
    shared.upload_terminal = upload.upload_terminal
    currentStage = `${prefix}-video-agent-create`
    const agent = await createAgent(page, shared.kb)
    if (!agent.id) fail('browser-shared-agent-create')
    shared.agentId = agent.id
    currentStage = `${prefix}-nonvideo-upload`
    const compatibility = await createCompatibilityKnowledgeBase(page, compatibilityFixtures)
    const compatibilityAgent = await createAgent(page, compatibility.name)
    if (!compatibilityAgent.id) fail('browser-shared-nonvideo-agent-create')
    shared.compatibilityKb = compatibility.name
    shared.compatibilityAgentId = compatibilityAgent.id
    shared.compatibilityFixtures = compatibility.filenames
  }
  if (!shared.kb || !shared.agentId || !shared.compatibilityKb || !shared.compatibilityAgentId || !Array.isArray(shared.compatibilityFixtures) || shared.compatibilityFixtures.length !== 3) fail('browser-shared-resource-missing')
  currentStage = `${prefix}-video-thread-create`
  const threadTitle = `${prefix}-thread`
  const threadId = await createConversation(page, shared.agentId, threadTitle)
  if (!threadId) fail('browser-role-thread-create')
  if (account.role === 'super_admin' && viewport === 'desktop' && !shared.threadNavigationContract) {
    currentStage = `${prefix}-thread-navigation-contract`
    shared.threadNavigationContract = await verifyThreadNavigationContract(page, shared.agentId, threadId, prefix)
  }
  currentStage = `${prefix}-video-retrieval`
  const videoObservations = {
    sessionAuthOk: true,
    agentCreated: Boolean(shared.agentId),
    agentKbMatch: Boolean(shared.kb),
    conversationBound: true,
    uploadTerminalCount: shared.upload_terminal === true ? 1 : 0,
  }
  video = await verifyCitationRenderAndPlayback(page, shared.agentId, threadId, threadTitle, videoObservations, prefix)
  nonVideo = await verifyNonVideoCompatibilityUi(page, shared.compatibilityAgentId, shared.compatibilityFixtures, prefix)
  legacyVideo = await verifyLegacyVideoUi(page, shared.legacyResource, prefix)
  currentStage = `${prefix}-logout`
  await logout(page, account.username)
  const logoutDenied = await page.evaluate(async mediaPath => {
    const apiReply = await fetch('/api/kb/list')
    const normal = mediaPath ? await fetch(mediaPath) : null
    const ranged = mediaPath ? await fetch(mediaPath, { headers: { Range: 'bytes=0-1' } }) : null
    return { api: apiReply.status, media: normal?.status || 0, media_range: ranged?.status || 0 }
  }, video.media_path)
  if (![401, 403].includes(logoutDenied.api) || ![401, 403].includes(logoutDenied.media) || ![401, 403].includes(logoutDenied.media_range)) fail('browser-logout-media-denial')
  const lifecycleErrors = lifecycleDiagnostics.errors()
  lifecycleDiagnostics.dispose()
  if (Object.values(lifecycleErrors).some(value => value !== 0)) fail('browser-client-errors')
  const common = {
    role: account.role,
    viewport,
    session_restore: true,
    logout: true,
    shared_kb_read: sharedKbRead,
    user_management: userManagement,
    kb_write: canWrite ? 'allowed' : 'denied',
    upload: account.role === 'super_admin' && viewport === 'desktop',
    upload_progress: account.role === 'super_admin' && viewport === 'desktop' ? shared.upload_progress === true : false,
    upload_terminal: account.role === 'super_admin' && viewport === 'desktop' ? shared.upload_terminal === true : false,
  }
  return {
    new_video: matrixObservation({ role: account.role, viewport, path: 'new_video', fields: {
      ...common,
      video_retrieval: video.adjacent_ranges && video.video_playback,
      adjacent_ranges: video.adjacent_ranges,
      video_playback: video.video_playback,
      expected_active_thread_match: video.expected_active_thread_match,
      page_detail_get: video.page_detail_get,
      assistant: video.assistant,
      citation: video.citation,
      player: video.player,
      seek: video.seek,
      ranges: video.ranges,
      logout_denied: logoutDenied,
       errors: lifecycleErrors,
      query_started: video.query_started,
      stream_completed: video.stream_completed,
      stream_citation_state_present: video.stream_citation_state_present,
      persisted_refresh_preserved: video.persisted_refresh_preserved,
      locator_binding_matches: video.locator_binding_matches,
      player_rendered: video.player_rendered,
      citation_count: video.citation_count,
      video_segment_count: video.video_segment_count,
      player_count: video.player_count,
       range_label_count: video.range_label_count,
       authorized_media: video.authorized_media,
    } }),
    nonvideo: matrixObservation({ role: account.role, viewport, path: 'nonvideo', fields: {
      ...common,
      video_retrieval: false,
      player_rendered: false,
      page_detail_get: nonVideo.page_detail_get,
       errors: lifecycleErrors,
      query_started: nonVideo.query_started,
      stream_completed: nonVideo.stream_completed,
      stream_citation_state_present: nonVideo.stream_citation_state_present,
      persisted_refresh_preserved: nonVideo.persisted_refresh_preserved,
      locator_binding_matches: nonVideo.locator_binding_matches,
      player_rendered: nonVideo.player_rendered,
      legacy_contract_ok: nonVideo.legacy_contract_ok,
      nonvideo_player_absent: nonVideo.nonvideo_player_absent,
      citation_count: nonVideo.citation_count,
      video_segment_count: nonVideo.video_segment_count,
      player_count: nonVideo.player_count,
       range_label_count: nonVideo.range_label_count,
       fixture_citations: nonVideo.fixture_citations,
    } }),
    legacy_video: matrixObservation({ role: account.role, viewport, path: 'legacy_video', fields: {
      ...common,
      video_retrieval: false,
      ...legacyVideo,
      errors: lifecycleErrors,
    } }),
    _media_path: video.media_path,
  }
}

async function main() {
  if (setupNavigationOnlyMode()) {
    await runSetupNavigationOnly()
    return
  }
  if (navigationOnlyMode()) {
    await runNavigationOnly()
    return
  }
  if (citationOnlyMode()) {
    await runCitationOnly()
    return
  }
  if (phaseAMode()) {
    phaseAEvidence = createPhaseAEvidence()
    setupNavigationObservation = createSetupNavigationObservation()
    phaseAEvidence.setup_navigation = setupNavigationObservation
    updateCurrentStage('browser-phase-a-setup-input')
  } else {
    updateCurrentStage('browser-desktop-super_admin-bootstrap-input')
  }
  if (!base || !accountsPath || !evidencePath || !fixture || !fs.existsSync(fixture)
    || (!phaseAMode() && !uploadDiagnosisMode && (!legacyResourcePath || !fs.existsSync(legacyResourcePath) || compatibilityFixtures.length !== 3 || compatibilityFixtures.some(path => !fs.existsSync(path))))) fail('browser-input')
  const accounts = JSON.parse(fs.readFileSync(accountsPath, 'utf8'))
  let legacyResource = null
  if (!phaseAMode() && !uploadDiagnosisMode) {
    legacyResource = JSON.parse(fs.readFileSync(legacyResourcePath, 'utf8'))
    updateCurrentStage('browser-desktop-super_admin-bootstrap-legacy-resource')
    if (!legacyResource?.kb || !legacyResource?.agent_id || !legacyResource?.task_id) fail('browser-legacy-resource')
    updateCurrentStage('browser-desktop-super_admin-bootstrap-login')
    const bootstrap = await api('/api/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: accounts.admin.username, password: accounts.admin.password }),
    })
    if (bootstrap.status !== 200 || !bootstrap.body.access_token) fail('browser-bootstrap-login')
    const auth = { Authorization: `Bearer ${bootstrap.body.access_token}`, 'Content-Type': 'application/json' }
    const roleReply = await api('/api/admin/roles', { headers: auth })
    const roleIds = new Map((roleReply.body.roles || []).map(role => [role.name, role.id]))
    for (const account of accounts.roles) {
      const reply = await api('/api/admin/users', {
        method: 'POST', headers: auth,
        body: JSON.stringify({ username: account.username, password: account.initial_password, role_id: roleIds.get(account.role) }),
      })
      updateCurrentStage(`browser-desktop-super_admin-bootstrap-role-${account.role}`)
      if (reply.status !== 201) fail('browser-role-bootstrap')
    }
  }
  if (uploadDiagnosisMode) {
    const browser = await chromium.launch({ headless: true, executablePath: chromiumExecutablePath() })
    const context = await browser.newContext({ viewport: viewports.desktop })
    const page = await context.newPage()
    try {
      if (!base || !accountsPath || !evidencePath || !fixture || !fs.existsSync(fixture)) fail('browser-input')
      const accounts = JSON.parse(fs.readFileSync(accountsPath, 'utf8'))
      await runUploadDiagnosis(page, { ...accounts.admin, role: 'super_admin' })
    } finally {
      await context.close()
      await browser.close()
    }
    return
  }
  if (phaseAMode()) updateCurrentStage('browser-phase-a-browser-launch')
  const browser = await chromium.launch({ headless: true, executablePath: chromiumExecutablePath() })
  const shared = { kb: '', legacyResource }
  const matrices = { new_video: [], nonvideo: [], legacy_video: [] }
  let controlledMediaPath = ''
  let phaseAPage = null
  let disposePhaseAObservation = () => {}
  try {
    const phaseA = phaseAMode()
    const apiResourceParity = phaseA ? null : await verifyApiResourceParity(browser, accounts.admin)
    if (phaseA) {
      const account = { ...accounts.admin, role: 'super_admin' }
      updateCurrentStage('browser-phase-a-context-create')
      const context = await browser.newContext({ viewport: viewports.desktop })
      updateCurrentStage('browser-phase-a-page-create')
      const page = await context.newPage()
      phaseAPage = page
      disposePhaseAObservation = installSetupNavigationObservability(page, setupNavigationObservation)
      updateCurrentStage('browser-phase-a-setup-login')
      const outcome = await runPhaseARepresentative(page, account)
      setupNavigationObservation.final_location = safeLocation(page.url())
      phaseAEvidence.current_stage = currentStage
      await context.close()
      writeEvidence({
        schema_version: 4,
        browser: 'playwright',
        phase_a_representative: true,
        complete_browser_evidence: false,
        representative_path: 'super_admin_desktop_new_video',
        runtime_status: 'passed',
        failure_class: null,
        timeout_stage: '',
        phase_a: phaseAEvidence || createPhaseAEvidence(),
        matrix: outcome.new_video,
      })
      return
    }
    for (const [viewport, options] of Object.entries(viewports)) {
      for (const account of accounts.roles) {
        currentStage = `browser-${viewport}-${account.role}-start`
        const context = await browser.newContext({ viewport: options, isMobile: Boolean(options.isMobile) })
        const page = await context.newPage()
        const outcome = await verifyRole(page, account, viewport, shared)
        controlledMediaPath = controlledMediaPath || outcome._media_path
        matrices.new_video.push(outcome.new_video)
        matrices.nonvideo.push(outcome.nonvideo)
        matrices.legacy_video.push(outcome.legacy_video)
        await context.close()
      }
    }
    currentStage = 'browser-desktop-anonymous-media'
    if (!controlledMediaPath || !controlledMediaPath.startsWith('/api/knowledge/media/')) fail('browser-controlled-media-path')
    const anonymousContext = await browser.newContext({ viewport: viewports.desktop })
    const anonymousPage = await anonymousContext.newPage()
    await anonymousPage.goto(`${base}/login`, { waitUntil: 'domcontentloaded', timeout: 30_000 })
    const anonymous = await anonymousPage.evaluate(async mediaPath => {
      const [apiReply, normal, ranged] = await Promise.all([
        fetch('/api/kb/list'),
        fetch(mediaPath),
        fetch(mediaPath, { headers: { Range: 'bytes=0-1' } }),
      ])
      return { api: apiReply.status, media: normal.status, media_range: ranged.status }
    }, controlledMediaPath)
    await anonymousContext.close()
    if (![401, 403].includes(anonymous.api) || ![401, 403].includes(anonymous.media) || ![401, 403].includes(anonymous.media_range)) fail('browser-anonymous-media-denial')
    const clientErrorCounts = Object.values(matrices).flat().reduce((total, item) => ({
      console: total.console + item.errors.console,
      page: total.page + item.errors.page,
      expected_detail_request: total.expected_detail_request + item.errors.expected_detail_request,
      non_expected_request: total.non_expected_request + item.errors.non_expected_request,
      aborted: total.aborted + item.errors.aborted,
    }), { console: 0, page: 0, expected_detail_request: 0, non_expected_request: 0, aborted: 0 })
    writeEvidence({
      schema_version: 2,
      browser: 'playwright',
      complete_browser_evidence: true,
      api_resource_parity: apiResourceParity,
      thread_navigation_contract: shared.threadNavigationContract,
      matrices,
      anonymous: { kb: anonymous.api, media: anonymous.media, media_range: anonymous.media_range },
      client_error_counts: clientErrorCounts,
    })
  } catch (error) {
    const explicit = String(error?.code || '')
    const kind = error?.name === 'TimeoutError' ? 'timeout' : 'automation'
    const failureClass = explicit || `browser-${currentStage}-${kind}`
    const errorKind = String(error?.name || 'Error').toLowerCase().replace(/[^a-z0-9_-]/g, '').slice(0, 24) || 'error'
    const phaseA = phaseAEvidence || createPhaseAEvidence()
    if (phaseAMode()) {
      phaseA.failure_class = phaseAFailureClass(error) || phaseA.failure_class || 'navigation'
      if (phaseA.failure_class && phaseA.observations?.request_failure?.stage === 'not_reached') {
        phaseA.observations.request_failure = { stage: 'upload_progress', path: '', reason_class: phaseA.failure_class }
      }
      if (error?.name === 'TimeoutError' && !phaseA.timeout_stage) phaseA.timeout_stage = phaseA.failure_class
      phaseA.status = 'run_failed'
      phaseA.current_stage = currentStage
      if (setupNavigationObservation) {
        setupNavigationObservation.current_stage = currentStage
        setupNavigationObservation.automation_error = shortAutomationError(error)
        if (phaseAPage) {
          setupNavigationObservation.final_location = safeLocation(phaseAPage.url())
          await captureSetupNavigationFailure(phaseAPage, { runRoot: path.dirname(evidencePath) }, setupNavigationObservation)
        }
        phaseA.setup_navigation = setupNavigationObservation
      }
    }
    writeEvidence({
      schema_version: 4,
      browser: 'playwright',
      phase_a_representative: phaseAMode(),
      complete_browser_evidence: false,
      runtime_status: 'run_failed',
      failure_class: phaseAMode() ? phaseA.failure_class : failureClass.replace(/[^a-z0-9_-]/gi, '').slice(0, 80) || 'browser-uat-failed',
      timeout_stage: phaseAMode() ? phaseA.timeout_stage : '',
      automation_error_kind: errorKind,
      ...(phaseAMode() ? { representative_path: 'super_admin_desktop_new_video', phase_a: phaseA } : {}),
    })
    process.exitCode = 1
  } finally {
    disposePhaseAObservation()
    await browser.close()
  }
}

process.once('uncaughtException', () => {
  writeCitationOnlyFallback('citation_probe_automation')
  process.exitCode = 1
})

process.once('unhandledRejection', () => {
  writeCitationOnlyFallback('citation_probe_automation')
  process.exitCode = 1
})

main().catch(error => {
  if (phaseAMode()) {
    const phaseA = phaseAEvidence || createPhaseAEvidence()
    phaseA.status = 'run_failed'
    phaseA.failure_class = phaseAFailureClass(error) || phaseA.failure_class || 'navigation'
    if (phaseA.failure_class && phaseA.observations?.request_failure?.stage === 'not_reached') {
      phaseA.observations.request_failure = { stage: 'upload_progress', path: '', reason_class: phaseA.failure_class }
    }
    if (error?.name === 'TimeoutError' && !phaseA.timeout_stage) phaseA.timeout_stage = phaseA.failure_class
    phaseA.current_stage = currentStage
    const observation = setupNavigationObservation || createSetupNavigationObservation()
    observation.current_stage = currentStage
    observation.automation_error = shortAutomationError(error)
    phaseA.setup_navigation = observation
    writeEvidence({
      schema_version: 4,
      browser: 'playwright',
      phase_a_representative: true,
      complete_browser_evidence: false,
      runtime_status: 'run_failed',
      failure_class: phaseA.failure_class,
      timeout_stage: phaseA.timeout_stage,
      automation_error_kind: String(error?.name || 'Error').toLowerCase().replace(/[^a-z0-9_-]/g, '').slice(0, 24) || 'error',
      representative_path: 'super_admin_desktop_new_video',
      phase_a: phaseA,
    })
    process.exitCode = 1
    return
  }
  if (navigationOnlyMode()) {
    writeEvidence({
      schema_version: 2,
      browser_navigation_only: true,
      runtime_status: 'run_failed',
      failure_class: 'unknown',
      old_run_evidence_used_as_result: false,
      probe_process_created_docker_resources: 0,
    })
    process.exitCode = 1
    return
  }
  if (citationOnlyMode()) {
    writeCitationOnlyFallback(error?.name === 'TimeoutError' ? 'citation_probe_timeout' : 'citation_probe_automation')
    process.exitCode = 1
    return
  }
  const kind = error?.name === 'TimeoutError' ? 'timeout' : 'automation'
  writeEvidence({
    schema_version: 1,
    failure_class: `browser-bootstrap-${kind}`,
  })
  process.exitCode = 1
})
