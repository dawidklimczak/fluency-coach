export interface ReadingToken {
  text: string;
  newline_before: boolean;
  start: number | null;
  end: number | null;
  status: "spoken" | "unclear" | "missed";
  wpm?: number | null;
  heard?: string | null;
}

export interface ReadingMetrics {
  target_wpm: number;
  wpm: number | null;
  wpm_articulation: number | null;
  wpm_vs_target: number | null;
  steadiness: number | null;
  fastest_wpm: number | null;
  slowest_wpm: number | null;
  reference_words: number;
  words_read: number;
  spoken_count: number;
  unclear_count: number;
  missed_count: number;
  extra_count: number;
  accuracy: number | null;
  duration_s: number;
  phonation_s: number;
  phonation_ratio: number | null;
  pause_count: number;
  longest_pauses: { before: string; duration: number }[];
  transcript_missing: boolean;
}

export interface ReadingResult {
  reading_id: number;
  status: "processing" | "done" | "error";
  target_wpm: number;
  metrics: ReadingMetrics | null;
  words: ReadingToken[] | null;
  transcript: string | null;
}

export interface AuthState {
  password_required: boolean;
  authenticated: boolean;
  local: boolean;
}

export interface InstanceSettings {
  openai_key_set: boolean;
  openai_key_hint: string | null;
  openai_key_from_env: boolean;
  password_set: boolean;
  llm_model: string;
}

export interface Domain {
  id: number;
  name: string;
  status: "active" | "done";
  session_count: number;
  target_sessions: number;
  started_at: string;
}

export interface RoundPlan {
  number: number;
  support_level: number;
  prep_s: number;
  speak_limit_s: number;
}

export interface ChunkDto {
  id: number;
  bank: "domain" | "function";
  text: string;
  prompt_pl: string;
  category: string | null;
}

export type TransferProbeType = "near" | "far";

export interface SessionPack {
  session_id: number;
  domain: string;
  support_ceiling: number;
  writing_phase_active: boolean;
  embed_mode_unlocked: boolean;
  seed_text: string;
  guiding_questions: string[];
  keywords: string[];
  transfer_prompt: string;
  keyword_planning_seconds: number;
  near_transfer_prompt: string;
  far_transfer_prompt: string | null;
  transfer_order: TransferProbeType[];
  rounds: RoundPlan[];
  bank_a_chunks: ChunkDto[];
  bank_b_chunks: ChunkDto[];
  interrupted_reason: string | null;
}

export interface AttemptStatus {
  attempt_id: number;
  status: "processing" | "done" | "error";
  transcript: string | null;
  metrics: Record<string, number | string | null> | null;
}

export interface MetricDelta {
  value: number | null;
  baseline: number | null;
}

export interface ProbeSummary {
  outcome_note: string | null;
  deltas: Record<string, MetricDelta>;
}

export interface SessionSummary {
  session_id: number;
  ended_reason: string;
  support_ceiling: number;
  support_changed: "up" | "down" | null;
  near: ProbeSummary;
  far: ProbeSummary;
}

// --- Bottleneck Diagnostic (spec zmian §2) ---------------------------------

export type DiagnosticCondition = "cold" | "supplied_ideas" | "self_plan" | "repetition" | "native_control";

export interface DiagnosticTrial {
  id: number;
  condition: DiagnosticCondition;
  prompt: string;
  support_json: { ideas?: string[]; items?: string[] } | null;
  planning_seconds: number;
  speaking_limit_seconds: number;
  source_trial_id: number | null;
  order_in_session: number;
}

export interface DiagnosticSessionDto {
  session_id: number;
  status: "in_progress" | "completed";
  language_control_enabled: boolean;
  trials: DiagnosticTrial[];
  note: string[] | null;
}

export interface BottleneckProfile {
  content_generation_sensitivity: string;
  planning_benefit: string;
  repetition_benefit: string;
  l2_specific_cost: string;
  sustained_speech_cost: string;
  disclaimer: string;
}

