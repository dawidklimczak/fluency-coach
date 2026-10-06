import { useEffect, useRef, useState } from "react";
import { api, RecoveryKind, RecoveryStaticTrial } from "../api/client";
import { Recorder } from "../audio/recorder";
import { encodeWav } from "../audio/wav";

interface Props {
  onDone: () => void;
  onAbort: () => void;
}

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

async function pollAttempt(attemptId: number) {
  for (;;) {
    const s = await api.getRecoveryAttempt(attemptId);
    if (s.status !== "processing") return;
    await new Promise((r) => setTimeout(r, 600));
  }
}

// spec zmian §8.2: żadna liczba ani ocena nie jest pokazywana użytkownikowi -
// mierzymy w tle, ekran po prostu prowadzi przez 3 krótkie kroki
type Step =
  | { kind: "static"; recoveryKind: RecoveryKind }
  | { kind: "followUp" };

const STEPS: Step[] = [
  { kind: "static", recoveryKind: "lost_thread" },
  { kind: "static", recoveryKind: "reformulation" },
  { kind: "followUp" },
];

export default function RecoveryDrillScreen({ onDone, onAbort }: Props) {
  const [stepIndex, setStepIndex] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [lostThreadAttemptId, setLostThreadAttemptId] = useState<number | null>(null);
  const recorderRef = useRef<Recorder | null>(null);

  useEffect(() => {
    Recorder.create()
      .then((r) => (recorderRef.current = r))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    return () => {
      recorderRef.current?.destroy();
    };
  }, []);

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

  if (!recorderRef.current) {
    return (
      <div className="flex min-h-screen items-center justify-center text-neutral-500">Getting ready...</div>
    );
  }

  const step = STEPS[stepIndex];
  const next = () => {
    if (stepIndex + 1 < STEPS.length) setStepIndex((i) => i + 1);
    else onDone();
  };

  return (
    <div className="mx-auto flex min-h-screen max-w-2xl flex-col gap-8 p-8">
      <div className="flex items-center justify-between text-xs uppercase tracking-wide text-neutral-600">
        <span>Recovery drill</span>
        <span>
          {stepIndex + 1} / {STEPS.length}
        </span>
      </div>

      {step.kind === "static" && (
        <StaticStep
          key={step.recoveryKind}
          kind={step.recoveryKind}
          recorder={recorderRef.current}
          onDone={(attemptId) => {
            if (step.recoveryKind === "lost_thread") setLostThreadAttemptId(attemptId);
            next();
          }}
        />
      )}
      {step.kind === "followUp" && lostThreadAttemptId !== null && (
        <FollowUpStep
          lostThreadAttemptId={lostThreadAttemptId}
          recorder={recorderRef.current}
          onDone={next}
        />
      )}
    </div>
  );
}

function StaticStep({
  kind,
  recorder,
  onDone,
}: {
  kind: RecoveryKind;
  recorder: Recorder;
  onDone: (attemptId: number) => void;
}) {
  const [trial, setTrial] = useState<RecoveryStaticTrial | null>(null);
  const [phase, setPhase] = useState<"ready" | "recording" | "processing" | "done">("ready");
  const stopRef = useRef({ current: false });

  useEffect(() => {
    api.getRecoveryStaticTrial(kind).then(setTrial);
  }, [kind]);

  const start = async () => {
    if (!trial) return;
    setPhase("recording");
    stopRef.current.current = false;
    const samples = await recordUntil(recorder, trial.speaking_limit_seconds * 1000 + 500, stopRef.current);
    setPhase("processing");
    const res = await api.submitRecoveryAttempt(kind, encodeWav(samples), 0);
    await pollAttempt(res.attempt_id);
    setPhase("done");
    onDone(res.attempt_id);
  };

  if (!trial) return <p className="text-neutral-500">Loading...</p>;

  return (
    <div className="flex flex-col gap-6">
      <p className="rounded border border-neutral-800 p-6 text-neutral-100">{trial.prompt}</p>
      {trial.suggested_chunk && (
        <p className="text-sm text-neutral-500">
          Optional tool: <span className="text-neutral-300">"{trial.suggested_chunk}"</span>
        </p>
      )}
      {phase === "ready" && (
        <button className="btn self-start" onClick={start}>
          Start speaking
        </button>
      )}
      {phase === "recording" && (
        <button className="btn self-start" onClick={() => (stopRef.current.current = true)}>
          Stop
        </button>
      )}
      {(phase === "processing" || phase === "done") && <p className="text-neutral-500">processing...</p>}
    </div>
  );
}

function FollowUpStep({
  lostThreadAttemptId,
  recorder,
  onDone,
}: {
  lostThreadAttemptId: number;
  recorder: Recorder;
  onDone: () => void;
}) {
  const [question, setQuestion] = useState<string | null>(null);
  const [recoveryAttemptId, setRecoveryAttemptId] = useState<number | null>(null);
  const [phase, setPhase] = useState<"loading" | "ready" | "recording" | "processing" | "done">("loading");
  const stopRef = useRef({ current: false });

  useEffect(() => {
    api.getRecoveryFollowUp(lostThreadAttemptId).then((r) => {
      setQuestion(r.question);
      setRecoveryAttemptId(r.recovery_attempt_id);
      setPhase("ready");
    });
  }, [lostThreadAttemptId]);

  const start = async () => {
    if (recoveryAttemptId === null) return;
    setPhase("recording");
    stopRef.current.current = false;
    const samples = await recordUntil(recorder, 30_500, stopRef.current);
    setPhase("processing");
    const res = await api.submitRecoveryFollowUpAttempt(recoveryAttemptId, encodeWav(samples), 0);
    await pollAttempt(res.attempt_id);
    setPhase("done");
  };

  if (phase === "loading" || question === null) return <p className="text-neutral-500">Loading...</p>;

  return (
    <div className="flex flex-col gap-6">
      <p className="rounded border border-neutral-800 p-6 text-neutral-100">{question}</p>
      <p className="text-sm text-neutral-500">Then return to your original point.</p>
      {phase === "ready" && (
        <button className="btn self-start" onClick={start}>
          Start speaking
        </button>
      )}
      {phase === "recording" && (
        <button className="btn self-start" onClick={() => (stopRef.current.current = true)}>
          Stop
        </button>
      )}
      {phase === "processing" && <p className="text-neutral-500">processing...</p>}
      {phase === "done" && (
        <button className="btn self-start" onClick={onDone}>
          Done
        </button>
      )}
    </div>
  );
}
