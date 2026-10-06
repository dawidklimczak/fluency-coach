import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, AttemptStatus, ChunkDto, SessionPack, SessionSummary, TransferProbeType } from "../api/client";
import { Recorder } from "../audio/recorder";
import { BrowserVad } from "../audio/vad";
import { encodeWav } from "../audio/wav";
import { measureReactionTimeMs } from "../audio/onset";

interface Props {
  onDone: (summary: SessionSummary, sessionId: number) => void;
  onAbort: () => void;
}

type Step =
  | { kind: "reading0" }
  | { kind: "entry1" }
  | { kind: "chunkA" }
  | { kind: "chunkB" }
  | { kind: "keywordPlanning" }
  | { kind: "round"; number: number }
  | { kind: "transfer"; probeType: TransferProbeType };

const SUPPORT_LABEL: Record<number, string> = {
  4: "full support",
  3: "questions + keywords",
  2: "keywords only",
  1: "topic only",
  0: "nothing",
};

// spec zmian §4.2: instrukcja kompresji przed każdą rundą
const ROUND_INSTRUCTION: Record<number, string> = {
  1: "Answer normally. Don't try to cover every possible nuance.",
  2: "Say essentially the same thing, but simpler.",
  3: "Keep only the main point, one example, and maybe one caveat.",
  4: "Get to the point. Don't add new threads.",
};

function buildSteps(pack: SessionPack): Step[] {
  const steps: Step[] = [{ kind: "reading0" }, { kind: "entry1" }, { kind: "chunkA" }];
  if (pack.embed_mode_unlocked && pack.bank_b_chunks.length > 0) steps.push({ kind: "chunkB" });
  // spec zmian §3: keyword planning zastępuje automatyczny writing rehearsal;
  // przy wsparciu 0 nie ma jawnego planowania w ogóle
  if (pack.support_ceiling > 0) steps.push({ kind: "keywordPlanning" });
  for (const r of pack.rounds) steps.push({ kind: "round", number: r.number });
  // spec zmian §6.3: kolejność near/far losowana na backendzie, nie zawsze
  // ta sama - far bywa pominięty, jeśli generacja pytania się nie udała
  for (const probeType of pack.transfer_order) {
    if (probeType === "far" && !pack.far_transfer_prompt) continue;
    steps.push({ kind: "transfer", probeType });
  }
  return steps;
}

