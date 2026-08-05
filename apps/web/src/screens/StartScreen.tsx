import { useEffect, useState } from "react";
import { api, LearningSessionState, ModuleInfo } from "../api/client";
import { getTimeLimitOverrides, setTimeLimit } from "../settings";

interface Props {
  calibrated: boolean;
  openSession: LearningSessionState | null;
  onOpenSession: () => void;
  onCalibrate: () => void;
  onProgress: () => void;
  onStructures: () => void;
  onObservations: () => void;
}

export default function StartScreen({
  calibrated,
  openSession,
  onOpenSession,
  onCalibrate,
  onProgress,
  onStructures,
  onObservations,
}: Props) {
  const [modules, setModules] = useState<ModuleInfo[]>([]);
  const [showSettings, setShowSettings] = useState(false);
  const [overrides, setOverrides] = useState<Record<string, number>>(
    getTimeLimitOverrides()
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.modules().then(setModules).catch((e) => setError(String(e)));
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
        <div className="flex w-full max-w-md flex-col items-center gap-6">
          <button
            className="w-full rounded border border-neutral-600 px-8 py-5 text-xl text-neutral-100 hover:border-neutral-300"
            onClick={onOpenSession}
          >
            {openSession
              ? `Resume session #${openSession.number}`
              : "Start session"}
          </button>
          {openSession && (
            <p className="text-sm text-neutral-500">
              open since {openSession.started_at.slice(0, 16).replace("T", " ")} ·{" "}
              {openSession.attempts} attempts so far
            </p>
          )}

          {showSettings && (
            <div className="w-full rounded border border-neutral-800 p-4">
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

          <div className="flex justify-center gap-6 text-sm text-neutral-600">
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
              observations
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
