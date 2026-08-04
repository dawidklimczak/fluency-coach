import { useCallback, useEffect, useRef, useState } from "react";
import { api, AttemptResult, DrillConfig, TaskDto } from "../api/client";
import { Recorder } from "../audio/recorder";
import { BrowserVad } from "../audio/vad";
import { encodeWav, SAMPLE_RATE } from "../audio/wav";

type Phase = "prep" | "record" | "process" | "feedback" | "error";

interface Props {
  sessionId: number;
  firstTask: TaskDto;
  config: DrillConfig;
  vadThreshold: number;
  recorder: Recorder;
  vad: BrowserVad;
  onSessionEnd: (reason: "completed" | "fatigue" | "aborted") => void;
}

const HINT_PREP_S = 4;

function totalRounds(task: TaskDto, config: DrillConfig): number {
  const limits = task.payload?.round_limits_s as number[] | undefined;
  if (Array.isArray(limits) && limits.length > 0) return limits.length;
  return config.rounds;
}

function roundMaxSpeak(task: TaskDto, config: DrillConfig, round: number): number {
  const limits =
    (task.payload?.round_limits_s as number[] | undefined) ?? config.round_speak_s;
  if (Array.isArray(limits) && limits[round - 1] != null) return limits[round - 1];
  return config.max_speak_s;
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
  const [phase, setPhase] = useState<Phase>("prep");
  const [task, setTask] = useState<TaskDto>(firstTask);
  const [taskIndex, setTaskIndex] = useState(1);
  const [roundIndex, setRoundIndex] = useState(1);
  const [prepLeft, setPrepLeft] = useState(0);
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
  const recordingIndexRef = useRef(0); // numer nagrania w sesji (krzywa zmęczenia)
  const roundRef = useRef(1);

  const rounds = totalRounds(task, config);
  const maxSpeak = roundMaxSpeak(task, config, roundIndex);
  const remaining = Math.max(0, maxSpeak - elapsed);
  const timeLow = remaining <= maxSpeak * 0.2;

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
        attempt_index: recordingIndexRef.current,
        round_index: roundRef.current,
        structure_mode: task.structure_mode,
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
  }, [recorder, sessionId, task.id, task.structure_mode]);

  const startRecording = useCallback(async () => {
    stoppedRef.current = false;
    firstSpeechRef.current = false;
    setElapsed(0);
    setSpeaking(false);
    vad.reset();
    recordingIndexRef.current += 1;
    await recorder.start();
    // bodziec dostępny od teraz - t0 to offset próbek w buforze
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
  }, [recorder, vad, vadThreshold]);

  const beginRound = useCallback(
    (t: TaskDto, round: number) => {
      setTask(t);
      setRoundIndex(round);
      roundRef.current = round;
      setResult(null);

      const hintPrep =
        t.structure_mode === "explicit" && t.structure_hint ? HINT_PREP_S : 0;
      const prepSeconds = round === 1 ? config.prep_time_s + hintPrep : 0;
      if (prepSeconds > 0) {
        setPrepLeft(prepSeconds);
        setPhase("prep");
        return; // odliczanie w useEffect poniżej
      }
      startRecording();
    },
    [config.prep_time_s, startRecording]
  );

  useEffect(() => {
    beginRound(firstTask, 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // odliczanie fazy przygotowania (łańcuch setTimeout - restartuje się też,
  // gdy kolejne zadanie zaczyna od fazy prep bez zmiany phase)
  useEffect(() => {
    if (phase !== "prep" || prepLeft <= 0) return;
    const t = window.setTimeout(() => {
      if (prepLeft <= 1) {
        setPrepLeft(0);
        startRecording();
      } else {
        setPrepLeft(prepLeft - 1);
      }
    }, 1000);
    return () => window.clearTimeout(t);
  }, [phase, prepLeft, startRecording]);

  // pętla czasu i auto-stopu podczas nagrywania
  useEffect(() => {
    if (phase !== "record") return;
    const iv = window.setInterval(() => {
      const el = (recorder.samplesRecorded - t0Ref.current) / SAMPLE_RATE;
      setElapsed(el);
      const silence =
        (recorder.samplesRecorded - lastSpeechSampleRef.current) / SAMPLE_RATE;
      // auto_stop_silence_s <= 0 wyłącza auto-stop po ciszy - cały czas do dyspozycji
      const autoStopEnabled = config.auto_stop_silence_s > 0;
      const canAutoStop =
        autoStopEnabled && firstSpeechRef.current && el >= config.min_speak_s;
      if (el >= maxSpeak) stopAndSubmit();
      else if (canAutoStop && silence >= config.auto_stop_silence_s) stopAndSubmit();
    }, 100);
    return () => window.clearInterval(iv);
  }, [phase, config, recorder, stopAndSubmit, maxSpeak]);

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
    if (roundIndex < rounds) {
      beginRound(task, roundIndex + 1);
      return;
    }
    if (taskIndex >= config.attempts_per_session) {
      onSessionEnd("completed");
      return;
    }
    try {
      const { task: next } = await api.nextTask(sessionId);
      setTaskIndex((i) => i + 1);
      beginRound(next, 1);
    } catch (e) {
      setErrorMsg(String(e));
      setPhase("error");
    }
  }, [
    taskIndex,
    roundIndex,
    rounds,
    task,
    config.attempts_per_session,
    sessionId,
    beginRound,
    onSessionEnd,
    result,
  ]);

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

        {config.id === "paraphrase" && m.lexical_distance_min != null && (
          <p
            className={`text-lg ${
              m.lexical_distance_min > 0.5 ? "text-emerald-400" : "text-amber-400"
            }`}
          >
            lexical distance {Number(m.lexical_distance_min).toFixed(2)}
            {m.lexical_distance_min <= 0.5 && " - too close to the previous version"}
          </p>
        )}

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

        {(config.id === "fluency_sprint" || config.id === "story_loop") &&
          Array.isArray(m.phonation_timeline) && (
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
          {rounds > 1 && (
            <span className="mr-4">
              round {roundIndex} / {rounds}
            </span>
          )}
          attempt {taskIndex} / {config.attempts_per_session}
        </p>
      </div>
    );
  }

  if (phase === "prep") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center p-8">
        <ExitButton onClick={exitSession} />
        <div className="mb-12 font-mono text-7xl tabular-nums text-neutral-500">
          {prepLeft}
        </div>
        <p className="max-w-3xl text-center text-4xl font-medium leading-snug">
          {task.prompt_text}
        </p>
        {task.structure_mode === "explicit" && task.structure_hint && (
          <div className="mt-10 max-w-xl text-center">
            <p className="text-sm uppercase tracking-wide text-sky-400">
              {task.structure_hint.label}
            </p>
            {task.structure_hint.example && (
              <p className="mt-2 text-lg text-neutral-400">
                {task.structure_hint.example}
              </p>
            )}
          </div>
        )}
      </div>
    );
  }

  // record: bodziec + timer + pasek mowy. Nic więcej (spec sekcja 11).
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

      {rounds > 1 && (
        <p className="mt-6 font-mono text-sm text-neutral-600">
          {roundIndex} / {rounds}
        </p>
      )}

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
        className="fixed bottom-8 right-8 rounded border border-neutral-700 px-5 py-2 text-neutral-300 hover:border-neutral-400"
        onClick={stopAndSubmit}
      >
        ■ finish
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
