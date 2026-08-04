export interface StructureHint {
  label: string;
  hint: string | null;
  example: string | null;
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
  difficulty: number;
}

export interface AttemptResult {
  attempt_id: number;
  status: "processing" | "done" | "error";
  metrics: Record<string, any> | null;
  transcript: string | null;
}

export interface SessionSummary {
  attempts: number;
  median_ttfw: number | null;
  median_mean_length_of_run: number | null;
  long_pause_total: number;
  baseline_7d_median_ttfw: number | null;
  interpretation: string;
  fatigue_curve: { attempt_index: number; ttfw: number | null; filler_rate: number | null }[];
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json();
}

export const api = {
  health: () => fetch("/api/health").then((r) => json<{ ok: boolean; vad_model: boolean; transcription: boolean }>(r)),

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
    fetch("/api/sessions/structures").then((r) =>
      json<{ id: string; label: string }[]>(r)
    ),

  createSession: (module: string, structureFilter?: string | null) =>
    fetch("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ module, structure_filter: structureFilter ?? null }),
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
      json<{ summary: SessionSummary; fatigue_detected: boolean }>(r)
    ),
};
