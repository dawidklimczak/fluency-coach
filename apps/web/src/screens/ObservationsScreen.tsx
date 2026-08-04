import { useEffect, useState } from "react";
import { api } from "../api/client";

// spec 5.5: powtarzalne wzorce błędów, raz w tygodniu, poza sesją treningową
export default function ObservationsScreen({ onBack }: { onBack: () => void }) {
  const [items, setItems] = useState<
    { pattern: string; example: string | null; note: string | null }[]
  >([]);
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .observations()
      .then((d) => {
        setItems(d.items);
        setGeneratedAt(d.generated_at);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="min-h-screen p-8">
      <div className="mx-auto flex max-w-2xl flex-col gap-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl text-neutral-300">Weekly observations</h1>
          <button className="text-sm text-neutral-500 underline" onClick={onBack}>
            back
          </button>
        </div>

        {loading && <p className="text-neutral-500">Loading...</p>}
        {error && <p className="text-red-400">{error}</p>}

        {!loading && !error && items.length === 0 && (
          <p className="text-neutral-500">
            Nothing yet - observations appear after a week of sessions.
          </p>
        )}

        {generatedAt && (
          <p className="text-sm text-neutral-600">
            generated {generatedAt.slice(0, 10)}
          </p>
        )}

        <div className="flex flex-col gap-4">
          {items.map((it, i) => (
            <div key={i} className="rounded border border-neutral-800 p-4">
              <p className="text-neutral-200">{it.pattern}</p>
              {it.example && (
                <p className="mt-2 font-mono text-sm text-neutral-400">{it.example}</p>
              )}
              {it.note && <p className="mt-2 text-sm text-neutral-500">{it.note}</p>}
            </div>
          ))}
        </div>

        {items.length > 0 && (
          <p className="text-sm text-neutral-600">
            These are recurring patterns, not a to-do list. Fluent speech with
            errors beats hesitant speech without them.
          </p>
        )}
      </div>
    </div>
  );
}
