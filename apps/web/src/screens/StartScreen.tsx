import { useEffect, useState } from "react";
import { api, ModuleInfo } from "../api/client";

interface Props {
  calibrated: boolean;
  onStartSession: (module: string) => void;
  onCalibrate: () => void;
}

export default function StartScreen({ calibrated, onStartSession, onCalibrate }: Props) {
  const [modules, setModules] = useState<ModuleInfo[]>([]);
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
            Przed pierwszą sesją: 10 sekund ciszy do kalibracji progu detekcji mowy
            w Twoim pomieszczeniu.
          </p>
          <button className="btn" onClick={onCalibrate}>
            Kalibruj
          </button>
        </div>
      ) : (
        <div className="flex w-full max-w-md flex-col gap-3">
          {modules.map((m) => (
            <button
              key={m.id}
              className="flex items-center justify-between rounded border border-neutral-800 px-6 py-4 text-left hover:border-neutral-500"
              onClick={() => onStartSession(m.id)}
            >
              <span className="text-lg">{m.name}</span>
              <span className="font-mono text-sm text-neutral-500">
                poziom {m.difficulty} · {m.attempts_per_session} prób
              </span>
            </button>
          ))}
          <button
            className="mt-6 self-center text-sm text-neutral-600 underline"
            onClick={onCalibrate}
          >
            ponowna kalibracja
          </button>
        </div>
      )}
    </div>
  );
}
