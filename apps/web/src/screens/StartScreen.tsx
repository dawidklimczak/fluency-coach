import { useEffect, useState } from "react";
import { api, ModuleInfo } from "../api/client";
import { getTimeLimitOverrides, setTimeLimit } from "../settings";

interface Props {
  calibrated: boolean;
  onStartSession: (module: string, structureFilter: string | null) => void;
  onCalibrate: () => void;
  onProgress: () => void;
  onStructures: () => void;
  onObservations: () => void;
}

export default function StartScreen({
  calibrated,
  onStartSession,
  onCalibrate,
  onProgress,
  onStructures,
  onObservations,
}: Props) {
  const [modules, setModules] = useState<ModuleInfo[]>([]);
  const [structures, setStructures] = useState<{ id: string; label: string }[]>([]);
  const [filter, setFilter] = useState<string>("");
  const [showSettings, setShowSettings] = useState(false);
  const [overrides, setOverrides] = useState<Record<string, number>>(
    getTimeLimitOverrides()
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.modules().then(setModules).catch((e) => setError(String(e)));
    api.structures().then(setStructures).catch(() => {});
  }, []);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-10 p-8">
      <h1 className="text-2xl font-medium tracking-tight text-neutral-300">
        Speaking Automaticity Trainer
      </h1>

      {error && <p className="text-red-400">{error}</p>}

      {!calibrated ? (
        <div className="flex flex-col items-center gap-4">
          <p className="max-w-md text-center text-neutral-400">
            Before your first session: 10 seconds of silence to calibrate speech
            detection for your room.
          </p>
          <button className="btn" onClick={onCalibrate}>
            Calibrate
          </button>
        </div>
      ) : (
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
              onClick={() => onStartSession(m.id, filter || null)}
            >
              <span className="text-lg">{m.name}</span>
              <span className="font-mono text-sm text-neutral-500">
                level {m.difficulty} · {m.attempts_per_session} attempts ·{" "}
                {overrides[m.id] ?? m.max_speak_s}s
              </span>
            </button>
          ))}

          {showSettings && (
            <div className="mt-4 rounded border border-neutral-800 p-4">
              <p className="mb-3 text-sm uppercase tracking-wide text-neutral-500">
                speaking time limit (seconds, empty = default)
              </p>
              <div className="flex flex-col gap-2">
                {modules.map((m) => (
                  <label
                    key={m.id}
                    className="flex items-center justify-between text-sm text-neutral-400"
                  >
                    <span>{m.name}</span>
                    <input
                      type="number"
                      min={5}
                      max={300}
                      className="w-24 rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-right font-mono text-neutral-200"
                      placeholder={String(m.max_speak_s)}
                      value={overrides[m.id] ?? ""}
                      onChange={(e) => {
                        const v = e.target.value === "" ? null : Number(e.target.value);
                        setTimeLimit(m.id, v);
                        setOverrides(getTimeLimitOverrides());
                      }}
                    />
                  </label>
                ))}
              </div>
              <p className="mt-3 text-xs text-neutral-600">
                Story Loop rounds scale proportionally (90/60/45 at the default 90s).
              </p>
            </div>
          )}

          <div className="mt-6 flex justify-center gap-6 text-sm text-neutral-600">
            <button className="underline" onClick={() => setShowSettings(!showSettings)}>
              time limits
            </button>
            <button className="underline" onClick={onProgress}>
              progress
            </button>
            <button className="underline" onClick={onStructures}>
              structures
            </button>
            <button className="underline" onClick={onObservations}>
              weekly notes
            </button>
            <button className="underline" onClick={onCalibrate}>
              recalibrate
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
