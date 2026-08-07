import { useEffect, useState } from "react";
import { api, LearningSessionState } from "../api/client";

interface Props {
  calibrated: boolean;
  openSession: LearningSessionState | null;
  onOpenSession: () => void;
  onCalibrate: () => void;
  onSettings: () => void;
  onProgress: () => void;
  onStructures: () => void;
  onObservations: () => void;
}

export default function StartScreen({
  calibrated,
  openSession,
  onOpenSession,
  onCalibrate,
  onSettings,
  onProgress,
  onStructures,
  onObservations,
}: Props) {
  const [keyMissing, setKeyMissing] = useState(false);

  useEffect(() => {
    // brak klucza kończyłby się nagraniem bez transkrypcji i bez feedbacku,
    // więc mówimy o tym wprost zanim użytkownik zacznie
    api
      .settings()
      .then((s) => setKeyMissing(!s.openai_key_set))
      .catch(() => {});
  }, []);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-10 p-8">
      <h1 className="text-2xl font-medium tracking-tight text-neutral-300">
        Speaking Automaticity Trainer
      </h1>

      {keyMissing && (
        <div className="max-w-md rounded border border-amber-900 p-4 text-center">
          <p className="text-amber-400">No OpenAI API key set.</p>
          <p className="mt-1 text-sm text-neutral-400">
            Timing metrics work without it, but there will be no transcript and no
            feedback.
          </p>
          <button className="mt-3 text-sm text-neutral-300 underline" onClick={onSettings}>
            add the key
          </button>
        </div>
      )}

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
            {openSession ? `Resume session #${openSession.number}` : "Start session"}
          </button>
          {openSession && (
            <p className="text-sm text-neutral-500">
              open since {openSession.started_at.slice(0, 16).replace("T", " ")} ·{" "}
              {openSession.attempts} attempts so far
            </p>
          )}

          <div className="flex flex-wrap justify-center gap-6 text-sm text-neutral-600">
            <button className="underline" onClick={onProgress}>
              progress
            </button>
            <button className="underline" onClick={onStructures}>
              structures
            </button>
            <button className="underline" onClick={onObservations}>
              observations
            </button>
            <button className="underline" onClick={onSettings}>
              settings
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
