import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, ModuleInfo } from "../api/client";

// spec ekran 6: szeregi czasowe ttfw, mean_length_of_run, complexity_fluency_tradeoff
const CHARTS: { key: string; label: string; unit: string }[] = [
  { key: "ttfw", label: "time to first word", unit: "s" },
  { key: "mean_length_of_run", label: "mean length of run", unit: "words" },
  { key: "complexity_fluency_tradeoff", label: "complexity / fluency trade-off", unit: "" },
];

const LINE = "#10b981"; // emerald-500 - jedna seria na wykres, bez legendy
const GRID = "#262626";
const INK_MUTED = "#737373";

export default function ProgressScreen({ onBack }: { onBack: () => void }) {
  const [modules, setModules] = useState<ModuleInfo[]>([]);
  const [module, setModule] = useState<string>("");
  const [series, setSeries] = useState<Record<string, number | string | null>[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .modules()
      .then((ms) => {
        setModules(ms);
        if (ms.length > 0) setModule(ms[0].id);
      })
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!module) return;
    api
      .progress(module, 30)
      .then((p) => setSeries(p.series))
      .catch((e) => setError(String(e)));
  }, [module]);

  return (
    <div className="min-h-screen p-8">
      <div className="mx-auto flex max-w-3xl flex-col gap-8">
        <div className="flex items-center justify-between">
          <h1 className="text-xl text-neutral-300">Progress · last 30 days</h1>
          <div className="flex items-center gap-4">
            <select
              className="rounded border border-neutral-800 bg-neutral-950 px-3 py-2 text-neutral-300"
              value={module}
              onChange={(e) => setModule(e.target.value)}
            >
              {modules.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
            <button className="text-sm text-neutral-500 underline" onClick={onBack}>
              back
            </button>
          </div>
        </div>

        {error && <p className="text-red-400">{error}</p>}
        {series.length === 0 && !error && (
          <p className="text-neutral-500">No attempts in this range yet.</p>
        )}

        {series.length > 0 &&
          CHARTS.map((c) => {
            const data = series.filter((r) => r[c.key] != null);
            if (data.length === 0) return null;
            return (
              <div key={c.key}>
                <p className="mb-2 text-sm uppercase tracking-wide text-neutral-500">
                  {c.label}
                  {c.unit ? ` (${c.unit})` : ""}
                </p>
                <div className="h-48 w-full">
                  <ResponsiveContainer>
                    <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                      <CartesianGrid stroke={GRID} vertical={false} />
                      <XAxis
                        dataKey="date"
                        stroke={INK_MUTED}
                        tick={{ fill: INK_MUTED, fontSize: 12 }}
                        tickLine={false}
                      />
                      <YAxis
                        stroke={INK_MUTED}
                        tick={{ fill: INK_MUTED, fontSize: 12 }}
                        tickLine={false}
                        width={44}
                        domain={["auto", "auto"]}
                      />
                      <Tooltip
                        contentStyle={{
                          background: "#171717",
                          border: "1px solid #404040",
                          borderRadius: 4,
                          color: "#d4d4d4",
                        }}
                        labelStyle={{ color: "#a3a3a3" }}
                        formatter={(v: number) => [v, c.label]}
                      />
                      <Line
                        type="monotone"
                        dataKey={c.key}
                        stroke={LINE}
                        strokeWidth={2}
                        dot={{ r: 3, fill: LINE, strokeWidth: 0 }}
                        activeDot={{ r: 5, stroke: "#0a0a0a", strokeWidth: 2 }}
                        isAnimationActive={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            );
          })}
      </div>
    </div>
  );
}
