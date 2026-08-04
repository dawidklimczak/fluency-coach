import { useEffect, useState } from "react";
import { api } from "../api/client";

type Row = {
  structure: string;
  attempts: number;
  avoidance: number | null;
  avoidance_explicit: number | null;
  avoidance_implicit: number | null;
  ttfw_structured: number | null;
  pre_structure_pause: number | null;
};

// mapa cieplna (spec 7.2): wartość zawsze widoczna liczbowo, kolor tylko wzmacnia
function heat(value: number | null, max: number): string {
  if (value == null) return "transparent";
  const a = Math.max(0, Math.min(1, value / max)) * 0.55;
  return `rgba(245, 158, 11, ${a})`; // amber - wyższa wartość = wyższy koszt
}

export default function StructuresScreen({ onBack }: { onBack: () => void }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [baseline, setBaseline] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .structuresHeatmap()
      .then((d) => {
        setRows(d.structures);
        setBaseline(d.baseline_ttfw);
      })
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <div className="min-h-screen p-8">
      <div className="mx-auto flex max-w-4xl flex-col gap-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl text-neutral-300">Grammar structures</h1>
          <button className="text-sm text-neutral-500 underline" onClick={onBack}>
            back
          </button>
        </div>

        {baseline != null && (
          <p className="text-sm text-neutral-500">
            baseline time to first word (tasks without a target structure):{" "}
            <span className="font-mono text-neutral-300">{baseline.toFixed(2)} s</span>
          </p>
        )}

        {error && <p className="text-red-400">{error}</p>}
        {rows.length === 0 && !error && (
          <p className="text-neutral-500">
            No structure-tagged attempts yet. Start a session with a structure filter.
          </p>
        )}

        {rows.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="text-left uppercase tracking-wide text-neutral-500">
                  <th className="py-2 pr-4 font-normal">structure</th>
                  <th className="px-3 py-2 text-right font-normal">attempts</th>
                  <th className="px-3 py-2 text-right font-normal">avoidance</th>
                  <th className="px-3 py-2 text-right font-normal">explicit</th>
                  <th className="px-3 py-2 text-right font-normal">implicit</th>
                  <th className="px-3 py-2 text-right font-normal">ttfw</th>
                  <th className="px-3 py-2 text-right font-normal">pre-structure pause</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.structure} className="border-t border-neutral-800">
                    <td className="py-2 pr-4 font-mono text-neutral-300">{r.structure}</td>
                    <td className="px-3 py-2 text-right font-mono text-neutral-400">
                      {r.attempts}
                    </td>
                    <Cell value={r.avoidance} max={1} fmt={(v) => `${(v * 100).toFixed(0)}%`} />
                    <Cell
                      value={r.avoidance_explicit}
                      max={1}
                      fmt={(v) => `${(v * 100).toFixed(0)}%`}
                    />
                    <Cell
                      value={r.avoidance_implicit}
                      max={1}
                      fmt={(v) => `${(v * 100).toFixed(0)}%`}
                    />
                    <Cell
                      value={r.ttfw_structured}
                      max={baseline != null ? baseline * 3 : 5}
                      fmt={(v) => `${v.toFixed(2)} s`}
                    />
                    <Cell
                      value={r.pre_structure_pause}
                      max={2}
                      fmt={(v) => `${v.toFixed(2)} s`}
                    />
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <p className="text-sm text-neutral-600">
          High avoidance in implicit mode with low avoidance in explicit mode means:
          you know the structure but do not reach for it on your own.
        </p>
      </div>
    </div>
  );
}

function Cell({
  value,
  max,
  fmt,
}: {
  value: number | null;
  max: number;
  fmt: (v: number) => string;
}) {
  return (
    <td
      className="px-3 py-2 text-right font-mono text-neutral-200"
      style={{ background: heat(value, max) }}
    >
      {value != null ? fmt(value) : "—"}
    </td>
  );
}
