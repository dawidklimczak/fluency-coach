import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { SessionSummary } from "../api/client";

interface Props {
  summary: SessionSummary;
  fatigue: boolean;
  onBack: () => void;
}

export default function SummaryScreen({ summary, fatigue, onBack }: Props) {
  const data = summary.fatigue_curve.filter((p) => p.ttfw != null);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-8 p-8">
      <h2 className="text-xl text-neutral-300">Podsumowanie sesji</h2>

      <div className="grid grid-cols-3 gap-12 text-center">
        <Stat
          label="mediana czasu startu"
          value={summary.median_ttfw != null ? `${summary.median_ttfw.toFixed(2)} s` : "—"}
        />
        <Stat
          label="mediana odcinka"
          value={
            summary.median_mean_length_of_run != null
              ? `${summary.median_mean_length_of_run.toFixed(1)} słów`
              : "—"
          }
        />
        <Stat label="długie pauzy" value={String(summary.long_pause_total)} />
      </div>

      {summary.baseline_7d_median_ttfw != null && (
        <p className="text-sm text-neutral-500">
          mediana z 7 dni: {summary.baseline_7d_median_ttfw.toFixed(2)} s
        </p>
      )}

      {data.length >= 2 && (
        <div className="h-64 w-full max-w-2xl">
          <ResponsiveContainer>
            <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
              <CartesianGrid stroke="#262626" />
              <XAxis
                dataKey="attempt_index"
                stroke="#525252"
                label={{ value: "próba", position: "insideBottom", offset: -4, fill: "#525252" }}
              />
              <YAxis stroke="#525252" unit=" s" width={50} />
              <Tooltip
                contentStyle={{ background: "#171717", border: "1px solid #404040" }}
                labelFormatter={(v) => `próba ${v}`}
              />
              <Line
                type="monotone"
                dataKey="ttfw"
                stroke="#10b981"
                strokeWidth={2}
                dot={{ r: 3 }}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {fatigue && (
        <p className="max-w-md text-center text-amber-400">
          Sesja zakończona z powodu zmęczenia poznawczego.
        </p>
      )}

      <p className="max-w-md text-center text-neutral-300">{summary.interpretation}</p>

      <button className="btn" onClick={onBack}>
        Wróć do startu
      </button>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-mono text-4xl tabular-nums">{value}</div>
      <div className="mt-2 text-sm uppercase tracking-wide text-neutral-500">{label}</div>
    </div>
  );
}
