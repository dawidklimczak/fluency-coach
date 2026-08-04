import { useRef, useState } from "react";
import { api } from "../api/client";
import { Recorder } from "../audio/recorder";
import { encodeWav } from "../audio/wav";

interface Props {
  onDone: () => void;
}

const CALIBRATION_S = 10;

export default function CalibrationScreen({ onDone }: Props) {
  const [state, setState] = useState<"idle" | "recording" | "uploading" | "done" | "error">("idle");
  const [secondsLeft, setSecondsLeft] = useState(CALIBRATION_S);
  const [result, setResult] = useState<{ noise_floor_db: number; vad_threshold: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const recorderRef = useRef<Recorder | null>(null);

  const start = async () => {
    try {
      setState("recording");
      const rec = await Recorder.create();
      recorderRef.current = rec;
      await rec.start();

      let left = CALIBRATION_S;
      setSecondsLeft(left);
      const iv = window.setInterval(async () => {
        left -= 1;
        setSecondsLeft(left);
        if (left <= 0) {
          window.clearInterval(iv);
          const samples = rec.stop();
          await rec.destroy();
          recorderRef.current = null;
          setState("uploading");
          try {
            const r = await api.calibrate(encodeWav(samples));
            setResult(r);
            setState("done");
          } catch (e) {
            setError(String(e));
            setState("error");
          }
        }
      }, 1000);
    } catch (e) {
      setError(String(e));
      setState("error");
    }
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-8 p-8">
      {state === "idle" && (
        <>
          <p className="max-w-md text-center text-neutral-300">
            Stay silent for {CALIBRATION_S} seconds. This measures the noise floor
            of your room and microphone.
          </p>
          <button className="btn" onClick={start}>
            Start
          </button>
        </>
      )}

      {state === "recording" && (
        <div className="text-center">
          <div className="font-mono text-8xl tabular-nums">{secondsLeft}</div>
          <p className="mt-4 text-neutral-500">silence...</p>
        </div>
      )}

      {state === "uploading" && <p className="text-neutral-400">Analyzing...</p>}

      {state === "done" && result && (
        <>
          <div className="text-center font-mono text-neutral-300">
            <p>noise floor: {result.noise_floor_db.toFixed(1)} dB</p>
            <p>VAD threshold: {result.vad_threshold.toFixed(3)}</p>
          </div>
          <button className="btn" onClick={onDone}>
            Done
          </button>
        </>
      )}

      {state === "error" && (
        <>
          <p className="max-w-md text-center text-red-400">{error}</p>
          <button className="btn" onClick={() => setState("idle")}>
            Try again
          </button>
        </>
      )}
    </div>
  );
}
