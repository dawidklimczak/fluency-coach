export interface StructureHint {
  label: string;
  hint: string | null;
  example: string | null;
}

export interface StructureCheatsheet {
  form: string;
  use: string[];
  examples: string[];
  mistake: string | null;
}

export interface StructureOption {
  id: string;
  label: string;
  cheatsheet: StructureCheatsheet | null;
}

export interface TaskDto {
  id: string;
  module: string;
  difficulty: number;
  target_structure: string | null;
  prompt_text: string;
  payload: Record<string, unknown> | null;
  structure_mode: "explicit" | "implicit" | null;
  structure_hint: StructureHint | null;
}

export interface DrillConfig {
  id: string;
  name: string;
  stimulus: string;
  prep_time_s: number;
  min_speak_s: number;
  max_speak_s: number;
  auto_stop_silence_s: number;
  rounds: number;
  round_speak_s?: number[];
  attempts_per_session: number;
  primary_metrics: string[];
  show_timer: boolean;
}

export interface ModuleInfo {
  id: string;
  name: string;
  attempts_per_session: number;
  max_speak_s: number;
  difficulty: number;
}

export interface AttemptResult {
  attempt_id: number;
  status: "processing" | "done" | "error";
  metrics: Record<string, any> | null;
  transcript: string | null;
}

export interface LearningSessionState {
  id: number;
  number: number;
  started_at: string;
  attempts: number;
  modules_done: string[];
  fatigue_detected: boolean;
}

export interface GrammarNote {
  pattern: string;
  example: string | null;
  note: string | null;
}

export interface SessionFeedback {
  comment: string;
  went_well: string[];
  to_improve: string[];
  grammar: GrammarNote[];
}

export interface LearningSessionSummary {
  number: number;
  started_at: string;
  ended_at: string;
  attempts: number;
  modules: {
    module: string;
    attempts: number;
    median_ttfw: number | null;
    median_mean_length_of_run: number | null;
    long_pause_total: number;
  }[];
  median_ttfw: number | null;
  fatigue_detected: boolean;
  fatigue_curve: { index: number; ttfw: number | null; filler_rate: number | null }[];
  feedback: SessionFeedback | null;
}

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

/** Wyciąga komunikat z `detail` FastAPI, żeby użytkownik widział powód. */
async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return typeof body.detail === "string" ? body.detail : JSON.stringify(body);
  } catch {
    return `HTTP ${res.status}`;
  }
}

export const api = {
  health: () => fetch("/api/health").then((r) => json<{ ok: boolean; vad_model: boolean; transcription: boolean }>(r)),

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

  modules: () => fetch("/api/sessions/modules").then((r) => json<ModuleInfo[]>(r)),

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

  structures: () =>
    fetch("/api/sessions/structures").then((r) => json<StructureOption[]>(r)),

  learningSessionStart: () =>
    fetch("/api/learning-sessions", { method: "POST" }).then((r) =>
      json<LearningSessionState & { resumed: boolean }>(r)
    ),

  learningSessionCurrent: () =>
    fetch("/api/learning-sessions/current").then((r) =>
      json<{ open: boolean } & Partial<LearningSessionState>>(r)
    ),

  learningSessionEnd: (id: number) =>
    fetch(`/api/learning-sessions/${id}/end`, { method: "POST" }).then((r) =>
      json<{ summary: LearningSessionSummary }>(r)
    ),

  createSession: (
    module: string,
    structureFilter?: string | null,
    learningSessionId?: number | null
  ) =>
    fetch("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        module,
        structure_filter: structureFilter ?? null,
        learning_session_id: learningSessionId ?? null,
      }),
    }).then((r) =>
      json<{
        session_id: number;
        module: string;
        difficulty: number;
        first_task: TaskDto;
        drill_config: DrillConfig;
      }>(r)
    ),

  nextTask: (sessionId: number) =>
    fetch(`/api/sessions/${sessionId}/next-task`).then((r) =>
      json<{ task: TaskDto; drill_config: DrillConfig; difficulty: number }>(r)
    ),

  submitAttempt: (
    wav: Blob,
    meta: {
      session_id: number;
      task_id: string;
      t0_offset_samples: number;
      attempt_index: number;
      round_index: number;
      structure_mode?: "explicit" | "implicit" | null;
    }
  ) => {
    const fd = new FormData();
    fd.append("audio", wav, "attempt.wav");
    fd.append("payload", JSON.stringify(meta));
    return fetch("/api/attempts", { method: "POST", body: fd }).then((r) =>
      json<{ attempt_id: number }>(r)
    );
  },

  submitReading: (
    wav: Blob,
    meta: { reference_text: string; target_wpm: number }
  ) => {
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
    fetch("/api/reading/structures").then((r) =>
      json<{ id: string; label: string }[]>(r)
    ),

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

  getAttempt: (attemptId: number) =>
    fetch(`/api/attempts/${attemptId}`).then((r) => json<AttemptResult>(r)),

  progress: (module: string, days = 30) =>
    fetch(`/api/stats/progress?module=${encodeURIComponent(module)}&days=${days}`).then(
      (r) =>
        json<{
          module: string;
          days: number;
          series: Record<string, number | string | null>[];
        }>(r)
    ),

  structuresHeatmap: () =>
    fetch("/api/stats/structures").then((r) =>
      json<{
        baseline_ttfw: number | null;
        structures: {
          structure: string;
          attempts: number;
          avoidance: number | null;
          avoidance_explicit: number | null;
          avoidance_implicit: number | null;
          ttfw_structured: number | null;
          pre_structure_pause: number | null;
        }[];
      }>(r)
    ),

  observations: () =>
    fetch("/api/stats/observations").then((r) =>
      json<{
        generated_at: string | null;
        stale: boolean;
        items: { pattern: string; example: string | null; note: string | null }[];
      }>(r)
    ),

  endSession: (sessionId: number) =>
    fetch(`/api/sessions/${sessionId}/end`, { method: "POST" }).then((r) =>
      json<{ summary: unknown; fatigue_detected: boolean }>(r)
    ),
};
