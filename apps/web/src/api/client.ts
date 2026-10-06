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
};

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
