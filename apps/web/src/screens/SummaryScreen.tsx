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
      <h2 className="text-xl text-neutral-300">Session summary</h2>

      <div className="grid grid-cols-3 gap-12 text-center">
        <Stat
          label="median time to start"
          value={summary.median_ttfw != null ? `${summary.median_ttfw.toFixed(2)} s` : "—"}
        />
        <Stat
          label="median run length"
          value={
            summary.median_mean_length_of_run != null
              ? `${summary.median_mean_length_of_run.toFixed(1)} words`
              : "—"
          }
        />
        <Stat label="long pauses" value={String(summary.long_pause_total)} />
      </div>

      {summary.baseline_7d_median_ttfw != null && (
        <p className="text-sm text-neutral-500">
          7-day median: {summary.baseline_7d_median_ttfw.toFixed(2)} s
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
                label={{ value: "attempt", position: "insideBottom", offset: -4, fill: "#525252" }}
              />
              <YAxis stroke="#525252" unit=" s" width={50} />
              <Tooltip
                contentStyle={{ background: "#171717", border: "1px solid #404040" }}
                labelFormatter={(v) => `attempt ${v}`}
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
          Session ended due to cognitive fatigue.
        </p>
      )}

      <p className="max-w-md text-center text-neutral-300">{summary.interpretation}</p>

      <button className="btn" onClick={onBack}>
        Back to start
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