// --- Recovery Drill (spec zmian §8) ----------------------------------------

export type RecoveryKind = "lost_thread" | "reformulation";

export interface RecoveryStaticTrial {
  kind: RecoveryKind;
  prompt: string;
  suggested_chunk: string | null;
  speaking_limit_seconds: number;
}

/** Rzucane przy 401 - App pokazuje wtedy ekran logowania zamiast błędu. */
export class UnauthorizedError extends Error {
  constructor() {
    super("Wymagane zalogowanie");
  }
}

async function json<T>(res: Response): Promise<T> {
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json();
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return typeof body.detail === "string" ? body.detail : JSON.stringify(body);
  } catch {
    return `HTTP ${res.status}`;
  }
}

async function postJson<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok && res.status !== 401) throw new Error(await errorMessage(res));
  return json<T>(res);
}

function uploadAttempt<T>(url: string, wav: Blob, meta: Record<string, unknown>): Promise<T> {
  const fd = new FormData();
  fd.append("audio", wav, "attempt.wav");
  fd.append("payload", JSON.stringify(meta));
  return fetch(url, { method: "POST", body: fd }).then((r) => json<T>(r));
}

export const api = {
  health: () =>
    fetch("/api/health").then((r) =>
      json<{ ok: boolean; vad_model: boolean; transcription: boolean }>(r)
    ),

  authState: () => fetch("/api/auth/state").then((r) => json<AuthState>(r)),

  login: async (password: string) => {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (res.status === 401) return { ok: false as const, error: "Nieprawidłowe hasło" };
    if (!res.ok) return { ok: false as const, error: await errorMessage(res) };
    return { ok: true as const };
  },

  logout: () => fetch("/api/auth/logout", { method: "POST" }).then((r) => json<{ ok: boolean }>(r)),

  settings: () => fetch("/api/settings").then((r) => json<InstanceSettings>(r)),

  setOpenAiKey: async (apiKey: string) => {
    const res = await fetch("/api/settings/openai-key", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: apiKey }),
    });
    if (!res.ok) throw new Error(await errorMessage(res));
    return res.json();
  },

  setPassword: async (newPassword: string, currentPassword: string | null) => {
    const res = await fetch("/api/settings/password", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        new_password: newPassword,
        current_password: currentPassword,
      }),
    });
    if (!res.ok) throw new Error(await errorMessage(res));
    return res.json();
  },

  calibrationStatus: () =>
    fetch("/api/calibrate/status").then((r) =>
      json<{ calibrated: boolean; noise_floor_db: number | null; vad_threshold: number }>(r)
    ),

  calibrate: (wav: Blob) => {
    const fd = new FormData();
    fd.append("audio", wav, "calibration.wav");
    return fetch("/api/calibrate", { method: "POST", body: fd }).then((r) =>
      json<{ noise_floor_db: number; vad_threshold: number }>(r)
    );
  },

  // --- profil: kontekst osobisty i domeny --------------------------------

  getPersonalContext: () =>
    fetch("/api/profile/personal-context").then((r) => json<{ content: string; version: number }>(r)),

  setPersonalContext: (content: string) =>
    postJson<{ content: string; version: number }>("/api/profile/personal-context", { content }),

  listDomains: () => fetch("/api/profile/domains").then((r) => json<Domain[]>(r)),

  suggestDomains: () => fetch("/api/profile/domains/suggestions").then((r) => json<string[]>(r)),

  createDomain: (name: string, targetSessions = 5) =>
    postJson<{ id: number; name: string }>("/api/profile/domains", {
      name,
      target_sessions: targetSessions,
    }),

  finishDomain: (id: number) => postJson<{ ok: boolean }>(`/api/profile/domains/${id}/finish`, {}),

  reactivateDomain: (id: number) =>
    postJson<{ ok: boolean }>(`/api/profile/domains/${id}/reactivate`, {}),

  // --- sesja mówienia ------------------------------------------------------

  startSession: () => postJson<SessionPack>("/api/speaking-sessions/start", {}),

  getSession: (id: number) => fetch(`/api/speaking-sessions/${id}`).then((r) => json<SessionPack>(r)),

  sessionStatus: (id: number) =>
    fetch(`/api/speaking-sessions/${id}/status`).then((r) =>
      json<{ interrupted: boolean; interrupted_reason: string | null }>(r)
    ),

  submitWritingRehearsal: (sessionId: number, text: string, durationS: number) =>
    postJson<{ ok: boolean; word_count: number }>(
      `/api/speaking-sessions/${sessionId}/writing-rehearsal`,
      { text, duration_s: durationS }
    ),

  submitKeywordPlan: (sessionId: number, items: string[]) =>
    postJson<{ ok: boolean; items: string[] }>(
      `/api/speaking-sessions/${sessionId}/keyword-plan`,
      { items }
    ),

  submitRoundAttempt: (sessionId: number, roundNumber: number, wav: Blob, t0OffsetSamples: number) =>
    uploadAttempt<{ attempt_id: number }>(
      `/api/speaking-sessions/${sessionId}/rounds/${roundNumber}/attempts`,
      wav,
      { t0_offset_samples: t0OffsetSamples }
    ),

  submitTransferProbe: (
    sessionId: number,
    probeType: TransferProbeType,
    wav: Blob,
    t0OffsetSamples: number
  ) =>
    uploadAttempt<{ attempt_id: number; probe_id: number }>(
      `/api/speaking-sessions/${sessionId}/transfer-probe/${probeType}`,
      wav,
      { t0_offset_samples: t0OffsetSamples }
    ),

  getAttempt: (attemptId: number) =>
    fetch(`/api/speaking-sessions/attempts/${attemptId}`).then((r) => json<AttemptStatus>(r)),

  chunkAccessExposure: (sessionId: number, chunkId: number, rtMs: number) =>
    postJson<{ ok: boolean }>(`/api/speaking-sessions/${sessionId}/chunks/${chunkId}/access`, {
      rt_ms: rtMs,
    }),

  chunkEmbedExposure: (sessionId: number, chunkId: number, wav: Blob, t0OffsetSamples: number) =>
    uploadAttempt<{ attempt_id: number }>(
      `/api/speaking-sessions/${sessionId}/chunks/${chunkId}/embed`,
      wav,
      { t0_offset_samples: t0OffsetSamples }
    ),

  endSession: (sessionId: number) =>
    postJson<SessionSummary>(`/api/speaking-sessions/${sessionId}/end`, {}),

  selfTranscriptionAvailable: (sessionId: number) =>
    fetch(`/api/speaking-sessions/${sessionId}/self-transcription/available`).then((r) =>
      json<{ available: boolean }>(r)
    ),

  submitSelfTranscription: (sessionId: number, userText: string) =>
    postJson<{ user_text: string; whisper_text: string }>(
      `/api/speaking-sessions/${sessionId}/self-transcription`,
      { user_text: userText }
    ),

  // --- czytanie (faza 0 - rozgrzewka, trener tempa) -----------------------

  submitReading: (wav: Blob, meta: { reference_text: string; target_wpm: number }) => {
    const fd = new FormData();
    fd.append("audio", wav, "reading.wav");
    fd.append("payload", JSON.stringify(meta));
    return fetch("/api/reading", { method: "POST", body: fd }).then((r) =>
      json<{ reading_id: number }>(r)
    );
  },

  getReading: (readingId: number) =>
    fetch(`/api/reading/${readingId}`).then((r) => json<ReadingResult>(r)),

  readingStructures: () =>
    fetch("/api/reading/structures").then((r) => json<{ id: string; label: string }[]>(r)),

  generateReadingText: async (body: {
    minutes: number;
    target_wpm: number;
    topic: string;
    structures: string[];
  }) => {
    const res = await fetch("/api/reading/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await errorMessage(res));
    return res.json() as Promise<{
      title: string;
      text: string;
      word_count: number;
      requested_words: number;
      estimated_seconds: number;
      contains_digits: boolean;
    }>;
  },

  readingHistory: () =>
    fetch("/api/reading").then((r) =>
      json<
        {
          reading_id: number;
          created_at: string;
          target_wpm: number;
          wpm: number | null;
          accuracy: number | null;
          words_read: number | null;
        }[]
      >(r)
    ),

  // --- postęp ---------------------------------------------------------------

  progress: (days = 90, probeType: TransferProbeType | "legacy" = "far") =>
    fetch(`/api/stats/progress?days=${days}&probe_type=${probeType}`).then((r) =>
      json<{
        days: number;
        probe_type: string;
        series: Record<string, number | string | null>[];
      }>(r)
    ),

  // --- Bottleneck Diagnostic --------------------------------------------

  startDiagnostic: (languageControlEnabled: boolean) =>
    postJson<DiagnosticSessionDto>("/api/diagnostics/start", {
      language_control_enabled: languageControlEnabled,
    }),

  getDiagnostic: (sessionId: number) =>
    fetch(`/api/diagnostics/${sessionId}`).then((r) => json<DiagnosticSessionDto>(r)),

  submitDiagnosticPlan: (sessionId: number, trialId: number, items: string[]) =>
    postJson<{ ok: boolean; items: string[] }>(`/api/diagnostics/${sessionId}/plan`, {
      trial_id: trialId,
      items,
    }),

  submitDiagnosticAttempt: (sessionId: number, condition: DiagnosticCondition, wav: Blob, t0OffsetSamples: number) =>
    uploadAttempt<{ attempt_id: number }>(
      `/api/diagnostics/${sessionId}/trials/${condition}/attempts`,
      wav,
      { t0_offset_samples: t0OffsetSamples }
    ),

  getDiagnosticAttempt: (attemptId: number) =>
    fetch(`/api/diagnostics/attempts/${attemptId}`).then((r) =>
      json<{ attempt_id: number; status: "processing" | "done" | "error"; transcript: string | null }>(r)
    ),

  endDiagnostic: (sessionId: number) =>
    postJson<DiagnosticSessionDto>(`/api/diagnostics/${sessionId}/end`, {}),

  getBottleneckProfile: () =>
    fetch("/api/diagnostics/profile").then((r) => json<{ profile: BottleneckProfile | null }>(r)),

  // --- Recovery Drill ------------------------------------------------------

  getRecoveryStaticTrial: (kind: RecoveryKind) =>
    fetch(`/api/recovery/trials/${kind}`).then((r) => json<RecoveryStaticTrial>(r)),

  submitRecoveryAttempt: (kind: RecoveryKind, wav: Blob, t0OffsetSamples: number) =>
    uploadAttempt<{ attempt_id: number; recovery_attempt_id: number }>(
      `/api/recovery/trials/${kind}/attempts`,
      wav,
      { t0_offset_samples: t0OffsetSamples }
    ),

  getRecoveryFollowUp: (lostThreadAttemptId: number) =>
    postJson<{ recovery_attempt_id: number; question: string }>("/api/recovery/follow-up", {
      lost_thread_attempt_id: lostThreadAttemptId,
    }),

  submitRecoveryFollowUpAttempt: (recoveryAttemptId: number, wav: Blob, t0OffsetSamples: number) =>
    uploadAttempt<{ attempt_id: number }>(
      `/api/recovery/follow-up/${recoveryAttemptId}/attempts`,
      wav,
      { t0_offset_samples: t0OffsetSamples }
    ),

  getRecoveryAttempt: (attemptId: number) =>
    fetch(`/api/recovery/attempts/${attemptId}`).then((r) =>
      json<{ attempt_id: number; status: "processing" | "done" | "error"; transcript: string | null }>(r)
    ),

  // --- Rozmowa (GPT-Live) ---------------------------------------------------

  conversationPersonas: () =>
    fetch("/api/conversation/personas").then((r) => json<{ personas: string[] }>(r)),

  startConversation: (sdpOffer: string, persona: string, maxMinutes: number) =>
    postJson<{ session_id: number; sdp_answer: string; max_minutes: number }>(
      "/api/conversation/start",
      { sdp_offer: sdpOffer, persona, max_minutes: maxMinutes }
    ),

  endConversation: (id: number, wav: Blob, turns: ConversationWindow[], billedSeconds: number | null) =>
    uploadAttempt<{ session_id: number }>(`/api/conversation/${id}/end`, wav, {
      turns,
      billed_seconds: billedSeconds,
    }),

  getConversation: (id: number) =>
    fetch(`/api/conversation/${id}`).then((r) => json<ConversationResult>(r)),

  // --- Grammar: rundy, mapa, most do rozmów ---------------------------------

  grammarHome: () => fetch("/api/grammar/home").then((r) => json<GrammarHome>(r)),

  grammarMap: () => fetch("/api/grammar/map").then((r) => json<{ groups: SkillGroup[] }>(r)),

  /** null = bank zadań jeszcze się generuje (HTTP 409) - ponów za chwilę */
  createRound: async (): Promise<GrammarRoundDto | null> => {
    const res = await fetch("/api/grammar/rounds", { method: "POST" });
    if (res.status === 409) return null;
    if (!res.ok && res.status !== 401) throw new Error(await errorMessage(res));
    return json<GrammarRoundDto>(res);
  },

  submitRoundAnswer: (roundId: number, index: number, wav: Blob, hintUsed: boolean) =>
    uploadAttempt<{ answer_id: number }>(`/api/grammar/rounds/${roundId}/answers`, wav, {
      index,
      hint_used: hintUsed,
    }),

  getRoundAnswer: (answerId: number) =>
    fetch(`/api/grammar/answers/${answerId}`).then((r) => json<GrammarAnswerDto>(r)),

  skipRoundEntry: (roundId: number, index: number) =>
    postJson<GrammarAnswerDto>(`/api/grammar/rounds/${roundId}/skip`, { index }),

  extraRoundEntry: (roundId: number, skillId: string) =>
    postJson<{ entry: RoundEntry | null }>(`/api/grammar/rounds/${roundId}/extra`, {
      skill_id: skillId,
    }),

  endRound: (roundId: number) =>
    postJson<{ round_id: number; summary: RoundSummary; home: GrammarHome }>(
      `/api/grammar/rounds/${roundId}/end`,
      {}
    ),

  talkPrompt: () =>
    fetch("/api/grammar/talk-prompt").then((r) =>
      json<{ text: string; skills: { id: string; meaning: string }[] }>(r)
    ),

  reviewTranscript: (text: string) =>
    postJson<TranscriptReview>("/api/grammar/transcript", { text }),

  // --- Shadowing ----------------------------------------------------------------

  shadowNext: async (excludeId?: number): Promise<ShadowPassage> => {
    const res = await fetch(`/api/shadow/next${excludeId ? `?exclude=${excludeId}` : ""}`);
    if (!res.ok && res.status !== 401) throw new Error(await errorMessage(res));
    return json<ShadowPassage>(res);
  },

  submitShadowAttempt: (
    passageId: number,
    wav: Blob,
    meta: { with_text: boolean; speed: number; offset_s: number }
  ) =>
    uploadAttempt<{ attempt_id: number }>(`/api/shadow/passages/${passageId}/attempts`, wav, meta),

  getShadowAttempt: (attemptId: number) =>
    fetch(`/api/shadow/attempts/${attemptId}`).then((r) => json<ShadowAttemptDto>(r)),
};

