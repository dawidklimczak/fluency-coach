import { useState } from "react";
import { api } from "../api/client";

interface Props {
  sessionId: number;
  onDone: () => void;
}

export default function SelfTranscriptionScreen({ sessionId, onDone }: Props) {
  const [text, setText] = useState("");
  const [result, setResult] = useState<{ user_text: string; whisper_text: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    try {
      const r = await api.submitSelfTranscription(sessionId, text);
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="min-h-screen p-8">
      <div className="mx-auto flex max-w-xl flex-col gap-6">
        <h1 className="text-xl text-neutral-300">Your first round, from memory</h1>
        <p className="text-sm text-neutral-500">
          Listen back in your head and write down what you actually said. No scoring - this is
          just for you to notice your own patterns.
        </p>

        {!result ? (
          <>
            <textarea
              className="min-h-[160px] rounded border border-neutral-800 bg-neutral-950 px-4 py-3 text-neutral-100"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Write what you remember saying..."
            />
            {error && <p className="text-red-400">{error}</p>}
            <button className="btn self-start" onClick={submit} disabled={!text.trim()}>
              Compare
            </button>
          </>
        ) : (
          <div className="flex flex-col gap-6">
            <div>
              <h2 className="mb-2 text-sm uppercase tracking-wide text-neutral-500">
                What you wrote
              </h2>
              <p className="whitespace-pre-wrap rounded border border-neutral-800 p-4 text-neutral-200">
                {result.user_text}
              </p>
            </div>
            <div>
              <h2 className="mb-2 text-sm uppercase tracking-wide text-neutral-500">
                What the transcript shows
              </h2>
              <p className="whitespace-pre-wrap rounded border border-neutral-800 p-4 text-neutral-200">
                {result.whisper_text || "(no transcript)"}
              </p>
            </div>
          </div>
        )}

        <button className="text-sm text-neutral-500 underline self-start" onClick={onDone}>
          back
        </button>
      </div>
    </div>
  );
}
