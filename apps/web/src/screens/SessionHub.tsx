import { useEffect, useState } from "react";
import { api, LearningSessionState, ModuleInfo } from "../api/client";
import { getTimeLimitOverrides } from "../settings";

interface Props {
  session: LearningSessionState;
  onStartDrill: (module: string, structureFilter: string | null) => void;
  onEndSession: () => void;
  onLeave: () => void;
}

// hub otwartej sesji nauki: szczegóły sesji, wybór ćwiczenia, zakończenie
export default function SessionHub({
  session,
  onStartDrill,
  onEndSession,
  onLeave,
}: Props) {
  const [modules, setModules] = useState<ModuleInfo[]>([]);
  const [structures, setStructures] = useState<{ id: string; label: string }[]>([]);
  const [filter, setFilter] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const overrides = getTimeLimitOverrides();

  useEffect(() => {
    api.modules().then(setModules).catch((e) => setError(String(e)));
    api.structures().then(setStructures).catch(() => {});
  }, []);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-8 p-8">
      <div className="text-center">
        <h1 className="text-2xl font-medium tracking-tight text-neutral-200">
          Session #{session.number}
        </h1>
        <p className="mt-2 font-mono text-sm text-neutral-500">
          {session.started_at.slice(0, 16).replace("T", " ")} · {session.attempts}{" "}
          attempts
          {session.modules_done.length > 0 &&
            ` · ${session.modules_done.join(", ")}`}
        </p>
      </div>

      {session.fatigue_detected && (
        <p className="max-w-md text-center text-amber-400">
          Fatigue was detected earlier in this session - consider ending it.
        </p>
      )}

      {error && <p className="text-red-400">{error}</p>}

      <div className="flex w-full max-w-md flex-col gap-3">
        {structures.length > 0 && (
          <label className="mb-2 flex items-center justify-between gap-4 text-sm text-neutral-500">
            <span>grammar structure filter</span>
            <select
              className="rounded border border-neutral-800 bg-neutral-950 px-3 py-2 text-neutral-300"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            >
              <option value="">off</option>
              {structures.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
        )}

        {modules.map((m) => (
          <button
            key={m.id}
            className="flex items-center justify-between rounded border border-neutral-800 px-6 py-4 text-left hover:border-neutral-500"
            onClick={() => onStartDrill(m.id, filter || null)}
          >
            <span className="text-lg">{m.name}</span>
            <span className="font-mono text-sm text-neutral-500">
              level {m.difficulty} · {overrides[m.id] ?? m.max_speak_s}s
            </span>
          </button>
        ))}
      </div>

      <div className="flex items-center gap-6">
        <button className="btn" onClick={onEndSession}>
          End session
        </button>
        <button className="text-sm text-neutral-600 underline" onClick={onLeave}>
          leave open and go back
        </button>
      </div>
    </div>
  );
}
