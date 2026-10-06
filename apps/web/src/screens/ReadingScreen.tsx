import { useCallback, useEffect, useRef, useState } from "react";
import { api, ReadingMetrics, ReadingToken } from "../api/client";
import { Recorder } from "../audio/recorder";
import { BrowserVad } from "../audio/vad";
import { encodeWav, SAMPLE_RATE } from "../audio/wav";

type Phase = "setup" | "reading" | "processing" | "result" | "error";

const TARGET_PRESETS = [
  { wpm: 110, label: "deliberate" },
  { wpm: 130, label: "conversational" },
  { wpm: 150, label: "brisk" },
  { wpm: 170, label: "fast" },
];

const TARGET_KEY = "reading_target_wpm";
const MINUTE_PRESETS = [1, 2, 3, 5];
const MAX_STRUCTURES = 3;

// Skala rozbieżna wobec celu: wolniej (chłodny) - na cel (neutralny) -
// szybciej (ciepły). Kolor nigdy nie niesie znaczenia sam: każde słowo ma
// tooltip z wartością, a pod tekstem jest legenda i liczby.
const SLOWER = "57, 135, 229"; // #3987e5
const FASTER = "230, 103, 103"; // #e66767

function formatDuration(seconds: number): string {
  const total = Math.round(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function speedStyle(wpm: number | null | undefined, target: number): React.CSSProperties {
  if (wpm == null) return {};
  const deviation = (wpm - target) / target;
  const magnitude = Math.min(1, Math.abs(deviation) / 0.4); // ±40% = pełne nasycenie
  if (magnitude < 0.08) return {};
  const rgb = deviation < 0 ? SLOWER : FASTER;
  return { backgroundColor: `rgba(${rgb}, ${(magnitude * 0.55).toFixed(2)})` };
}

export default function ReadingScreen({ onBack }: { onBack: () => void }) {
  const [phase, setPhase] = useState<Phase>("setup");
  const [text, setText] = useState("");
  const [target, setTarget] = useState<number>(
    () => Number(localStorage.getItem(TARGET_KEY)) || 130
  );
  const [elapsed, setElapsed] = useState(0);
  const [speaking, setSpeaking] = useState(false);
  const [tokens, setTokens] = useState<ReadingToken[] | null>(null);
  const [metrics, setMetrics] = useState<ReadingMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  // generowanie tekstu; panel otwarty domyślnie, dopóki nie ma tekstu -
  // inaczej wybór struktur był schowany dwa kliknięcia głęboko
  const [showGenerator, setShowGenerator] = useState(true);
  const [structures, setStructures] = useState<{ id: string; label: string }[]>([]);
  const [structuresError, setStructuresError] = useState(false);
  const [minutes, setMinutes] = useState(2);
  const [topic, setTopic] = useState("");
  const [chosenStructures, setChosenStructures] = useState<string[]>([]);
  const [generating, setGenerating] = useState(false);
  const [genNote, setGenNote] = useState<string | null>(null);
  const [genError, setGenError] = useState<string | null>(null);

  const recorderRef = useRef<Recorder | null>(null);
  const vadRef = useRef<BrowserVad | null>(null);
  const t0Ref = useRef(0);
  const stoppedRef = useRef(false);
  const vadChainRef = useRef<Promise<void>>(Promise.resolve());

  useEffect(() => {
    localStorage.setItem(TARGET_KEY, String(target));
  }, [target]);

  useEffect(() => {
    return () => {
      recorderRef.current?.destroy();
    };
  }, []);

  useEffect(() => {
    if (showGenerator && structures.length === 0) {
      api
        .readingStructures()
        .then((s) => {
          setStructures(s);
          setStructuresError(false);
        })
        // bez tego pusta lista wyglądała jak brak funkcji, a nie jak błąd
        .catch(() => setStructuresError(true));
    }
  }, [showGenerator, structures.length]);

  const toggleStructure = (id: string) => {
    setChosenStructures((prev) =>
      prev.includes(id)
        ? prev.filter((s) => s !== id)
        : prev.length >= MAX_STRUCTURES
          ? prev
          : [...prev, id]
    );
  };

  const generate = async () => {
    setGenerating(true);
    setGenError(null);
    setGenNote(null);
    try {
      const res = await api.generateReadingText({
        minutes,
        target_wpm: target,
        topic,
        structures: chosenStructures,
      });
      setText(res.text);
      setGenNote(
        `"${res.title}" · ${res.word_count} words · about ${res.estimated_seconds}s at ${target} wpm` +
          (res.contains_digits
            ? " · contains digits, which may lower the accuracy score"
            : "")
      );
      setShowGenerator(false);
    } catch (e) {
      setGenError(String(e instanceof Error ? e.message : e));
    } finally {
      setGenerating(false);
    }
  };

  const start = useCallback(async () => {
    setError(null);
    try {
      const [recorder, vad] = await Promise.all([Recorder.create(), BrowserVad.create()]);
      recorderRef.current = recorder;
      vadRef.current = vad;
      stoppedRef.current = false;
      setElapsed(0);
      await recorder.start();
      requestAnimationFrame(() => {
        t0Ref.current = recorder.markT0();
        setPhase("reading");
      });
      recorder.onVadFrame = (frame) => {
        vadChainRef.current = vadChainRef.current.then(async () => {
          if (stoppedRef.current) return;
          const prob = await vad.processFrame(frame);
          setSpeaking(prob >= 0.5);
        });
      };
    } catch (e) {
      setError(String(e));
      setPhase("error");
    }
  }, []);

  const finish = useCallback(async () => {
    const recorder = recorderRef.current;
    if (!recorder || stoppedRef.current) return;
    stoppedRef.current = true;
    recorder.onVadFrame = null;
    const samples = recorder.stop();
    await recorder.destroy();
    recorderRef.current = null;
    setPhase("processing");
    try {
      const { reading_id } = await api.submitReading(encodeWav(samples), {
        reference_text: text,
        target_wpm: target,
      });
      for (let i = 0; i < 240; i++) {
        const r = await api.getReading(reading_id);
        if (r.status === "done") {
          setTokens(r.words);
          setMetrics(r.metrics);
          setPhase("result");
          return;
        }
        if (r.status === "error") throw new Error("Analysis failed");
        await new Promise((res) => setTimeout(res, 500));
      }
      throw new Error("Analysis is taking too long");
    } catch (e) {
      setError(String(e));
      setPhase("error");
    }
  }, [text, target]);

  useEffect(() => {
    if (phase !== "reading") return;
    const iv = window.setInterval(() => {
      const recorder = recorderRef.current;
      if (recorder) {
        setElapsed((recorder.samplesRecorded - t0Ref.current) / SAMPLE_RATE);
      }
    }, 100);
    return () => window.clearInterval(iv);
  }, [phase]);

  const reset = () => {
    setTokens(null);
    setMetrics(null);
    setPhase("setup");
  };

  // --- ekrany ---

  if (phase === "error") {
    return (
      <Frame onBack={onBack}>
        <p className="text-red-400">{error}</p>
        <button className="btn" onClick={reset}>
          try again
        </button>
      </Frame>
    );
  }

  if (phase === "processing") {
    return (
      <Frame onBack={onBack}>
        <p className="text-2xl text-neutral-400">Analysing...</p>
      </Frame>
    );
  }

  if (phase === "reading") {
    const words = text.trim().split(/\s+/).length;
    const projected = elapsed > 0 ? Math.round((words / target) * 60) : 0;
    return (
      <div className="min-h-screen p-8">
        <div className="mx-auto max-w-3xl">
          <div className="mb-8 flex items-baseline justify-between">
            <span className="font-mono text-4xl tabular-nums text-neutral-100">
              {elapsed.toFixed(1)}s
            </span>
            <span className="font-mono text-sm text-neutral-500">
              target {target} wpm · pace for this text ≈ {projected}s
            </span>
          </div>

          <p className="whitespace-pre-wrap text-2xl leading-relaxed text-neutral-200">
            {text}
          </p>

          <div className="fixed bottom-0 left-0 h-3 w-full bg-neutral-800">
            <div
              className={`h-full w-full transition-colors duration-100 ${
                speaking ? "bg-emerald-500" : "bg-neutral-700"
              }`}
            />
          </div>

          <button
            className="fixed bottom-8 right-8 rounded border border-neutral-700 px-5 py-2 text-neutral-300 hover:border-neutral-400"
            onClick={finish}
          >
            ■ finish
          </button>
        </div>
      </div>
    );
  }

  if (phase === "result" && metrics && tokens) {
    return (
      <div className="min-h-screen p-8">
        <div className="mx-auto flex max-w-3xl flex-col gap-8">
          <div className="flex items-center justify-between">
            <h1 className="text-xl text-neutral-300">Reading result</h1>
            <button className="text-sm text-neutral-500 underline" onClick={onBack}>
              back
            </button>
          </div>

          <div className="grid grid-cols-2 gap-8 sm:grid-cols-4">
            <Stat
              label="reading time"
              value={formatDuration(metrics.duration_s)}
            />
            <Stat
              label="your pace"
              value={metrics.wpm != null ? `${metrics.wpm}` : "—"}
              unit="wpm"
              note={
                metrics.wpm_vs_target != null
                  ? `${metrics.wpm_vs_target > 0 ? "+" : ""}${metrics.wpm_vs_target} vs target`
                  : undefined
              }
            />
            <Stat
              label="while speaking"
              value={metrics.wpm_articulation != null ? `${metrics.wpm_articulation}` : "—"}
              unit="wpm"
              note="pauses excluded"
            />
            <Stat
              label="steadiness"
              value={metrics.steadiness != null ? `±${metrics.steadiness}` : "—"}
              unit="wpm"
              note="lower is more even"
            />
            <Stat
              label="read correctly"
              value={
                metrics.accuracy != null ? `${Math.round(metrics.accuracy * 100)}` : "—"
              }
              unit="%"
              note={`${metrics.spoken_count}/${metrics.reference_words} words`}
            />
          </div>

          {metrics.transcript_missing && (
            <p className="rounded border border-amber-900 p-3 text-sm text-amber-400">
              No transcript came back — check your OpenAI key in settings. Timing
              still works, but the heat map and accuracy need transcription.
            </p>
          )}

          <div>
            <div className="mb-3 flex flex-wrap items-center gap-4 text-xs text-neutral-500">
              <span className="uppercase tracking-wide">speed map</span>
              <Swatch color={`rgba(${SLOWER}, 0.5)`} label={`slower than ${target}`} />
              <Swatch color="transparent" label="on target" border />
              <Swatch color={`rgba(${FASTER}, 0.5)`} label={`faster than ${target}`} />
              <span className="text-neutral-600">
                · <span className="underline decoration-amber-500 decoration-2">unclear</span>
                {"  "}· <span className="text-neutral-700 line-through">skipped</span>
              </span>
            </div>

            <p className="text-xl leading-loose">
              {tokens.map((t, i) => (
                <span key={i}>
                  {t.newline_before && <br />}
                  <span
                    className={
                      t.status === "missed"
                        ? "text-neutral-700 line-through"
                        : t.status === "unclear"
                          ? "text-neutral-200 underline decoration-amber-500 decoration-2 underline-offset-4"
                          : "text-neutral-200"
                    }
                    style={t.status !== "missed" ? speedStyle(t.wpm, target) : undefined}
                    title={
                      t.status === "missed"
                        ? "not detected in the recording"
                        : t.status === "unclear"
                          ? `heard: ${t.heard ?? "something else"}`
                          : t.wpm != null
                            ? `${t.wpm} wpm`
                            : undefined
                    }
                  >
                    {t.text}
                  </span>{" "}
                </span>
              ))}
            </p>
          </div>

          <div className="flex flex-col gap-2 text-sm text-neutral-500">
            {metrics.slowest_wpm != null && metrics.fastest_wpm != null && (
              <p>
                Local pace ranged from{" "}
                <span className="font-mono text-neutral-300">{metrics.slowest_wpm}</span> to{" "}
                <span className="font-mono text-neutral-300">{metrics.fastest_wpm}</span> wpm.
              </p>
            )}
            {metrics.pause_count > 0 && (
              <p>
                {metrics.pause_count} noticeable pause
                {metrics.pause_count === 1 ? "" : "s"}
                {metrics.longest_pauses.length > 0 && (
                  <>
                    , longest before{" "}
                    <span className="text-neutral-300">
                      &ldquo;{metrics.longest_pauses[0].before}&rdquo;
                    </span>{" "}
                    ({metrics.longest_pauses[0].duration}s)
                  </>
                )}
                .
              </p>
            )}
            {metrics.unclear_count > 0 && (
              <p>
                {metrics.unclear_count} word
                {metrics.unclear_count === 1 ? " was" : "s were"} transcribed as something
                else — often unclear articulation, sometimes just the transcriber being
                wrong. Hover to see what came through.
              </p>
            )}
            {metrics.extra_count > 0 && (
              <p>{metrics.extra_count} extra word(s) — re-reads or fillers.</p>
            )}
          </div>

          <div className="flex gap-4">
            <button className="btn" onClick={() => setPhase("setup")}>
              read again
            </button>
          </div>
        </div>
      </div>
    );
  }

  // setup
  const wordCount = text.trim() ? text.trim().split(/\s+/).length : 0;
  return (
    <div className="min-h-screen p-8">
      <div className="mx-auto flex max-w-3xl flex-col gap-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl text-neutral-300">Reading pace trainer</h1>
          <button className="text-sm text-neutral-500 underline" onClick={onBack}>
            back
          </button>
        </div>

        <p className="text-sm text-neutral-500">
          Paste any English text or have one written for you, pick a target pace, then
          read it aloud. You get your overall pace and a map of where you sped up or
          slowed down.
        </p>

        <div className="flex items-center justify-between border-b border-neutral-800 pb-3">
          <span className="text-sm uppercase tracking-wide text-neutral-500">
            text to read
          </span>
          <button
            className={`rounded border px-3 py-1 text-sm ${
              showGenerator
                ? "border-neutral-700 text-neutral-400"
                : "border-neutral-600 text-neutral-200 hover:border-neutral-400"
            }`}
            onClick={() => setShowGenerator(!showGenerator)}
          >
            {showGenerator ? "hide generator" : "write one for me"}
          </button>
        </div>

        {showGenerator && (
          <div className="flex flex-col gap-4 rounded border border-neutral-800 p-4">
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-sm text-neutral-500">length</span>
              {MINUTE_PRESETS.map((m) => (
                <button
                  key={m}
                  className={`rounded border px-3 py-1 text-sm ${
                    minutes === m
                      ? "border-neutral-400 text-neutral-100"
                      : "border-neutral-800 text-neutral-500 hover:border-neutral-600"
                  }`}
                  onClick={() => setMinutes(m)}
                >
                  {m} min
                </button>
              ))}
              <span className="text-sm text-neutral-600">
                ≈ {Math.round(minutes * target)} words at {target} wpm
              </span>
            </div>

            <input
              className="rounded border border-neutral-800 bg-neutral-950 px-3 py-2 text-neutral-100"
              placeholder="topic (optional) — e.g. why cities feel lonely"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
            />

            <div>
              <p className="mb-2 text-sm text-neutral-500">
                grammar to emphasise (optional, up to {MAX_STRUCTURES})
                {chosenStructures.length > 0 && (
                  <span className="ml-2 text-sky-400">
                    {chosenStructures.length} selected
                  </span>
                )}
              </p>
              {structuresError && (
                <p className="text-sm text-red-400">
                  Could not load the structure list — check that the app is running
                  and reload the page.
                </p>
              )}
              {!structuresError && structures.length === 0 && (
                <p className="text-sm text-neutral-600">loading...</p>
              )}
              <div className="flex flex-wrap gap-2">
                {structures.map((s) => {
                  const active = chosenStructures.includes(s.id);
                  const disabled = !active && chosenStructures.length >= MAX_STRUCTURES;
                  return (
                    <button
                      key={s.id}
                      disabled={disabled}
                      className={`rounded border px-2 py-1 text-xs ${
                        active
                          ? "border-sky-500 text-sky-300"
                          : disabled
                            ? "border-neutral-900 text-neutral-700"
                            : "border-neutral-800 text-neutral-400 hover:border-neutral-600"
                      }`}
                      onClick={() => toggleStructure(s.id)}
                    >
                      {s.label}
                    </button>
                  );
                })}
              </div>
            </div>

            {genError && <p className="text-sm text-red-400">{genError}</p>}

            <button className="btn self-start" onClick={generate} disabled={generating}>
              {generating ? "writing..." : "Generate"}
            </button>
            <p className="text-xs text-neutral-600">
              Numbers are written out as words, because digits get transcribed
              unpredictably and would show up as reading mistakes.
            </p>
          </div>
        )}

        <textarea
          className="h-56 w-full rounded border border-neutral-800 bg-neutral-950 p-4 text-neutral-100"
          placeholder="Paste the text you want to read..."
          value={text}
          onChange={(e) => setText(e.target.value)}
        />

        {genNote && <p className="text-sm text-emerald-400">{genNote}</p>}

        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-neutral-500">target pace</span>
          {TARGET_PRESETS.map((p) => (
            <button
              key={p.wpm}
              className={`rounded border px-3 py-1 text-sm ${
                target === p.wpm
                  ? "border-neutral-400 text-neutral-100"
                  : "border-neutral-800 text-neutral-500 hover:border-neutral-600"
              }`}
              onClick={() => setTarget(p.wpm)}
            >
              {p.wpm} · {p.label}
            </button>
          ))}
          <input
            type="number"
            min={60}
            max={300}
            className="w-20 rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-right font-mono text-neutral-200"
            value={target}
            onChange={(e) => setTarget(Number(e.target.value))}
          />
          <span className="text-sm text-neutral-600">wpm</span>
        </div>

        {wordCount > 0 && (
          <p className="text-sm text-neutral-600">
            {wordCount} words · at {target} wpm that is about{" "}
            {Math.round((wordCount / target) * 60)} seconds
          </p>
        )}

        <button className="btn self-start" onClick={start} disabled={wordCount < 5}>
          Start reading
        </button>
        {wordCount > 0 && wordCount < 5 && (
          <p className="text-sm text-neutral-600">Paste at least a few words.</p>
        )}
      </div>
    </div>
  );
}

function Frame({ children, onBack }: { children: React.ReactNode; onBack: () => void }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 p-8">
      <button className="fixed left-6 top-6 text-sm text-neutral-500 underline" onClick={onBack}>
        back
      </button>
      {children}
    </div>
  );
}

function Swatch({
  color,
  label,
  border,
}: {
  color: string;
  label: string;
  border?: boolean;
}) {
  return (
    <span className="flex items-center gap-2">
      <span
        className={`inline-block h-3 w-6 rounded-sm ${border ? "border border-neutral-700" : ""}`}
        style={{ backgroundColor: color }}
      />
      {label}
    </span>
  );
}

function Stat({
  label,
  value,
  unit,
  note,
}: {
  label: string;
  value: string;
  unit?: string;
  note?: string;
}) {
  return (
    <div>
      <div className="font-mono text-3xl tabular-nums text-neutral-100">
        {value}
        {unit && <span className="ml-1 text-base text-neutral-500">{unit}</span>}
      </div>
      <div className="mt-1 text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      {note && <div className="mt-0.5 text-xs text-neutral-600">{note}</div>}
    </div>
  );
}
