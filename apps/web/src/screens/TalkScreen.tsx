import { useEffect, useState } from "react";
import { api, TranscriptReview } from "../api/client";

interface Props {
  onBack: () => void;
  onPractice: () => void;
}

/**
 * Most do rozmów prowadzonych poza aplikacją (asystent głosowy w subskrypcji):
 * gotowy tekst na start rozmowy + analiza wklejonego zapisu.
 */
export default function TalkScreen({ onBack, onPractice }: Props) {
  const [prompt, setPrompt] = useState<{ text: string; skills: { id: string; meaning: string }[] } | null>(null);
  const [copied, setCopied] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [review, setReview] = useState<TranscriptReview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.talkPrompt().then(setPrompt).catch((e) => setError(String(e)));
  }, []);

  const copy = async () => {
    if (!prompt) return;
    try {
      await navigator.clipboard.writeText(prompt.text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Couldn't copy automatically - select the text and copy it by hand.");
    }
  };

  const analyse = async () => {
    setBusy(true);
    setError(null);
    setReview(null);
    try {
      setReview(await api.reviewTranscript(text));
      setText("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const saved = review?.findings.filter((f) => f.skill_id).length ?? 0;

  return (
    <div className="mx-auto flex min-h-screen max-w-2xl flex-col gap-8 p-6 sm:p-10">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="eyebrow">Conversation kit</p>
          <p className="mt-2 text-neutral-400">
            Real conversations happen in your voice assistant, not here. This page connects the two.
          </p>
        </div>
        <button className="link shrink-0" onClick={onBack}>
          back
        </button>
      </div>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg text-neutral-100">1 · Start a conversation that uses what you're practising</h2>
        <p className="text-sm text-neutral-500">Paste this as the first message, then switch to voice.</p>
        <pre className="card whitespace-pre-wrap font-sans text-sm leading-relaxed text-neutral-300">
          {prompt ? prompt.text : "..."}
        </pre>
        <button className="btn self-start" onClick={copy} disabled={!prompt}>
          {copied ? "Copied ✓" : "Copy"}
        </button>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg text-neutral-100">2 · Bring the conversation back</h2>
        <p className="text-sm text-neutral-500">
          Paste the transcript. Your real mistakes become exercises in your next rounds, and anything you got right on
          your own earns a star on the map.
        </p>
        <textarea
          className="min-h-[10rem] rounded-xl border border-neutral-800 bg-neutral-950 p-4 text-sm text-neutral-200 focus:border-neutral-500 focus:outline-none"
          placeholder="Paste the whole conversation here, both sides."
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={busy}
        />
        <button className="btn-primary self-start !px-6 !py-3 !text-lg" onClick={analyse} disabled={busy || text.trim().length < 40}>
          {busy ? "Reading it..." : "Find my mistakes"}
        </button>
        {error && <p className="text-sm text-red-400">{error}</p>}
      </section>

      {review && (
        <section className="pop-in flex flex-col gap-4">
          {review.summary && <p className="text-neutral-200">{review.summary}</p>}

          {review.used_well.length > 0 && (
            <div className="flex flex-col gap-1">
              <p className="eyebrow text-amber-300">★ Used on your own</p>
              {review.used_well.map((u) => (
                <p key={u.skill_id} className="text-neutral-300">
                  {u.label}
                </p>
              ))}
            </div>
          )}

          {review.findings.length === 0 ? (
            <p className="text-neutral-400">No grammar mistakes worth practising in this one.</p>
          ) : (
            review.findings.map((f, i) => (
              <div key={i} className="rounded-2xl border border-neutral-800 p-5">
                <p className="text-neutral-500">You said: {f.said}</p>
                <p className="mt-2 text-xl text-neutral-50">{f.corrected}</p>
                {f.explanation && <p className="mt-2 text-sm text-neutral-400">{f.explanation}</p>}
                <p className="mt-2 text-xs text-neutral-600">
                  {f.skill_label ? `added to: ${f.skill_label}` : "not on the map, shown for reference"}
                </p>
              </div>
            ))
          )}

          {saved > 0 && (
            <button className="btn self-start" onClick={onPractice}>
              Practise {saved === 1 ? "it" : `these ${saved}`} now
            </button>
          )}
        </section>
      )}
    </div>
  );
}