async function recordUntil(
  recorder: Recorder,
  maxMs: number,
  stopRef: { current: boolean }
): Promise<Float32Array> {
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

async function pollAttempt(attemptId: number): Promise<AttemptStatus> {
  for (;;) {
    const s = await api.getAttempt(attemptId);
    if (s.status !== "processing") return s;
    await new Promise((r) => setTimeout(r, 600));
  }
}

export default function SessionScreen({ onDone, onAbort }: Props) {
  const [pack, setPack] = useState<SessionPack | null>(null);
  const [steps, setSteps] = useState<Step[]>([]);
  const [stepIndex, setStepIndex] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [ending, setEnding] = useState(false);
  const [keywordPlan, setKeywordPlan] = useState<string[]>([]);

  const recorderRef = useRef<Recorder | null>(null);
  const vadRef = useRef<BrowserVad | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [p, recorder, vad] = await Promise.all([
          api.startSession(),
          Recorder.create(),
          BrowserVad.create(),
        ]);
        recorderRef.current = recorder;
        vadRef.current = vad;
        setPack(p);
        setSteps(buildSteps(p));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      recorderRef.current?.destroy();
    };
  }, []);

  const next = useCallback(() => setStepIndex((i) => i + 1), []);

  const finishSession = useCallback(
    async (sessionId: number) => {
      setEnding(true);
      try {
        const summary = await api.endSession(sessionId);
        onDone(summary, sessionId);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [onDone]
  );

  // po R3: sprawdź czy sesja została przerwana (spec §4), jeśli tak - przeskocz do końca
  const afterRoundDone = useCallback(
    async (roundNumber: number) => {
      if (roundNumber === 3 && pack) {
        const status = await api.sessionStatus(pack.session_id);
        if (status.interrupted) {
          await finishSession(pack.session_id);
          return;
        }
      }
      next();
    },
    [pack, next, finishSession]
  );

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

  if (!pack || ending) {
    return (
      <div className="flex min-h-screen items-center justify-center text-neutral-500">
        {ending ? "Wrapping up..." : "Preparing your session..."}
      </div>
    );
  }

  const step = steps[stepIndex];
  if (!step) return null;

  return (
    <div className="mx-auto flex min-h-screen max-w-2xl flex-col gap-8 p-8">
      <div className="flex items-center justify-between text-xs uppercase tracking-wide text-neutral-600">
        <span>{pack.domain}</span>
        <span>
          step {stepIndex + 1} / {steps.length}
        </span>
      </div>

      {step.kind === "reading0" && <ReadingWarmup pack={pack} recorder={recorderRef.current!} onNext={next} />}
      {step.kind === "entry1" && <EntryPhase pack={pack} onNext={next} />}
      {step.kind === "chunkA" && (
        <ChunkDrillA
          pack={pack}
          recorder={recorderRef.current!}
          vad={vadRef.current!}
          onNext={next}
        />
      )}
      {step.kind === "chunkB" && (
        <ChunkDrillB pack={pack} recorder={recorderRef.current!} onNext={next} />
      )}
      {step.kind === "keywordPlanning" && (
        <KeywordPlanningPhase pack={pack} onNext={(items) => { setKeywordPlan(items); next(); }} />
      )}
      {step.kind === "round" && (
        <RoundPhase
          key={step.number}
          pack={pack}
          roundNumber={step.number}
          keywordPlan={keywordPlan}
          recorder={recorderRef.current!}
          onNext={() => afterRoundDone(step.number)}
        />
      )}
      {step.kind === "transfer" && (
        <TransferPhase
          key={step.probeType}
          pack={pack}
          probeType={step.probeType}
          isLast={steps[stepIndex + 1]?.kind !== "transfer"}
          recorder={recorderRef.current!}
          onNext={
            steps[stepIndex + 1]?.kind === "transfer" ? next : () => finishSession(pack.session_id)
          }
        />
      )}
    </div>
  );
}

// --- Faza 0: rozgrzewka (trener tempa, poza statystykami mowy spontanicznej) --

function ReadingWarmup({
  pack,
  recorder,
  onNext,
}: {
  pack: SessionPack;
  recorder: Recorder;
  onNext: () => void;
}) {
  const [recording, setRecording] = useState(false);
  const [done, setDone] = useState(false);
  const stopRef = useRef({ current: false });

  const start = async () => {
    setRecording(true);
    stopRef.current.current = false;
    const samples = await recordUntil(recorder, 90_000, stopRef.current);
    setRecording(false);
    setDone(true);
    api
      .submitReading(encodeWav(samples), { reference_text: pack.seed_text, target_wpm: 130 })
      .catch(() => {});
  };

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-lg text-neutral-300">Warm-up: read this out loud</h2>
      <p className="whitespace-pre-wrap rounded border border-neutral-800 p-4 text-neutral-200">
        {pack.seed_text}
      </p>
      {!recording && !done && (
        <button className="btn self-start" onClick={start}>
          Start reading
        </button>
      )}
      {recording && (
        <button className="btn self-start" onClick={() => (stopRef.current.current = true)}>
          Done reading
        </button>
      )}
      {done && (
        <button className="btn self-start" onClick={onNext}>
          Continue
        </button>
      )}
    </div>
  );
}

// --- Faza 1: wejście - czytanie ciche + pytania naprowadzające ---------------

function EntryPhase({ pack, onNext }: { pack: SessionPack; onNext: () => void }) {
  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-lg text-neutral-300">Read it through once more</h2>
      <p className="whitespace-pre-wrap rounded border border-neutral-800 p-4 text-neutral-200">
        {pack.seed_text}
      </p>
      <div>
        <h3 className="mb-2 text-sm uppercase tracking-wide text-neutral-500">
          Guiding questions
        </h3>
        <ul className="flex flex-col gap-1 text-neutral-300">
          {pack.guiding_questions.map((q, i) => (
            <li key={i}>- {q}</li>
          ))}
        </ul>
      </div>
      <button className="btn self-start" onClick={onNext}>
        Continue
      </button>
    </div>
  );
}

// --- Faza 2: chunk drill ------------------------------------------------------

