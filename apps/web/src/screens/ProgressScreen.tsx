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
import { api } from "../api/client";

// spec §3/§5: tylko sondy transferowe idą na wykres postępu, tylko delta -
// tu pokazujemy surowe serie, deltę widać na ekranie podsumowania sesji
const CHARTS: { key: string; label: string; unit: string }[] = [
  { key: "mean_length_of_run", label: "mean length of run", unit: "words" },
  { key: "phonation_time_ratio", label: "phonation time ratio", unit: "" },
  { key: "mid_clause_pause_duration", label: "mid-clause pause duration", unit: "s" },
  { key: "clause_final_pause_duration", label: "clause-final pause duration", unit: "s" },
];

const LINE = "#10b981";
const GRID = "#262626";
const INK_MUTED = "#737373";

// spec zmian §7: far jest głównym KPI generalizacji, stąd domyślny wybór
type ProbeFilter = "far" | "near" | "legacy";
const PROBE_FILTERS: { value: ProbeFilter; label: string }[] = [
  { value: "far", label: "Far transfer" },
  { value: "near", label: "Near transfer" },
  { value: "legacy", label: "Legacy" },
];

export default function ProgressScreen({ onBack }: { onBack: () => void }) {
  const [series, setSeries] = useState<Record<string, number | string | null>[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [probeType, setProbeType] = useState<ProbeFilter>("far");

  useEffect(() => {
    api
      .progress(90, probeType)
      .then((p) => setSeries(p.series))
      .catch((e) => setError(String(e)));
  }, [probeType]);

  return (
    <div className="min-h-screen p-8">
      <div className="mx-auto flex max-w-3xl flex-col gap-8">
        <div className="flex items-center justify-between">
          <h1 className="text-xl text-neutral-300">Progress · transfer probes, last 90 days</h1>
          <button className="text-sm text-neutral-500 underline" onClick={onBack}>
            back
          </button>
        </div>

        <div className="flex gap-2">
          {PROBE_FILTERS.map((f) => (
            <button
              key={f.value}
              className={
                "rounded border px-3 py-1 text-sm " +
                (probeType === f.value
                  ? "border-emerald-600 text-emerald-400"
                  : "border-neutral-800 text-neutral-500")
              }
              onClick={() => setProbeType(f.value)}
            >
              {f.label}
            </button>
          ))}
        </div>

        {error && <p className="text-red-400">{error}</p>}
        {series.length === 0 && !error && (
          <p className="text-neutral-500">
            No transfer probes yet - this only fills in after a few completed sessions.
          </p>
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
