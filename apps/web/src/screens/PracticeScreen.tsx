import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  EntryFormat,
  GrammarAnswerDto,
  GrammarHome,
  RoundEntry,
  RoundSummary,
  Verdict,
} from "../api/client";
import { captureAnswer, CaptureControl, loadVad } from "../audio/capture";
import { chimeCorrect, chimeLevelUp, chimeSoft } from "../audio/chime";
import { Recorder } from "../audio/recorder";
import { BrowserVad } from "../audio/vad";
import { encodeWav } from "../audio/wav";

interface Props {
  onDone: () => void;
  onShadow: () => void;
}

// czas na odpowiedź: hojny, bo zegar ma tylko domykać nagranie, nie poganiać
const MAX_MS: Record<EntryFormat, number> = {
  guided: 30_000,
  situation: 25_000,
  translate: 25_000,
  fix: 25_000,
  own: 25_000,
  personal: 45_000,
};

const FORMAT_LABEL: Record<EntryFormat, string> = {
  guided: "Finish the sentence",
  situation: "Say what you'd really say",
  translate: "Jak to powiedzieć po angielsku?",
  fix: "Say it right",
  personal: "About you",
  own: "From your own conversation - say what you meant",
};

const LEVEL_UP_TEXT: Record<number, string> = {
  2: "You can do this one without help now.",
  3: "Solid. It comes back in a few days to check that it stuck.",
  4: "Mastered. It survived every break.",
};

type Phase =
  | { name: "loading" }
  | { name: "preparing" }
  | { name: "recording" }
  | { name: "checking" }
  | { name: "feedback"; answer: GrammarAnswerDto }
  | { name: "sayAgain"; answer: GrammarAnswerDto }
  | { name: "finishing" }
  | { name: "summary"; summary: RoundSummary; home: GrammarHome };

type Mark = Verdict | "pending";