function shuffled<T>(arr: T[]): T[] {
  const out = [...arr];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

function ChunkDrillA({
  pack,
  recorder,
  vad,
  onNext,
}: {
  pack: SessionPack;
  recorder: Recorder;
  vad: BrowserVad;
  onNext: () => void;
}) {
  const pool = useMemo(
    () => shuffled([...pack.bank_a_chunks, ...pack.bank_b_chunks]).slice(0, 8),
    [pack]
  );
  const [idx, setIdx] = useState(0);
  const [busy, setBusy] = useState(false);
  const [lastRt, setLastRt] = useState<number | null>(null);

  const current = pool[idx];

  const go = async () => {
    setBusy(true);
    const rtMs = await measureReactionTimeMs(recorder, vad, 3000);
    setLastRt(rtMs);
    api.chunkAccessExposure(pack.session_id, current.id, rtMs).catch(() => {});
    setBusy(false);
  };

  if (pool.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        <p className="text-neutral-400">No chunks to drill this session.</p>
        <button className="btn self-start" onClick={onNext}>
          Continue
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-lg text-neutral-300">Chunk drill - say the phrase ({idx + 1}/{pool.length})</h2>
      <p className="rounded border border-neutral-800 p-6 text-center text-xl text-neutral-100">
        {current.prompt_pl}
      </p>
      {lastRt !== null && !busy && (
        <p className="text-sm text-neutral-500">reaction: {Math.round(lastRt)} ms</p>
      )}
      {!busy && lastRt === null && (
        <button className="btn self-start" onClick={go}>
          Ready
        </button>
      )}
      {busy && <p className="text-neutral-500">listening...</p>}
      {!busy && lastRt !== null && (
        <button
          className="btn self-start"
          onClick={() => {
            setLastRt(null);
            if (idx + 1 < pool.length) setIdx(idx + 1);
            else onNext();
          }}
        >
          {idx + 1 < pool.length ? "Next" : "Continue"}
        </button>
      )}
    </div>
  );
}

function ChunkDrillB({
  pack,
  recorder,
  onNext,
}: {
  pack: SessionPack;
  recorder: Recorder;
  onNext: () => void;
}) {
  const pool = useMemo(() => {
    const base = pack.bank_b_chunks;
    const out: ChunkDto[] = [];
    for (let i = 0; i < 4; i++) out.push(base[i % base.length]);
    return out;
  }, [pack]);
  const [idx, setIdx] = useState(0);
  const [phase, setPhase] = useState<"ready" | "recording" | "uploading" | "done">("ready");
  const stopRef = useRef({ current: false });
  const current = pool[idx];

  const go = async () => {
    setPhase("recording");
    stopRef.current.current = false;
    const samples = await recordUntil(recorder, 12_000, stopRef.current);
    setPhase("uploading");
    try {
      await api.chunkEmbedExposure(pack.session_id, current.id, encodeWav(samples), 0);
    } catch {
      // brak treści do oceny - błąd sieciowy nie blokuje sesji
    }
    setPhase("done");
  };

  if (pool.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        <button className="btn self-start" onClick={onNext}>
          Continue
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-lg text-neutral-300">
        Start with the phrase, then keep talking for 10 seconds ({idx + 1}/{pool.length})
      </h2>
      <p className="rounded border border-neutral-800 p-4 text-neutral-200">
        Use: <span className="text-neutral-100">"{current.text}"</span>
      </p>
      <p className="rounded border border-neutral-800 p-6 text-center text-xl text-neutral-100">
        Why did you skip lunch today?
      </p>
      {phase === "ready" && (
        <button className="btn self-start" onClick={go}>
          Start
        </button>
      )}
      {phase === "recording" && (
        <button className="btn self-start" onClick={() => (stopRef.current.current = true)}>
          Stop
        </button>
      )}
      {phase === "uploading" && <p className="text-neutral-500">processing...</p>}
      {phase === "done" && (
        <button
          className="btn self-start"
          onClick={() => {
            setPhase("ready");
            if (idx + 1 < pool.length) setIdx(idx + 1);
            else onNext();
          }}
        >
          {idx + 1 < pool.length ? "Next" : "Continue"}
        </button>
      )}
    </div>
  );
}

// --- Keyword planning: hasła zamiast pełnego pisania (spec zmian §3) ---------

function KeywordPlanningPhase({
  pack,
  onNext,
}: {
  pack: SessionPack;
  onNext: (items: string[]) => void;
}) {
  const MAX_ITEMS = 3;
  const MAX_WORDS = 5;
  const [items, setItems] = useState<string[]>([""]);
  const [secondsLeft, setSecondsLeft] = useState(pack.keyword_planning_seconds);
  const [rescueMode, setRescueMode] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (secondsLeft <= 0 || rescueMode) return;
    const id = setInterval(() => setSecondsLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(id);
  }, [secondsLeft, rescueMode]);

  const submit = async () => {
    const cleaned = items.map((i) => i.trim()).filter(Boolean);
    if (cleaned.length === 0) return;
    setSubmitting(true);
    try {
      await api.submitKeywordPlan(pack.session_id, cleaned);
    } catch {
      // brak planu nie powinien blokować sesji
    }
    onNext(cleaned);
  };

  if (rescueMode) {
    return (
      <WritingRehearsalPhase
        pack={pack}
        onNext={() => onNext([])}
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-lg text-neutral-300">
        Jot down up to {MAX_ITEMS} short points{secondsLeft > 0 ? ` - ${secondsLeft}s` : ""}
      </h2>
      <p className="text-sm text-neutral-500">
        Max {MAX_WORDS} words per point. No sentences - just what you want to touch on.
      </p>
      <div className="flex flex-col gap-2">
        {items.map((val, i) => (
          <input
            key={i}
            className="rounded border border-neutral-800 bg-neutral-950 px-4 py-2 text-neutral-100"
            placeholder={`Point ${i + 1}`}
            value={val}
            disabled={submitting}
            onChange={(e) => {
              const words = e.target.value.split(/\s+/).filter(Boolean);
              const next = words.length > MAX_WORDS ? words.slice(0, MAX_WORDS).join(" ") : e.target.value;
              setItems((prev) => prev.map((p, idx) => (idx === i ? next : p)));
            }}
          />
        ))}
      </div>
      {items.length < MAX_ITEMS && (
        <button
          className="self-start text-sm text-neutral-500 underline"
          onClick={() => setItems((prev) => [...prev, ""])}
        >
          + add a point
        </button>
      )}
      <div className="flex items-center gap-4">
        <button className="btn self-start" disabled={submitting} onClick={submit}>
          Continue to speaking
        </button>
        {pack.writing_phase_active && (
          <button
            className="text-sm text-neutral-500 underline"
            onClick={() => setRescueMode(true)}
          >
            Need more time? Write it out first
          </button>
        )}
      </div>
    </div>
  );
}

// --- Faza -1 (rescue mode): write-before-speak, dostępne tylko na życzenie ---

function WritingRehearsalPhase({ pack, onNext }: { pack: SessionPack; onNext: () => void }) {
  const [text, setText] = useState("");
  const [secondsLeft, setSecondsLeft] = useState(240);
  const [submitted, setSubmitted] = useState(false);
  const startedAt = useRef(performance.now());

  useEffect(() => {
    const id = setInterval(() => setSecondsLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(id);
  }, []);

  const submit = async () => {
    const durationS = (performance.now() - startedAt.current) / 1000;
    await api.submitWritingRehearsal(pack.session_id, text, durationS).catch(() => {});
    setSubmitted(true);
  };

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-lg text-neutral-300">
        Write about it first - {Math.floor(secondsLeft / 60)}:{String(secondsLeft % 60).padStart(2, "0")}
      </h2>
      <p className="text-sm text-neutral-500">
        No correction, no scoring - just get the content out in writing before you speak it.
      </p>
      <textarea
        className="min-h-[200px] rounded border border-neutral-800 bg-neutral-950 px-4 py-3 text-neutral-100"
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={submitted}
      />
      {!submitted ? (
        <button className="btn self-start" onClick={submit}>
          Done writing
        </button>
      ) : (
        <button className="btn self-start" onClick={onNext}>
          Continue to speaking
        </button>
      )}
    </div>
  );
}

// --- Faza 3: blok główny (rundy) ----------------------------------------------

function RoundPhase({
  pack,
  roundNumber,
  keywordPlan,
  recorder,
  onNext,
}: {
  pack: SessionPack;
  roundNumber: number;
  keywordPlan: string[];
  recorder: Recorder;
  onNext: () => void;
}) {
  const round = pack.rounds.find((r) => r.number === roundNumber)!;
  // spec zmian §5.3: maks. 1-2 "dostępne narzędzia" na niskim wsparciu, nigdy
  // wymagane - wybór losowy, stabilny w obrębie tej rundy (nie przy re-renderze)
  const suggestedTools = useMemo(() => {
    const pool = [...pack.bank_a_chunks, ...pack.bank_b_chunks];
    return shuffled(pool).slice(0, 2);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pack.session_id, roundNumber]);
  const [phase, setPhase] = useState<"prep" | "speaking" | "processing" | "done">(
    round.prep_s > 0 ? "prep" : "speaking"
  );
  const [remaining, setRemaining] = useState(round.prep_s > 0 ? round.prep_s : round.speak_limit_s);
  const stopRef = useRef({ current: false });
  const startedSpeaking = useRef(false);

  useEffect(() => {
    if (phase !== "prep" && phase !== "speaking") return;
    const id = setInterval(() => setRemaining((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(id);
  }, [phase]);

  useEffect(() => {
    if (phase === "prep" && remaining <= 0) {
      setPhase("speaking");
      setRemaining(round.speak_limit_s);
    }
    if (phase === "speaking" && remaining <= 0) {
      stopRef.current.current = true;
    }
  }, [phase, remaining, round.speak_limit_s]);

  useEffect(() => {
    if (phase !== "speaking" || startedSpeaking.current) return;
    startedSpeaking.current = true;
    (async () => {
      const samples = await recordUntil(recorder, round.speak_limit_s * 1000 + 500, stopRef.current);
      setPhase("processing");
      const res = await api.submitRoundAttempt(pack.session_id, roundNumber, encodeWav(samples), 0);
      await pollAttempt(res.attempt_id);
      setPhase("done");
    })();
  }, [phase, recorder, round.speak_limit_s, pack.session_id, roundNumber]);

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-lg text-neutral-300">
        Round {roundNumber} / 4 - {SUPPORT_LABEL[round.support_level]}
      </h2>
      <p className="text-sm text-neutral-500">{ROUND_INSTRUCTION[roundNumber]}</p>

      {keywordPlan.length > 0 && (
        <p className="text-sm text-neutral-400">Your plan: {keywordPlan.join(" · ")}</p>
      )}

      {round.support_level <= 2 && suggestedTools.length > 0 && (
        <p className="text-sm text-neutral-500">
          Available tools: {suggestedTools.map((c) => `"${c.text}"`).join("  ·  ")}
        </p>
      )}

      {round.support_level >= 4 && (
        <p className="whitespace-pre-wrap rounded border border-neutral-800 p-4 text-neutral-200">
          {pack.seed_text}
        </p>
      )}
      {round.support_level >= 3 && (
        <ul className="flex flex-col gap-1 text-neutral-300">
          {pack.guiding_questions.map((q, i) => (
            <li key={i}>- {q}</li>
          ))}
        </ul>
      )}
      {round.support_level >= 2 && (
        <p className="text-neutral-400">{pack.keywords.join(" · ")}</p>
      )}
      {round.support_level <= 1 && (
        <p className="text-neutral-400">Topic: {pack.domain}</p>
      )}

      {phase === "prep" && (
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

// --- Faza 4: sonda transferowa -------------------------------------------------

function TransferPhase({
  pack,
  probeType,
  isLast,
  recorder,
  onNext,
}: {
  pack: SessionPack;
  probeType: TransferProbeType;
  isLast: boolean;
  recorder: Recorder;
  onNext: () => void;
}) {
  const [phase, setPhase] = useState<"ready" | "speaking" | "processing" | "done">("ready");
  const [remaining, setRemaining] = useState(120);
  const stopRef = useRef({ current: false });
  const prompt = probeType === "near" ? pack.near_transfer_prompt : pack.far_transfer_prompt;

  useEffect(() => {
    if (phase !== "speaking") return;
    const id = setInterval(() => setRemaining((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(id);
  }, [phase]);

  useEffect(() => {
    if (phase === "speaking" && remaining <= 0) stopRef.current.current = true;
  }, [phase, remaining]);

  const start = async () => {
    setPhase("speaking");
    stopRef.current.current = false;
    const samples = await recordUntil(recorder, 120_500, stopRef.current);
    setPhase("processing");
    const res = await api.submitTransferProbe(pack.session_id, probeType, encodeWav(samples), 0);
    await pollAttempt(res.attempt_id);
    setPhase("done");
  };

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-lg text-neutral-300">
        {probeType === "near" ? "Same topic, no prep, no support" : "Different topic, no prep, no support"}
      </h2>
      <p className="rounded border border-neutral-800 p-6 text-center text-xl text-neutral-100">
        {prompt}
      </p>
      {phase === "ready" && (
        <button className="btn self-start" onClick={start}>
          Start speaking
        </button>
      )}
      {phase === "speaking" && (
        <>
          <p className="text-2xl text-neutral-100">{remaining}s left</p>
          <button className="btn self-start" onClick={() => (stopRef.current.current = true)}>
            Stop
          </button>
        </>
      )}
      {phase === "processing" && <p className="text-neutral-500">processing...</p>}
      {phase === "done" && (
        <button className="btn self-start" onClick={onNext}>
          {isLast ? "Finish session" : "Continue"}
        </button>
      )}
    </div>
  );
}
