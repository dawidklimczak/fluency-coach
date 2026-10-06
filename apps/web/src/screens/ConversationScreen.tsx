import { useEffect, useRef, useState } from "react";
import { api, ConversationResult } from "../api/client";
import { LiveConversation } from "../audio/livesession";
import { encodeWav } from "../audio/wav";
import SpeakerOrb from "./SpeakerOrb";

interface Props {
  onBack: () => void;
}

type Phase = "setup" | "connecting" | "live" | "processing" | "results";

const PERSONA_LABELS: Record<string, string> = {
  colleague: "Colleague over coffee",
  interviewer: "Friendly interviewer",
  neighbour: "Neighbour",
  tutor: "Curious friend",
};

const MINUTES = [5, 10, 15, 20];

function fmt(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined ? "–" : v.toFixed(digits);
}

export default function ConversationScreen({ onBack }: Props) {
  const [phase, setPhase] = useState<Phase>("setup");
  const [personas, setPersonas] = useState<string[]>([]);
  const [persona, setPersona] = useState("tutor");
  const [minutes, setMinutes] = useState(10);
  const [headphones, setHeadphones] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aiSpeaking, setAiSpeaking] = useState(false);
  const [userSpeaking, setUserSpeaking] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [result, setResult] = useState<ConversationResult | null>(null);

  const aiLevel = useRef(0);
  const userLevel = useRef(0);
  const live = useRef<LiveConversation | null>(null);
  const finishing = useRef(false);

  useEffect(() => {
    api
      .conversationPersonas()
      .then((r) => setPersonas(r.personas))
      .catch((e) => setError(String(e)));
    return () => {
      live.current?.abort().catch(() => {});
    };
  }, []);

  useEffect(() => {
    if (phase !== "live") return;
    const started = Date.now();
    const id = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 500);
    return () => window.clearInterval(id);
  }, [phase]);

  async function finish() {
    const conv = live.current;
    if (!conv || finishing.current) return;
    finishing.current = true;
    setPhase("processing");
    try {
      const r = await conv.finish();
      live.current = null;
      await api.endConversation(conv.sessionId, encodeWav(r.wav), r.turns, r.billedSeconds);
      for (let i = 0; i < 120; i++) {
        const res = await api.getConversation(conv.sessionId);
        if (res.status === "done" || res.status === "error") {
          setResult(res);
          setPhase("results");
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      throw new Error("Analiza trwa zbyt długo");
    } catch (e) {
      setError(String(e));
      setPhase("setup");
    } finally {
      finishing.current = false;
    }
  }

  async function start() {
    setError(null);
    setPhase("connecting");
    const conv = new LiveConversation({
      onAiSpeaking: setAiSpeaking,
      onUserSpeaking: setUserSpeaking,
      onAiLevel: (l) => (aiLevel.current = l),
      onUserLevel: (l) => (userLevel.current = l),
      onTimeout: () => void finish(),
      onError: setError,
    });
    live.current = conv;
    try {
      await conv.start(persona, minutes);
      setElapsed(0);
      setPhase("live");
    } catch (e) {
      await conv.abort().catch(() => {});
      live.current = null;
      setError(e instanceof Error ? e.message : String(e));
      setPhase("setup");
    }
  }

  if (phase === "setup") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-6 p-8">
        <div className="flex w-full max-w-md flex-col gap-6">
          <h1 className="text-xl text-neutral-300">Conversation</h1>
          <p className="text-sm text-neutral-500">
            An open voice conversation. No transcript and no corrections while you talk - the
            numbers come after.
          </p>

          <div className="flex flex-col gap-2">
            {personas.map((p) => (
              <label key={p} className="flex items-center gap-2 text-neutral-300">
                <input type="radio" checked={persona === p} onChange={() => setPersona(p)} />
                {PERSONA_LABELS[p] ?? p}
              </label>
            ))}
          </div>

          <div className="flex items-center gap-3 text-neutral-300">
            <span className="text-sm text-neutral-500">Length</span>
            {MINUTES.map((m) => (
              <button
                key={m}
                className={`rounded border px-3 py-1 text-sm ${
                  minutes === m ? "border-neutral-300" : "border-neutral-800 text-neutral-500"
                }`}
                onClick={() => setMinutes(m)}
              >
                {m} min
              </button>
            ))}
          </div>

          <label className="flex items-center gap-2 text-sm text-neutral-400">
            <input
              type="checkbox"
              checked={headphones}
              onChange={(e) => setHeadphones(e.target.checked)}
            />
            I'm wearing headphones (needed - speakers leak the other voice into the recording)
          </label>

          {error && <p className="text-sm text-red-400">{error}</p>}

          <div className="flex gap-4">
            <button className="btn" disabled={!headphones} onClick={start}>
              Start
            </button>
            <button className="text-sm text-neutral-500 underline" onClick={onBack}>
              Back
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (phase === "connecting" || phase === "processing") {
    return (
      <div className="flex min-h-screen items-center justify-center text-neutral-500">
        {phase === "connecting" ? "Connecting..." : "Analysing the conversation..."}
      </div>
    );
  }

  if (phase === "live") {
    const mm = String(Math.floor(elapsed / 60)).padStart(2, "0");
    const ss = String(elapsed % 60).padStart(2, "0");
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-12 p-8">
        <div className="flex flex-wrap items-center justify-center gap-16 sm:gap-28">
          <SpeakerOrb
            label={PERSONA_LABELS[persona] ?? "Them"}
            sublabel="speaking"
            levelRef={aiLevel}
            active={aiSpeaking}
            rgb="120, 170, 255"
          />
          <SpeakerOrb
            label="You"
            sublabel="speaking"
            levelRef={userLevel}
            active={userSpeaking}
            rgb="130, 220, 170"
          />
        </div>
        <div className="text-3xl tabular-nums text-neutral-500">
          {mm}:{ss}
        </div>
        <button className="btn" onClick={() => void finish()}>
          End conversation
        </button>
      </div>
    );
  }

  const turns = result?.turns ?? [];
  return (
    <div className="min-h-screen p-8">
      <div className="mx-auto flex max-w-2xl flex-col gap-6">
        <h1 className="text-xl text-neutral-300">Conversation results</h1>
        {result?.status === "error" && (
          <p className="text-red-400">The analysis failed - the recording was discarded.</p>
        )}
        {result?.status === "done" && turns.length === 0 && (
          <p className="text-neutral-500">No full turns were detected this time.</p>
        )}
        {turns.length > 0 && (
          <table className="w-full text-left text-sm text-neutral-300">
            <thead className="text-neutral-500">
              <tr>
                <th className="py-1">Turn</th>
                <th>First word (s)</th>
                <th>Run (words)</th>
                <th>Speaking ratio</th>
                <th>Fillers/min</th>
              </tr>
            </thead>
            <tbody>
              {turns.map((t) => (
                <tr key={t.number} className="border-t border-neutral-900">
                  <td className="py-1">{t.number}</td>
                  <td>{fmt(t.metrics.ttfw, 2)}</td>
                  <td>{fmt(t.metrics.mean_length_of_run)}</td>
                  <td>{fmt(t.metrics.phonation_time_ratio, 2)}</td>
                  <td>{fmt(t.metrics.filler_rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <button className="btn self-start" onClick={onBack}>
          Back
        </button>
      </div>
    </div>
  );
}