// --- Grammar ------------------------------------------------------------------

export type LevelName = "new" | "learning" | "unaided" | "solid" | "mastered";

export interface GrammarHome {
  llm_ready: boolean;
  bank_items: number;
  total_skills: number;
  counts: Record<LevelName, number>;
  due_today: number;
  in_progress: string[];
  next_new: string | null;
  week: { date: string; done: boolean }[];
  week_days_done: number;
  weekly_goal: number;
  today_index: number;
  answers_today: number;
  answers_total: number;
}

export interface SkillDto {
  id: string;
  meaning: string;
  pl: string;
  pattern: string;
  example: string;
  name: string;
  trap_pl: string;
  level: number;
  level_name: LevelName;
  due: boolean;
  next_due: string | null;
  attempts: number;
  correct: number;
  wild_uses: number;
}

export interface SkillGroup {
  id: string;
  label: string;
  skills: SkillDto[];
}

export type EntryKind = "probe" | "learn" | "practice" | "review" | "extra";
export type EntryFormat = "guided" | "situation" | "translate" | "fix" | "personal" | "own";

export interface RoundEntry {
  index: number;
  kind: EntryKind;
  fmt: EntryFormat;
  skill_id: string;
  prompt: string;
  cue: string;
  hint: string;
  show_pattern: boolean;
  pattern: string;
  meaning: string;
  name: string;
  model_answer: string;
  accepted_variants: string[];
}

