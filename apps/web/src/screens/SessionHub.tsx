import { useEffect, useState } from "react";
import {
  api,
  LearningSessionState,
  ModuleInfo,
  StructureOption,
} from "../api/client";
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
  const [structures, setStructures] = useState<StructureOption[]>([]);
  const [filter, setFilter] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const overrides = getTimeLimitOverrides();
  const selected = structures.find((s) => s.id === filter) ?? null;

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

      <div className="flex w-full max-w-4xl flex-col items-start justify-center gap-8 lg:flex-row">
        <div className="mx-auto flex w-full max-w-md flex-col gap-3">
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

        {selected?.cheatsheet && (
          <aside className="mx-auto w-full max-w-md rounded border border-neutral-800 p-5 lg:mx-0 lg:w-80">
            <p className="text-sm uppercase tracking-wide text-sky-400">
              {selected.label}
            </p>
            <p className="mt-2 font-mono text-sm text-neutral-200">
              {selected.cheatsheet.form}
            </p>

            <p className="mt-4 text-xs uppercase tracking-wide text-neutral-500">
              use it for
            </p>
            <ul className="mt-1 flex flex-col gap-1 text-sm text-neutral-300">
              {selected.cheatsheet.use.map((u, i) => (
                <li key={i}>· {u}</li>
              ))}
            </ul>

            <p className="mt-4 text-xs uppercase tracking-wide text-neutral-500">
              sounds like
            </p>
            <ul className="mt-1 flex flex-col gap-1 text-sm italic text-neutral-400">
              {selected.cheatsheet.examples.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>

            {selected.cheatsheet.mistake && (
              <>
                <p className="mt-4 text-xs uppercase tracking-wide text-amber-400">
                  watch out
                </p>
                <p className="mt-1 text-sm text-neutral-400">
                  {selected.cheatsheet.mistake}
                </p>
              </>
            )}
          </aside>
        )}
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
