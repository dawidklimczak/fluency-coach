import { useCallback, useEffect, useRef, useState } from "react";
import { api, ShadowAttemptDto, ShadowPassage } from "../api/client";
import { playSamples } from "../audio/chime";
import { Recorder } from "../audio/recorder";
import { encodeWav, SAMPLE_RATE } from "../audio/wav";

interface Props {
  onBack: () => void;
  onPractice: () => void;
}

type Mode = "idle" | "listening" | "shadowing" | "analysing" | "looping" | "comparing";

const SPEEDS = [0.85, 1.0, 1.15];
const TAIL_MS = 900; // tyle nagrywamy po końcu wzorca - mówiący jest zawsze trochę z tyłu
const LOOP_REPEATS = 3;

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

export default function ShadowScreen({ onBack, onPractice }: Props) {
  const [passage, setPassage] = useState<ShadowPassage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("idle");
  const [speed, setSpeed] = useState(1.0);
  const [hideText, setHideText] = useState(false);
  const [wordIndex, setWordIndex] = useState(-1);
  const [result, setResult] = useState<ShadowAttemptDto | null>(null);
  const [steps, setSteps] = useState({ listened: false, withText: false, blind: false });
  const [loopInfo, setLoopInfo] = useState<string | null>(null);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const recorderRef = useRef<Recorder | null>(null);
  const samplesRef = useRef<Float32Array | null>(null);
  const runRef = useRef(0); // każda akcja dostaje numer; zmiana numeru przerywa poprzednią
  const aliveRef = useRef(true);

  const load = useCallback(async (excludeId?: number) => {
    setPassage(null);
    setResult(null);
    setError(null);
    setSteps({ listened: false, withText: false, blind: false });
    samplesRef.current = null;
    try {
      const p = await api.shadowNext(excludeId);
      if (!aliveRef.current) return;
      const audio = new Audio(p.audio_url);
      audio.preload = "auto";
      audioRef.current = audio;
      setPassage(p);
    } catch (e) {
      if (aliveRef.current) setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    aliveRef.current = true;
    void load();
    return () => {
      aliveRef.current = false;
      runRef.current++;
      audioRef.current?.pause();
      void recorderRef.current?.destroy();
      recorderRef.current = null;
    };
  }, [load]);

  /** Odtwarza wzorzec od `from` do `to` (sekundy nagrania) i podświetla bieżące słowo. */
  const playRange = useCallback(
    (run: number, rate: number, from = 0, to?: number, onStarted?: () => void): Promise<void> => {
      const audio = audioRef.current;
      if (!audio || !passage) return Promise.resolve();
      audio.pause();
      audio.playbackRate = rate;
      audio.currentTime = Math.max(0, from);
      return new Promise((resolve) => {
        let started = false;
        const tick = () => {
          if (runRef.current !== run) {
            audio.pause();
            resolve();
            return;
          }
          const t = audio.currentTime;
          if (!started && !audio.paused && t > from) {
            started = true;
            onStarted?.();
          }
          const idx = passage.words.findIndex((w) => t >= w.start && t < w.end);
          if (idx >= 0) setWordIndex(idx);
          if (audio.ended || (to !== undefined && t >= to)) {
            audio.pause();
            resolve();
            return;
          }
          requestAnimationFrame(tick);
        };
        audio.play().then(() => requestAnimationFrame(tick), () => resolve());
      });
    },
    [passage]
  );

  const stop = () => {
    runRef.current++;
    audioRef.current?.pause();
    if (mode === "shadowing") recorderRef.current?.stop();
    setMode("idle");
    setWordIndex(-1);
    setLoopInfo(null);
  };

  const listen = async () => {
    const run = ++runRef.current;
    setMode("listening");
    setHideText(false);
    await playRange(run, speed);
    if (runRef.current !== run) return;
    setSteps((s) => ({ ...s, listened: true }));
    setMode("idle");
    setWordIndex(-1);
  };

  const shadow = async (blind: boolean) => {
    if (!passage) return;
    const run = ++runRef.current;
    try {
      if (!recorderRef.current) recorderRef.current = await Recorder.create({ autoGain: true });
      const recorder = recorderRef.current;
      setResult(null);
      setHideText(blind);
      setMode("shadowing");
      await recorder.start();
      let offsetS = 0;
      await playRange(run, speed, 0, undefined, () => {
        // moment, w którym wzorzec faktycznie ruszył, w zegarze nagrania
        offsetS = recorder.samplesRecorded / SAMPLE_RATE;
      });
      if (runRef.current !== run) return;
      await sleep(TAIL_MS);
      if (runRef.current !== run) return;
      const samples = recorder.stop();
      samplesRef.current = samples;
      setMode("analysing");
      setWordIndex(-1);
      const { attempt_id } = await api.submitShadowAttempt(passage.passage_id, encodeWav(samples), {
        with_text: !blind,
        speed,
        offset_s: offsetS,
      });
      for (let i = 0; i < 120; i++) {
        const res = await api.getShadowAttempt(attempt_id);
        if (runRef.current !== run) return;
        if (res.status !== "processing") {
          if (res.status === "error") throw new Error("The analysis failed. Try once more.");
          setResult(res);
          break;
        }
        await sleep(500);
      }
      setSteps((s) => (blind ? { ...s, blind: true } : { ...s, withText: true }));
      setHideText(false);
      setMode("idle");
    } catch (e) {
      if (runRef.current === run) {
        setError(e instanceof Error ? e.message : String(e));
        setMode("idle");
      }
    }
  };

  const loopSentence = async (index: number, rate: number) => {
    const s = passage?.sentences.find((x) => x.index === index);
    if (!s) return;
    const run = ++runRef.current;
    setMode("looping");
    setHideText(false);
    for (let i = 0; i < LOOP_REPEATS; i++) {
      setLoopInfo(`${i + 1} / ${LOOP_REPEATS} · ${rate === 1 ? "full speed" : `${rate}×`}`);
      await playRange(run, rate, s.start - 0.12, s.end + 0.18);
      if (runRef.current !== run) return;
      await sleep(700);
      if (runRef.current !== run) return;
    }
    setLoopInfo(null);
    setMode("idle");
    setWordIndex(-1);
  };

  const compare = async (index: number) => {
    const s = passage?.sentences.find((x) => x.index === index);
    const mine = result?.metrics?.sentences.find((x) => x.index === index);
    const samples = samplesRef.current;
    if (!s || !mine || !samples || mine.user_start === null || mine.user_end === null) return;
    const run = ++runRef.current;
    setMode("comparing");
    setLoopInfo("the speaker");
    await playRange(run, 1.0, s.start - 0.12, s.end + 0.18);
    if (runRef.current !== run) return;
    await sleep(350);
    setLoopInfo("you");
    setWordIndex(-1);
    await playSamples(samples, mine.user_start - 0.25, mine.user_end + 0.35);
    if (runRef.current !== run) return;
    setLoopInfo(null);
    setMode("idle");
  };

  // --- widoki --------------------------------------------------------------------

  if (error && !passage) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-8">
        <p className="max-w-lg text-center text-red-400">{error}</p>
        <div className="flex gap-4">
          <button className="btn" onClick={() => void load()}>
            Try again
          </button>
          <button className="btn" onClick={onBack}>
            Back
          </button>
        </div>
      </div>
    );
  }

  if (!passage) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 p-8">
        <p className="text-lg text-neutral-300">Getting a passage ready...</p>
        <p className="max-w-md text-center text-sm text-neutral-500">
          A new one is written and recorded when none is waiting. That can take up to a minute.
        </p>
        <button className="link" onClick={onBack}>
          back
        </button>
      </div>
    );
  }

  const busy = mode !== "idle";
  const metrics = result?.metrics ?? null;
  const hardest = metrics?.hardest_sentence ?? null;
  const statusOf = (i: number) => result?.words?.[i]?.status;
  const nextStep = !steps.listened ? "listen" : !steps.withText ? "withText" : "blind";
  const stepClass = (name: string) => (nextStep === name && !busy ? "btn-primary !px-5 !py-3 !text-lg" : "btn");
  const canCompare =
    hardest !== null && metrics?.sentences.find((s) => s.index === hardest)?.user_start != null;

  return (
    <div className="mx-auto flex min-h-screen max-w-2xl flex-col gap-7 p-6 sm:p-10">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="eyebrow">Shadowing · headphones on</p>
          <h1 className="mt-2 text-2xl font-semibold text-neutral-50">{passage.title}</h1>
          <p className="mt-1 text-sm text-neutral-500">
            Speak along with the voice, half a second behind. Copy the rhythm, don't wait for full sentences.
          </p>
        </div>
        <button className="link shrink-0" onClick={onBack}>
          back
        </button>
      </div>

      <div className="card min-h-[11rem] text-xl leading-relaxed">
        {hideText && mode === "shadowing" ? (
          <p className="text-neutral-600">Text hidden. Follow by ear.</p>
        ) : (
          passage.words.map((w, i) => {
            const status = busy ? undefined : statusOf(i);
            const tone =
              i === wordIndex
                ? "text-emerald-300"
                : status === "missed"
                  ? "text-neutral-600 underline decoration-red-500/70 decoration-2 underline-offset-4"
                  : status === "unclear"
                    ? "text-amber-300"
                    : "text-neutral-200";
            const marked = !busy && hardest === w.sentence ? "bg-neutral-800/80" : "";
            return (
              <span key={i} className={`${tone} ${marked} transition-colors`}>
                {w.text}{" "}
              </span>
            );
          })
        )}
      </div>

      {busy ? (
        <div className="flex items-center gap-5">
          <span className="text-neutral-300">
            {mode === "listening" && "Just listen."}
            {mode === "shadowing" && "● Recording. Speak along."}
            {mode === "analysing" && "Checking how far you kept up..."}
            {mode === "looping" && `Say it with the voice · ${loopInfo ?? ""}`}
            {mode === "comparing" && `Now playing: ${loopInfo ?? ""}`}
          </span>
          {mode !== "analysing" && (
            <button className="btn" onClick={stop}>
              Stop
            </button>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <button className={stepClass("listen")} onClick={() => void listen()}>
              1 · Listen
            </button>
            <button className={stepClass("withText")} onClick={() => void shadow(false)}>
              2 · Speak along
            </button>
            <button className={stepClass("blind")} onClick={() => void shadow(true)}>
              3 · Without the text
            </button>
          </div>
          <div className="flex items-center gap-3 text-sm text-neutral-500">
            speed
            {SPEEDS.map((s) => (
              <button
                key={s}
                className={`rounded-lg border px-3 py-1 ${
                  speed === s ? "border-neutral-300 text-neutral-100" : "border-neutral-800"
                }`}
                onClick={() => setSpeed(s)}
              >
                {s === 1 ? "normal" : `${s}×`}
              </button>
            ))}
          </div>
        </div>
      )}

      {error && <p className="text-sm text-red-400">{error}</p>}

      {metrics && !busy && (
        <div className="pop-in flex flex-col gap-4">
          {metrics.transcript_missing ? (
            <p className="text-neutral-300">I didn't hear you on that run. Check the microphone and try again.</p>
          ) : (
            <>
              <p className="text-5xl font-semibold text-neutral-50">
                {Math.round((metrics.coverage ?? 0) * 100)}
                <span className="text-2xl text-neutral-500">% of the words</span>
              </p>
              <p className="text-neutral-400">
                {metrics.lag_drift_s === null
                  ? "Too few words landed to say how well you stayed in step."
                  : metrics.lag_drift_s > 0.35
                    ? `You slipped further behind towards the end (about ${metrics.lag_drift_s.toFixed(1)} s). Try the slower speed.`
                    : "You stayed in step with the speaker the whole way."}
                {(metrics.coverage ?? 0) >= 0.9 && speed < 1.15 && " Ready for a faster speed or the next passage."}
              </p>
            </>
          )}

          {hardest !== null && (
            <div className="rounded-2xl border border-neutral-800 p-5">
              <p className="eyebrow">Where you dropped off</p>
              <p className="mt-2 text-lg text-neutral-100">
                {passage.sentences.find((s) => s.index === hardest)?.text}
              </p>
              <div className="mt-4 flex flex-wrap gap-3">
                <button className="btn !px-4 !py-2 !text-base" onClick={() => void loopSentence(hardest, 0.85)}>
                  Loop it slowly
                </button>
                <button className="btn !px-4 !py-2 !text-base" onClick={() => void loopSentence(hardest, 1.0)}>
                  Loop at full speed
                </button>
                {canCompare && (
                  <button className="btn !px-4 !py-2 !text-base" onClick={() => void compare(hardest)}>
                    Speaker, then me
                  </button>
                )}
              </div>
            </div>
          )}
          <p className="text-xs text-neutral-600">
            This measures whether you kept up, not your accent. For pronunciation, trust your ears: use "Speaker, then
            me".
          </p>
        </div>
      )}

      {!busy && (
        <div className="mt-auto flex flex-wrap items-center gap-6 pt-4">
          <button className="btn" onClick={() => void load(passage.passage_id)}>
            Next passage
          </button>
          <button className="link" onClick={onPractice}>
            grammar round instead
          </button>
          {passage.skills.length > 0 && (
            <span className="text-xs text-neutral-600">built around: {passage.skills.join(" · ")}</span>
          )}
        </div>
      )}
    </div>
  );
}