export default function PracticeScreen({ onDone, onShadow }: Props) {
  const [phase, setPhase] = useState<Phase>({ name: "loading" });
  const [entries, setEntries] = useState<RoundEntry[]>([]);
  const [pos, setPos] = useState(0);
  const [marks, setMarks] = useState<Record<number, Mark>>({});
  const [error, setError] = useState<string | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [level, setLevel] = useState(0);
  const [speaking, setSpeaking] = useState(false);
  const [hintShown, setHintShown] = useState(false);
  const [roundKey, setRoundKey] = useState(0);

  const recorderRef = useRef<Recorder | null>(null);
  const vadRef = useRef<BrowserVad | null>(null);
  const roundIdRef = useRef(0);
  const controlRef = useRef<CaptureControl>({ stop: false, cancel: false });
  const skipRef = useRef(false);
  const hintRef = useRef(false);
  const extraAskedRef = useRef<Set<string>>(new Set());
  const aliveRef = useRef(true);

  const entry = entries[pos];

  // --- start rundy -----------------------------------------------------------

  useEffect(() => {
    aliveRef.current = true;
    let timer: number | undefined;
    setPhase({ name: "loading" });
    setEntries([]);
    setPos(0);
    setMarks({});
    extraAskedRef.current = new Set();

    const begin = async () => {
      try {
        if (!recorderRef.current) {
          const [recorder, vad] = await Promise.all([Recorder.create({ autoGain: true }), loadVad()]);
          recorderRef.current = recorder;
          vadRef.current = vad;
        }
        const round = await api.createRound();
        if (!aliveRef.current) return;
        if (round === null) {
          // bank zadań dopiero powstaje - serwer generuje w tle, pytamy ponownie
          setPhase({ name: "preparing" });
          timer = window.setTimeout(begin, 5000);
          return;
        }
        roundIdRef.current = round.round_id;
        setEntries(round.entries);
        setPhase({ name: "recording" });
      } catch (e) {
        if (aliveRef.current) setError(e instanceof Error ? e.message : String(e));
      }
    };
    void begin();

    return () => {
      aliveRef.current = false;
      controlRef.current.cancel = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [roundKey]);

  useEffect(
    () => () => {
      void recorderRef.current?.destroy();
      recorderRef.current = null;
    },
    []
  );

  // --- nagranie i ocena jednego zadania ------------------------------------------

  const [attempt, setAttempt] = useState(0); // zwiększane przy "spróbuj jeszcze raz"

  useEffect(() => {
    if (phase.name !== "recording" || !entry || !recorderRef.current) return;
    const recorder = recorderRef.current;
    const control: CaptureControl = { stop: false, cancel: false };
    controlRef.current = control;
    skipRef.current = false;
    hintRef.current = false;
    setHintShown(false);

    (async () => {
      try {
        const { samples } = await captureAnswer(recorder, vadRef.current, MAX_MS[entry.fmt], control, (t) => {
          setSecondsLeft(t.secondsLeft);
          setLevel(t.level);
          setSpeaking(t.speaking);
        });
        if (control.cancel || !aliveRef.current) return;

        let answer: GrammarAnswerDto;
        if (skipRef.current) {
          answer = await api.skipRoundEntry(roundIdRef.current, entry.index);
        } else if (samples.length < 16000 * 0.3) {
          // nagranie krótsze niż 0,3 s (np. "Done" od razu) - nie ma czego wysyłać
          answer = silentAnswer(entry);
        } else {
          // czy była mowa, rozstrzyga serwer (VAD); przeglądarka nigdy nie odrzuca odpowiedzi
          setPhase({ name: "checking" });
          const { answer_id } = await api.submitRoundAnswer(
            roundIdRef.current,
            entry.index,
            encodeWav(samples),
            hintRef.current
          );
          answer = await pollAnswer(answer_id);
        }
        if (!aliveRef.current) return;
        onGraded(entry, answer);
      } catch (e) {
        if (aliveRef.current) setError(e instanceof Error ? e.message : String(e));
      }
    })();

    return () => {
      control.cancel = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase.name === "recording", entry?.index, attempt]);

  const onGraded = (e: RoundEntry, answer: GrammarAnswerDto) => {
    const verdict: Mark = answer.status === "error" ? "unclear" : answer.verdict ?? "unclear";
    setMarks((m) => ({ ...m, [e.index]: verdict }));
    const levelUp =
      answer.level_before !== null &&
      answer.level_after !== null &&
      answer.level_after > answer.level_before &&
      answer.level_after >= 2;
    if (levelUp) chimeLevelUp();
    else if (verdict === "correct") chimeCorrect();
    else if (verdict !== "unclear") chimeSoft();

    // błąd wraca w tej samej rundzie jako inna sytuacja (raz na umiejętność)
    if ((verdict === "incorrect" || verdict === "avoided") && !extraAskedRef.current.has(e.skill_id)) {
      extraAskedRef.current.add(e.skill_id);
      api
        .extraRoundEntry(roundIdRef.current, e.skill_id)
        .then((r) => {
          if (r.entry && aliveRef.current) setEntries((list) => [...list, r.entry!]);
        })
        .catch(() => {});
    }
    setPhase({ name: "feedback", answer });
  };

  const finish = useCallback(async () => {
    controlRef.current.cancel = true;
    setPhase({ name: "finishing" });
    try {
      const res = await api.endRound(roundIdRef.current);
      if (aliveRef.current) setPhase({ name: "summary", summary: res.summary, home: res.home });
    } catch (e) {
      if (aliveRef.current) setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const next = useCallback(() => {
    if (pos + 1 < entries.length) {
      setPos(pos + 1);
      setPhase({ name: "recording" });
    } else {
      void finish();
    }
  }, [pos, entries.length, finish]);

  // efekty z nagrywaniem żyją dłużej niż jeden render, a lista zadań może w tym
  // czasie urosnąć o powrót błędnego zadania - stąd zawsze aktualna wersja w refie
  const nextRef = useRef(next);
  nextRef.current = next;

  const retrySame = () => {
    setAttempt((n) => n + 1);
    setPhase({ name: "recording" });
  };

  // "powiedz jeszcze raz": poprawna wersja ma przejść przez usta; nic nie wysyłamy
  useEffect(() => {
    if (phase.name !== "sayAgain" || !recorderRef.current) return;
    const control: CaptureControl = { stop: false, cancel: false };
    controlRef.current = control;
    captureAnswer(recorderRef.current, vadRef.current, 15_000, control, (t) => {
      setLevel(t.level);
      setSpeaking(t.speaking);
    }).then(() => {
      if (!control.cancel && aliveRef.current) nextRef.current();
    });
    return () => {
      control.cancel = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase.name === "sayAgain"]);

  // --- klawiatura: spacja / Enter = główna akcja -----------------------------------

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key !== " " && ev.key !== "Enter") return;
      if (ev.target instanceof HTMLButtonElement) return; // przycisk obsłuży to sam
      if (phase.name === "recording" || phase.name === "sayAgain") {
        ev.preventDefault();
        controlRef.current.stop = true;
      } else if (phase.name === "feedback") {
        ev.preventDefault();
        const v = phase.answer.verdict;
        if (v === "incorrect" || v === "avoided") setPhase({ name: "sayAgain", answer: phase.answer });
        else if (v === "correct") next();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase, next]);

  // --- widoki ---------------------------------------------------------------------

  if (error) {
    return (
      <Centered>
        <p className="max-w-lg text-center text-red-400">{error}</p>
        <button className="btn" onClick={onDone}>
          Back
        </button>
      </Centered>
    );
  }

  if (phase.name === "loading" || phase.name === "finishing") {
    return (
      <Centered>
        <p className="text-neutral-500">{phase.name === "loading" ? "Getting your round ready..." : "Wrapping up..."}</p>
      </Centered>
    );
  }

  if (phase.name === "preparing") {
    return (
      <Centered>
        <p className="text-lg text-neutral-300">Writing your first exercises...</p>
        <p className="max-w-md text-center text-sm text-neutral-500">
          This happens once and takes about a minute. The round starts by itself.
        </p>
        <button className="link" onClick={onDone}>
          back
        </button>
      </Centered>
    );
  }

  if (phase.name === "summary") {
    return (
      <Summary
        summary={phase.summary}
        home={phase.home}
        onAgain={() => setRoundKey((k) => k + 1)}
        onShadow={onShadow}
        onDone={onDone}
      />
    );
  }

  if (!entry) return null;

  return (
    <div className="mx-auto flex min-h-screen max-w-2xl flex-col gap-8 p-6 sm:p-10">
      <div className="flex items-center justify-between gap-4">
        <div className="flex flex-wrap gap-1.5">
          {entries.map((e, i) => (
            <span key={e.index} className={`h-2.5 w-7 rounded-full ${dotClass(marks[e.index], i === pos)}`} />
          ))}
        </div>
        <button className="link shrink-0" onClick={() => void finish()}>
          end round
        </button>
      </div>

      <div key={`${entry.index}-${attempt}`} className="pop-in flex flex-col gap-5">
        <p className="eyebrow">
          {FORMAT_LABEL[entry.fmt]}
          {entry.kind === "review" && <span className="ml-2 text-sky-400">· back after a break</span>}
          {entry.kind === "extra" && <span className="ml-2 text-amber-400">· one more of that kind</span>}
        </p>

        {entry.fmt === "own" ? (
          <div className="card">
            <p className="text-sm text-neutral-500">You said:</p>
            <p className="mt-1 text-2xl leading-snug text-neutral-100">&ldquo;{entry.prompt}&rdquo;</p>
          </div>
        ) : (
          <p className="card text-2xl leading-snug text-neutral-100">{entry.prompt}</p>
        )}

        {entry.show_pattern && (
          <p className="text-neutral-400">
            Shape: <span className="font-mono text-amber-300">{entry.pattern}</span>
          </p>
        )}
        {entry.cue && <p className="text-2xl font-medium text-amber-300">{entry.cue}</p>}
      </div>

      {phase.name === "recording" && (
        <div className="flex flex-col gap-5">
          <div className="flex items-center gap-4">
            <MicMeter level={level} speaking={speaking} />
            <span className="text-sm text-neutral-500">
              {speaking ? "hearing you" : "listening"} · {secondsLeft}s
            </span>
          </div>
          {entry.hint &&
            (hintShown ? (
              <p className="text-neutral-400">Hint: {entry.hint}</p>
            ) : (
              <button
                className="link self-start"
                onClick={() => {
                  hintRef.current = true;
                  setHintShown(true);
                }}
              >
                show a hint
              </button>
            ))}
          <div className="flex items-center gap-6">
            <button className="btn" onClick={() => (controlRef.current.stop = true)}>
              Done
            </button>
            <button
              className="link"
              onClick={() => {
                skipRef.current = true;
                controlRef.current.stop = true;
              }}
            >
              I don't know - show me
            </button>
          </div>
          <p className="text-xs text-neutral-600">Just answer out loud. It stops when you stop talking.</p>
        </div>
      )}

      {phase.name === "checking" && <p className="text-neutral-500">Checking...</p>}

      {(phase.name === "feedback" || phase.name === "sayAgain") && (
        <Feedback
          entry={entry}
          answer={phase.answer}
          sayingAgain={phase.name === "sayAgain"}
          level={level}
          isLast={pos + 1 >= entries.length}
          onNext={next}
          onSayAgain={() => setPhase({ name: "sayAgain", answer: phase.answer })}
          onStopSayAgain={() => (controlRef.current.stop = true)}
          onRetry={retrySame}
        />
      )}
    </div>
  );
}

// --- pomocnicze -------------------------------------------------------------------

function silentAnswer(entry: RoundEntry): GrammarAnswerDto {
  return {
    answer_id: 0,
    status: "done",
    transcript: null,
    latency_ms: null,
    verdict: "unclear",
    error_type: null,
    explanation: null,
    note_pl: null,
    corrected: null,
    reaction: null,
    skill_id: entry.skill_id,
    skill_label: entry.meaning,
    level_before: null,
    level_after: null,
  };
}

async function pollAnswer(answerId: number): Promise<GrammarAnswerDto> {
  for (let i = 0; i < 150; i++) {
    const a = await api.getRoundAnswer(answerId);
    if (a.status !== "processing") return a;
    await new Promise((r) => setTimeout(r, 350));
  }
  throw new Error("Checking took too long. Your answer is saved - try the next one.");
}

function dotClass(mark: Mark | undefined, current: boolean): string {
  if (mark === "correct") return "bg-emerald-400";
  if (mark === "incorrect" || mark === "avoided") return "bg-amber-400";
  if (mark === "unclear") return "bg-neutral-600";
  return current ? "bg-neutral-300" : "bg-neutral-800";
}

function Centered({ children }: { children: React.ReactNode }) {
  return <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-8">{children}</div>;
}

function MicMeter({ level, speaking = false }: { level: number; speaking?: boolean }) {
  return (
    <div className="flex h-10 items-center gap-1" aria-hidden>
      {[0.15, 0.3, 0.45, 0.6, 0.75].map((threshold, i) => (
        <span
          key={i}
          className={`w-1.5 rounded-full transition-all duration-75 ${
            level > threshold ? (speaking ? "bg-emerald-400" : "bg-neutral-400") : "bg-neutral-700"
          }`}
          style={{ height: `${10 + i * 6 + (level > threshold ? 6 : 0)}px` }}
        />
      ))}
    </div>
  );
}

function Feedback({
  entry,
  answer,
  sayingAgain,
  level,
  isLast,
  onNext,
  onSayAgain,
  onStopSayAgain,
  onRetry,
}: {
  entry: RoundEntry;
  answer: GrammarAnswerDto;
  sayingAgain: boolean;
  level: number;
  isLast: boolean;
  onNext: () => void;
  onSayAgain: () => void;
  onStopSayAgain: () => void;
  onRetry: () => void;
}) {
  const verdict = answer.status === "error" ? "unclear" : answer.verdict ?? "unclear";
  const nextLabel = isLast ? "Finish" : "Next";
  const levelUp =
    answer.level_before !== null &&
    answer.level_after !== null &&
    answer.level_after > answer.level_before &&
    LEVEL_UP_TEXT[answer.level_after];

  const shape = (
    <p className="text-sm text-neutral-400">
      {entry.meaning} → <span className="font-mono text-amber-300">{entry.pattern}</span>
    </p>
  );

  if (verdict === "unclear") {
    return (
      <div className="pop-in flex flex-col gap-4">
        <p className="text-xl text-neutral-300">
          {answer.transcript ? "I couldn't make that out." : "I didn't hear anything in that recording."}
        </p>
        {answer.transcript ? (
          <p className="text-neutral-500">Heard: {answer.transcript}</p>
        ) : (
          <p className="text-sm text-neutral-500">
            If this keeps happening, check which microphone the browser uses (the icon in the address bar) and
            that nothing else is holding it.
          </p>
        )}
        <div className="flex items-center gap-6">
          <button className="btn-primary" onClick={onRetry} autoFocus>
            Try again
          </button>
          <button className="link" onClick={onNext}>
            skip this one
          </button>
        </div>
      </div>
    );
  }

  if (verdict === "correct") {
    return (
      <div className="pop-in flex flex-col gap-4">
        <div className="rounded-2xl border border-emerald-500/40 bg-emerald-500/10 p-5">
          <p className="text-sm font-medium text-emerald-300">
            ✓ Right
            {answer.latency_ms !== null && (
              <span className="ml-2 font-normal text-emerald-300/70">
                · you started after {(answer.latency_ms / 1000).toFixed(1)} s
              </span>
            )}
          </p>
          <p className="mt-2 text-xl text-neutral-100">{answer.transcript}</p>
          {answer.reaction && <p className="mt-2 text-neutral-400">{answer.reaction}</p>}
        </div>
        {shape}
        {levelUp && <p className="text-emerald-300">▲ {levelUp}</p>}
        <button className="btn-primary self-start" onClick={onNext} autoFocus>
          {nextLabel}
        </button>
      </div>
    );
  }

  const better = answer.corrected || entry.model_answer;
  return (
    <div className="pop-in flex flex-col gap-4">
      <div className="rounded-2xl border border-amber-500/40 bg-amber-500/10 p-5">
        <p className="text-sm font-medium text-amber-300">
          {verdict === "avoided" ? "Fine sentence, but it dodged the shape we're practising" : "Almost"}
        </p>
        {answer.transcript && <p className="mt-2 text-neutral-400">You said: {answer.transcript}</p>}
        <p className="mt-3 text-2xl leading-snug text-neutral-50">{better}</p>
      </div>
      {answer.explanation && <p className="text-neutral-300">{answer.explanation}</p>}
      {answer.note_pl && <p className="text-neutral-400"><span className="mr-2 rounded border border-neutral-700 px-1.5 py-0.5 text-[10px] font-semibold tracking-wider text-neutral-400">PL</span>
          {answer.note_pl}</p>}
      {shape}
      {sayingAgain ? (
        <div className="flex items-center gap-4">
          <MicMeter level={level} />
          <span className="text-neutral-300">Say it out loud.</span>
          <button className="btn" onClick={onStopSayAgain}>
            {nextLabel}
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-6">
          <button className="btn-primary" onClick={onSayAgain} autoFocus>
            Say it right
          </button>
          <button className="link" onClick={onNext}>
            {isLast ? "finish" : "next"}
          </button>
        </div>
      )}
    </div>
  );
}

function Summary({
  summary,
  home,
  onAgain,
  onShadow,
  onDone,
}: {
  summary: RoundSummary;
  home: GrammarHome;
  onAgain: () => void;
  onShadow: () => void;
  onDone: () => void;
}) {
  const ups = summary.moved.filter((m) => m.up);
  const learning = summary.moved.filter((m) => !m.up && m.to === 1);
  const mastered = home.counts.mastered + home.counts.solid;
  return (
    <div className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-8 p-6 sm:p-10">
      <div className="pop-in">
        <p className="eyebrow">Round done</p>
        {summary.graded > 0 ? (
          <p className="mt-2 text-6xl font-semibold text-neutral-50">
            {summary.correct}
            <span className="text-neutral-600"> / {summary.graded}</span>
          </p>
        ) : (
          <p className="mt-2 text-2xl text-neutral-300">Nothing answered this time. That's fine.</p>
        )}
        {summary.median_latency_ms !== null && (
          <p className="mt-2 text-neutral-500">
            You typically started answering after {(summary.median_latency_ms / 1000).toFixed(1)} s.
          </p>
        )}
      </div>

      {ups.length > 0 && (
        <div className="flex flex-col gap-2">
          <p className="eyebrow text-emerald-400">Moved up</p>
          {ups.map((m) => (
            <p key={m.skill_id} className="text-neutral-200">
              ▲ {m.label}
            </p>
          ))}
        </div>
      )}

      {learning.length > 0 && (
        <div className="flex flex-col gap-2">
          <p className="eyebrow text-amber-400">Found something to work on</p>
          {learning.map((m) => (
            <p key={m.skill_id} className="text-neutral-300">
              {m.label}
            </p>
          ))}
          <p className="text-sm text-neutral-500">Next rounds start these with the sentence shape visible.</p>
        </div>
      )}

      {learning.length === 0 && summary.to_revisit.length > 0 && (
        <div className="flex flex-col gap-2">
          <p className="eyebrow">Coming back next round</p>
          {summary.to_revisit.map((m) => (
            <p key={m.skill_id} className="text-neutral-300">
              {m.label}
            </p>
          ))}
        </div>
      )}

      <p className="text-sm text-neutral-500">
        Map: {mastered} of {home.total_skills} solid or mastered · {home.counts.unaided} unaided ·{" "}
        {home.counts.learning} learning · this week {home.week_days_done} of {home.weekly_goal} days
      </p>

      <div className="flex flex-wrap items-center gap-5">
        <button className="btn-primary" onClick={onAgain} autoFocus>
          One more round
        </button>
        <button className="btn" onClick={onShadow}>
          Shadowing
        </button>
        <button className="link" onClick={onDone}>
          done for today
        </button>
      </div>
    </div>
  );
}
