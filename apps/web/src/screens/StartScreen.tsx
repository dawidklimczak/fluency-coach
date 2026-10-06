import { useEffect, useState } from "react";
import { api } from "../api/client";

interface Props {
  calibrated: boolean;
  onStartSession: () => void;
  onCalibrate: () => void;
  onSettings: () => void;
  onProfile: () => void;
  onReading: () => void;
  onProgress: () => void;
  onDiagnostic: (languageControlEnabled: boolean) => void;
  onBottleneckProfile: () => void;
  onRecoveryDrill: () => void;
  onConversation: () => void;
}

export default function StartScreen({
  calibrated,
  onStartSession,
  onCalibrate,
  onSettings,
  onProfile,
  onReading,
  onProgress,
  onDiagnostic,
  onBottleneckProfile,
  onRecoveryDrill,
  onConversation,
}: Props) {
  const [keyMissing, setKeyMissing] = useState(false);
  const [languageControlEnabled, setLanguageControlEnabled] = useState(false);

  useEffect(() => {
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
            Sessions can't generate material or transcribe without it.
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
            onClick={onStartSession}
          >
            Start session
          </button>

          <button
            className="w-full rounded border border-neutral-800 px-6 py-4 text-left hover:border-neutral-500"
            onClick={onReading}
          >
            <span className="text-lg text-neutral-200">Reading pace trainer</span>
            <span className="mt-1 block text-sm text-neutral-500">
              read a text aloud, see where you speed up and slow down
            </span>
          </button>

          <button
            className="w-full rounded border border-neutral-800 px-6 py-4 text-left hover:border-neutral-500"
            onClick={onConversation}
          >
            <span className="text-lg text-neutral-200">Conversation</span>
            <span className="mt-1 block text-sm text-neutral-500">
              open voice chat with a native-like speaker, numbers afterwards
            </span>
          </button>

          <button
            className="w-full rounded border border-neutral-800 px-6 py-4 text-left hover:border-neutral-500"
            onClick={onRecoveryDrill}
          >
            <span className="text-lg text-neutral-200">Recovery drill</span>
            <span className="mt-1 block text-sm text-neutral-500">
              practice picking a thread back up, not just answering
            </span>
          </button>

          <div className="w-full rounded border border-neutral-800 px-6 py-4 text-left">
            <button className="text-lg text-neutral-200" onClick={() => onDiagnostic(languageControlEnabled)}>
              Bottleneck diagnostic
            </button>
            <span className="mt-1 block text-sm text-neutral-500">
              see whether prep, repetition, or content is the bigger cost
            </span>
            <label className="mt-2 flex items-center gap-2 text-xs text-neutral-500">
              <input
                type="checkbox"
                checked={languageControlEnabled}
                onChange={(e) => setLanguageControlEnabled(e.target.checked)}
              />
              also include one question in Polish
            </label>
          </div>

          <div className="flex flex-wrap justify-center gap-6 text-sm text-neutral-600">
            <button className="underline" onClick={onProfile}>
              profile
            </button>
            <button className="underline" onClick={onProgress}>
              progress
            </button>
            <button className="underline" onClick={onBottleneckProfile}>
              bottleneck profile
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