export interface GrammarRoundDto {
  round_id: number;
  entries: RoundEntry[];
  summary: RoundSummary | null;
}

export type Verdict = "correct" | "incorrect" | "avoided" | "unclear";

export interface GrammarAnswerDto {
  answer_id: number;
  status: "processing" | "done" | "error";
  transcript: string | null;
  latency_ms: number | null;
  verdict: Verdict | null;
  error_type: string | null;
  explanation: string | null;
  note_pl: string | null;
  corrected: string | null;
  reaction: string | null;
  skill_id: string;
  skill_label: string;
  level_before: number | null;
  level_after: number | null;
}

export interface RoundSummary {
  answered: number;
  graded: number;
  correct: number;
  moved: { skill_id: string; label: string; from: number; to: number; up: boolean }[];
  to_revisit: { skill_id: string; label: string }[];
  median_latency_ms: number | null;
}

export interface TranscriptReview {
  findings: {
    skill_id: string | null;
    skill_label: string | null;
    said: string;
    corrected: string;
    explanation: string;
  }[];
  used_well: { skill_id: string; label: string }[];
  summary: string;
}

// --- Shadowing ----------------------------------------------------------------

export interface ShadowWord {
  text: string;
  sentence: number;
  start: number;
  end: number;
}

export interface ShadowPassage {
  passage_id: number;
  title: string;
  text: string;
  duration_s: number;
  audio_url: string;
  words: ShadowWord[];
  sentences: { index: number; text: string; start: number; end: number }[];
  skills: string[];
}

export interface ShadowMetrics {
  total_words: number;
  said: number;
  unclear: number;
  missed: number;
  coverage: number | null;
  sentences: {
    index: number;
    words: number;
    said: number;
    coverage: number;
    user_start: number | null;
    user_end: number | null;
  }[];
  hardest_sentence: number | null;
  lag_median_s: number | null;
  lag_drift_s: number | null;
  transcript_missing: boolean;
}

export interface ShadowAttemptDto {
  attempt_id: number;
  status: "processing" | "done" | "error";
  with_text: boolean;
  speed: number;
  metrics: ShadowMetrics | null;
  words:
    | { text: string; sentence: number; status: "spoken" | "unclear" | "missed"; lag: number | null }[]
    | null;
}

export interface ConversationWindow {
  start_s: number;
  end_s: number;
}

export interface ConversationTurnResult {
  number: number;
  start_s: number;
  end_s: number;
  metrics: Record<string, number | null>;
}

export interface ConversationResult {
  session_id: number;
  status: "active" | "processing" | "done" | "error";
  persona: string;
  billed_seconds: number | null;
  turns: ConversationTurnResult[];
}
