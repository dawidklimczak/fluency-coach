import { useCallback, useEffect, useRef, useState } from "react";
import { api, AttemptResult, DrillConfig, TaskDto } from "../api/client";
import { Recorder } from "../audio/recorder";
import { BrowserVad } from "../audio/vad";
import { encodeWav, SAMPLE_RATE } from "../audio/wav";

type Phase = "present" | "record" | "process" | "feedback" | "error";

interface Props {
  sessionId: number;
  firstTask: TaskDto;
  config: DrillConfig;
  vadThreshold: number;
  recorder: Recorder;
  vad: BrowserVad;
  onSessionEnd: (reason: "completed" | "fatigue" | "aborted") => void;
}

export default function DrillScreen({
  sessionId,
  firstTask,
  config,
  vadThreshold,
  recorder,
  vad,
  onSessionEnd,
}: Props) {
  const [phase, setPhase] = useState<Phase>("present");
  const [task, setTask] = useState<TaskDto>(firstTask);
  const [attemptIndex, setAttemptIndex] = useState(1);
  const [elapsed, setElapsed] = useState(0);
  const [speaking, setSpeaking] = useState(false);
  const [result, setResult] = useState<AttemptResult | null>(null);
  const [showTranscript, setShowTranscript] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const t0Ref = useRef(0);
  const stoppedRef = useRef(false);
  const firstSpeechRef = useRef(false);
  const lastSpeechSampleRef = useRef(0);
  const vadChainRef = useRef<Promise<void>>(Promise.resolve());
  const advanceTimerRef = useRef<number | null>(null);
  const showTranscriptRef = useRef(false);

  const remaining = Math.max(0, config.max_speak_s - elapsed);
  const timeLow = remaining <= config.max_speak_s * 0.2;

  // powrót do ekranu głównego: przerywa nagrywanie, nic nie wysyła
  const exitSession = useCallback(() => {
    stoppedRef.current = true;
    recorder.onVadFrame = null;
    recorder.stop();
    onSessionEnd("aborted");
  }, [recorder, onSessionEnd]);

  const stopAndSubmit = useCallback(async () => {
    if (stoppedRef.current) return;
    stoppedRef.current = true;
    recorder.onVadFrame = null;
    const samples = recorder.stop();
    setPhase("process");
    try {
      const wav = encodeWav(samples);
      const { attempt_id } = await api.submitAttempt(wav, {
        session_id: sessionId,
        task_id: task.id,
        t0_offset_samples: t0Ref.current,
        attempt_index: attemptIndex,
        round_index: 1,
      });
      // odpytywanie co 500 ms do status done (spec sekcja 10)
      const poll = async (): Promise<AttemptResult> => {
        for (let i = 0; i < 120; i++) {
          const r = await api.getAttempt(attempt_id);
          if (r.status !== "processing") return r;
          await new Promise((res) => setTimeout(res, 500));
        }
        throw new Error("Przetwarzanie trwa zbyt długo");
      };
      const r = await poll();
      if (r.status === "error") throw new Error("Błąd przetwarzania próby");
      setResult(r);
      setShowTranscript(false);
      showTranscriptRef.current = false;
      setPhase("feedback");
    } catch (e) {
      setErrorMsg(String(e));
      setPhase("error");
    }
  }, [recorder, sessionId, task.id, attemptIndex]);

  const beginAttempt = useCallback(
    async (t: TaskDto) => {
      setTask(t);
      setResult(null);
      setElapsed(0);
      setSpeaking(false);
      stoppedRef.current = false;
      firstSpeechRef.current = false;
      vad.reset();
      await recorder.start();
      // bodziec pojawia się teraz - t0 to offset próbek w buforze
      requestAnimationFrame(() => {
        t0Ref.current = recorder.markT0();
        lastSpeechSampleRef.current = t0Ref.current;
        setPhase("record");
      });

      recorder.onVadFrame = (frame) => {
        vadChainRef.current = vadChainRef.current.then(async () => {
          if (stoppedRef.current) return;
          const prob = await vad.processFrame(frame);
          const isSpeech = prob >= vadThreshold;
          setSpeaking(isSpeech);
          if (isSpeech) {
            firstSpeechRef.current = true;
            lastSpeechSampleRef.current = recorder.samplesRecorded;
          }
        });
      };
    },
    [recorder, vad, vadThreshold]
  );

  useEffect(() => {
    beginAttempt(firstTask);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // pętla czasu i auto-stopu podczas nagrywania
  useEffect(() => {
    if (phase !== "record") return;
    const iv = window.setInterval(() => {
      const el = (recorder.samplesRecorded - t0Ref.current) / SAMPLE_RATE;
      setElapsed(el);
      const silence =
        (recorder.samplesRecorded - lastSpeechSampleRef.current) / SAMPLE_RATE;
      const canAutoStop = firstSpeechRef.current && el >= config.min_speak_s;
      if (el >= config.max_speak_s) stopAndSubmit();
      else if (canAutoStop && silence >= config.auto_stop_silence_s) stopAndSubmit();
    }, 100);
    return () => window.clearInterval(iv);
  }, [phase, config, recorder, stopAndSubmit]);

  const goNext = useCallback(async () => {
    if (advanceTimerRef.current) {
      window.clearTimeout(advanceTimerRef.current);
      advanceTimerRef.current = null;
    }
    const fatigue = result?.metrics?.fatigue_detected === true;
    if (fatigue) {
      onSessionEnd("fatigue");
      return;
    }
    if (attemptIndex >= config.attempts_per_session) {
      onSessionEnd("completed");
      return;
    }
    try {
      const { task: next } = await api.nextTask(sessionId);
      setAttemptIndex((i) => i + 1);
      setPhase("present");
      await beginAttempt(next);
    } catch (e) {
      setErrorMsg(String(e));
      setPhase("error");
    }
  }, [attemptIndex, config.attempts_per_session, sessionId, beginAttempt, onSessionEnd, result]);

  // automatyczne przejście po 4 s ekspozycji feedbacku (spec ekran 4)
  useEffect(() => {
    if (phase !== "feedback") return;
    advanceTimerRef.current = window.setTimeout(() => {
      if (!showTranscriptRef.current) goNext();
    }, 4000);
    return () => {
      if (advanceTimerRef.current) window.clearTimeout(advanceTimerRef.current);
    };
  }, [phase, goNext]);

  const forbidden = (task.payload?.forbidden_words as string[] | undefined) ?? [];

  if (phase === "error") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-6 p-8">
        <p className="text-red-400">{errorMsg}</p>
        <button className="btn" onClick={() => onSessionEnd("aborted")}>
          Back to start
        </button>
      </div>
    );
  }

  if (phase === "process") {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <ExitButton onClick={exitSession} />
        <p className="text-2xl text-neutral-400">Processing...</p>
      </div>
    );
  }

  if (phase === "feedback" && result?.metrics) {
    const m = result.metrics;
    const failed = m.failed === true;
    const fatigue = m.fatigue_detected === true;
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-8 p-8">
        <ExitButton onClick={exitSession} />
        <div className="grid grid-cols-3 gap-12 text-center">
          <Stat label="time to start" value={m.ttfw != null ? `${m.ttfw.toFixed(2)} s` : "—"} />
          <Stat
            label="longest run"
            value={
              m.max_length_of_run != null
                ? `${m.max_length_of_run} words`
                : m.longest_speech_segment_s != null
                  ? `${m.longest_speech_segment_s.toFixed(1)} s`
                  : "—"
            }
          />
          <Stat label="long pauses" value={String(m.long_pause_count ?? 0)} />
        </div>

        {failed && (
          <p className="text-lg text-red-400">
            Forbidden word used: {(m.forbidden_hits as string[]).join(", ")}
          </p>
        )}
        {fatigue && (
          <p className="text-lg text-amber-400">
            Your start time has clearly risen - that is fatigue. Ending the session.
          </p>
        )}

        {config.id === "fluency_sprint" && Array.isArray(m.phonation_timeline) && (
          <div className="flex h-16 items-end gap-1">
            {(m.phonation_timeline as number[]).map((v, i) => (
              <div
                key={i}
                className="w-3 bg-emerald-500"
                style={{ height: `${Math.max(4, v * 100)}%`, opacity: 0.4 + v * 0.6 }}
              />
            ))}
          </div>
        )}

        {result.transcript && (
          <div className="w-full max-w-2xl">
            <button
              className="text-sm text-neutral-500 underline"
              onClick={() => {
                showTranscriptRef.current = !showTranscript;
                setShowTranscript(!showTranscript);
              }}
            >
              {showTranscript ? "hide transcript" : "show transcript"}
            </button>
            {showTranscript && (
              <p className="mt-2 text-neutral-300">{result.transcript}</p>
            )}
          </div>
        )}

        <button className="btn" onClick={goNext}>
          next
        </button>
        <p className="text-sm text-neutral-600">
          attempt {attemptIndex} / {config.attempts_per_session}
        </p>
      </div>
    );
  }

  // present / record: bodziec + timer + pasek mowy. Nic więcej (spec sekcja 11).
  return (
    <div
      className={`flex min-h-screen flex-col items-center justify-center p-8 transition-colors duration-500 ${
        timeLow ? "bg-red-950" : "bg-neutral-950"
      }`}
    >
      <ExitButton onClick={exitSession} />

      {config.show_timer && (
        <div className="mb-12 font-mono text-7xl tabular-nums text-neutral-100">
          {remaining.toFixed(0)}
        </div>
      )}

      <p className="max-w-3xl text-center text-4xl font-medium leading-snug">
        {task.prompt_text}
      </p>

      {forbidden.length > 0 && (
        <div className="mt-8 text-center">
          <p className="text-sm uppercase tracking-wide text-red-400">
            do not use these words
          </p>
          <p className="mt-2 text-xl text-neutral-500 line-through decoration-red-400/60">
            {forbidden.join(" · ")}
          </p>
        </div>
      )}

      <div className="fixed bottom-0 left-0 h-3 w-full bg-neutral-800">
        <div
          className={`h-full transition-all duration-100 ${
            speaking ? "w-full bg-emerald-500" : "w-full bg-neutral-700"
          }`}
        />
      </div>

      <button
        className="fixed bottom-8 right-8 rounded border border-neutral-700 px-4 py-2 text-neutral-400"
        onClick={stopAndSubmit}
      >
        ■
      </button>
    </div>
  );
}

function ExitButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      className="fixed left-6 top-6 rounded border border-neutral-800 px-3 py-1 text-lg text-neutral-500 hover:border-neutral-500 hover:text-neutral-300"
      onClick={onClick}
      aria-label="Back to start"
      title="Back to start"
    >
      ✕
    </button>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-mono text-5xl tabular-nums">{value}</div>
      <div className="mt-2 text-sm uppercase tracking-wide text-neutral-500">{label}</div>
    </div>
  );
}
