import { useEffect, useRef, useState } from "react";
import { api, DiagnosticSessionDto, DiagnosticTrial } from "../api/client";
import { Recorder } from "../audio/recorder";
import { encodeWav } from "../audio/wav";

interface Props {
  languageControlEnabled: boolean;
  onDone: (note: string[] | null) => void;
  onAbort: () => void;
}

const CONDITION_LABEL: Record<string, string> = {
  cold: "No prep - answer right away",
  supplied_ideas: "A few directions to use",
  self_plan: "Write your own short plan",
  repetition: "Same question again",
  native_control: "Same type of question - in Polish",
};

async function recordUntil(recorder: Recorder, maxMs: number, stopRef: { current: boolean }): Promise<Float32Array> {
  await recorder.start();
  await new Promise<void>((resolve) => {
    const start = performance.now();
    const tick = () => {
      if (stopRef.current || performance.now() - start >= maxMs) resolve();
      else requestAnimationFrame(tick);
    };
    tick();
  });
  return recorder.stop();
}

async function pollAttempt(getStatus: (id: number) => Promise<{ status: string }>, attemptId: number) {
  for (;;) {
    const s = await getStatus(attemptId);
    if (s.status !== "processing") return;
    await new Promise((r) => setTimeout(r, 600));
  }
}

export default function DiagnosticScreen({ languageControlEnabled, onDone, onAbort }: Props) {
  const [session, setSession] = useState<DiagnosticSessionDto | null>(null);
  const [trialIndex, setTrialIndex] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const recorderRef = useRef<Recorder | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [s, recorder] = await Promise.all([
          api.startDiagnostic(languageControlEnabled),
          Recorder.create(),
        ]);
        recorderRef.current = recorder;
        setSession(s);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      recorderRef.current?.destroy();
    };
  }, [languageControlEnabled]);

  if (error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-8">
        <p className="max-w-lg text-center text-red-400">{error}</p>
        <button className="btn" onClick={onAbort}>
          Back
        </button>
      </div>
    );
  }

  if (!session) {
    return (
      <div className="flex min-h-screen items-center justify-center text-neutral-500">
        Preparing your questions...
      </div>
    );
  }

  const trial = session.trials[trialIndex];
  if (!trial) return null;

  const finish = async () => {
    const ended = await api.endDiagnostic(session.session_id);
    onDone(ended.note);
  };

  return (
    <div className="mx-auto flex min-h-screen max-w-2xl flex-col gap-8 p-8">
      <div className="flex items-center justify-between text-xs uppercase tracking-wide text-neutral-600">
        <span>Bottleneck diagnostic</span>
        <span>
          {trialIndex + 1} / {session.trials.length}
        </span>
      </div>
      <TrialRunner
        key={trial.id}
        sessionId={session.session_id}
        trial={trial}
        recorder={recorderRef.current!}
        onNext={() => {
          if (trialIndex + 1 < session.trials.length) setTrialIndex((i) => i + 1);
          else finish().catch((e) => setError(e instanceof Error ? e.message : String(e)));
        }}
      />
    </div>
  );
}

function TrialRunner({
  sessionId,
  trial,
  recorder,
  onNext,
}: {
  sessionId: number;
  trial: DiagnosticTrial;
  recorder: Recorder;
  onNext: () => void;
}) {
  const needsPlan = trial.condition === "self_plan";
  const [items, setItems] = useState<string[]>([""]);
  const [planSubmitted, setPlanSubmitted] = useState(false);
  const [phase, setPhase] = useState<"planning" | "speaking" | "processing" | "done">(
    trial.planning_seconds > 0 ? "planning" : "speaking"
  );
  const [remaining, setRemaining] = useState(trial.planning_seconds || trial.speaking_limit_seconds);
  const stopRef = useRef({ current: false });
  const startedSpeaking = useRef(false);

  useEffect(() => {
    if (phase !== "planning" && phase !== "speaking") return;
    const id = setInterval(() => setRemaining((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(id);
  }, [phase]);

  useEffect(() => {
    if (phase === "planning" && remaining <= 0) {
      if (needsPlan && !planSubmitted) submitPlan();
      setPhase("speaking");
      setRemaining(trial.speaking_limit_seconds);
    }
    if (phase === "speaking" && remaining <= 0) stopRef.current.current = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, remaining, trial.speaking_limit_seconds]);

  useEffect(() => {
    if (phase !== "speaking" || startedSpeaking.current) return;
    startedSpeaking.current = true;
    (async () => {
      const samples = await recordUntil(recorder, trial.speaking_limit_seconds * 1000 + 500, stopRef.current);
      setPhase("processing");
      const res = await api.submitDiagnosticAttempt(sessionId, trial.condition, encodeWav(samples), 0);
      await pollAttempt(api.getDiagnosticAttempt, res.attempt_id);
      setPhase("done");
    })();
  }, [phase, recorder, sessionId, trial]);

  const submitPlan = async () => {
    if (planSubmitted) return;
    setPlanSubmitted(true);
    const cleaned = items.map((i) => i.trim()).filter(Boolean);
    if (cleaned.length === 0) return;
    await api.submitDiagnosticPlan(sessionId, trial.id, cleaned).catch(() => {});
  };

  const continueEarly = () => {
    submitPlan();
    setPhase("speaking");
    setRemaining(trial.speaking_limit_seconds);
  };

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-lg text-neutral-300">{CONDITION_LABEL[trial.condition]}</h2>
      <p className="rounded border border-neutral-800 p-6 text-center text-xl text-neutral-100">
        {trial.prompt}
      </p>

      {trial.support_json?.ideas && (
        <ul className="flex flex-col gap-1 text-neutral-300">
          {trial.support_json.ideas.map((idea, i) => (
            <li key={i}>- {idea}</li>
          ))}
        </ul>
      )}

      {needsPlan && !planSubmitted && (
        <div className="flex flex-col gap-2">
          <p className="text-sm text-neutral-500">
            Up to 3 points, max 5 words each - {remaining}s
          </p>
          {items.map((val, i) => (
            <input
              key={i}
              className="rounded border border-neutral-800 bg-neutral-950 px-4 py-2 text-neutral-100"
              placeholder={`Point ${i + 1}`}
              value={val}
              onChange={(e) => {
                const words = e.target.value.split(/\s+/).filter(Boolean);
                const next = words.length > 5 ? words.slice(0, 5).join(" ") : e.target.value;
                setItems((prev) => prev.map((p, idx) => (idx === i ? next : p)));
              }}
            />
          ))}
          {items.length < 3 && (
            <button className="self-start text-sm text-neutral-500 underline" onClick={() => setItems((p) => [...p, ""])}>
              + add a point
            </button>
          )}
          <button className="btn self-start" onClick={continueEarly}>
            Continue
          </button>
        </div>
      )}

      {phase === "planning" && (!needsPlan || planSubmitted) && (
        <p className="text-2xl text-neutral-200">Starting in {remaining}s</p>
      )}
      {phase === "speaking" && (
        <>
          <p className="text-2xl text-neutral-100">Speaking - {remaining}s left</p>
          <button className="btn self-start" onClick={() => (stopRef.current.current = true)}>
            Stop
          </button>
        </>
      )}
      {phase === "processing" && <p className="text-neutral-500">processing...</p>}
      {phase === "done" && (
        <button className="btn self-start" onClick={onNext}>
          Continue
        </button>
      )}
    </div>
  );
}
