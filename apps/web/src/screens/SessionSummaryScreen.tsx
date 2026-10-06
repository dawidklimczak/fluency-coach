import { useEffect, useState } from "react";
import { api, ProbeSummary, SessionSummary } from "../api/client";

interface Props {
  summary: SessionSummary;
  onBack: () => void;
  onSelfTranscription: () => void;
}

const METRIC_LABELS: Record<string, { label: string; unit: string }> = {
  mean_length_of_run: { label: "mean length of run", unit: " words" },
  phonation_time_ratio: { label: "phonation time ratio", unit: "" },
  mid_clause_pause_duration: { label: "mid-clause pause duration", unit: "s" },
};

// spec §5: wyłącznie delta vs baseline, bez z-score'ów, bez ocen, bez kolorów
function deltaLine(key: string, value: number | null, baseline: number | null): string | null {
  const meta = METRIC_LABELS[key];
  if (!meta || value == null) return null;
  if (baseline == null) return `${meta.label}: ${value}${meta.unit} (still building your baseline)`;
  const diff = value - baseline;
  const abs = Math.abs(diff).toFixed(diff < 1 ? 2 : 1);
  if (Math.abs(diff) < 0.01) return `${meta.label}: about the same as your median`;
  const direction = diff > 0 ? "higher" : "lower";
  return `${meta.label}: ${abs}${meta.unit} ${direction} than your median`;
}

const ENDED_REASON_TEXT: Record<string, string> = {
  completed: "Session completed.",
  low_phonation_r3: "The session ended a bit early - that's a normal call, not a setback.",
};

// spec zmian §14: Near i Far pokazane osobno, każde z własną notatką i deltami
function ProbeSection({ title, probe }: { title: string; probe: ProbeSummary }) {
  const lines = Object.entries(probe.deltas)
    .map(([key, d]) => deltaLine(key, d.value, d.baseline))
    .filter((line): line is string => Boolean(line));

  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-sm uppercase tracking-wide text-neutral-500">{title}</h2>
      {probe.outcome_note && <p className="text-neutral-400">{probe.outcome_note}</p>}
      {lines.length === 0 && <p className="text-neutral-500">No data yet.</p>}
      {lines.map((line, i) => (
        <p key={i} className="text-neutral-300">
          {line}
        </p>
      ))}
    </section>
  );
}

export default function SessionSummaryScreen({ summary, onBack, onSelfTranscription }: Props) {
  const [transcriptionAvailable, setTranscriptionAvailable] = useState(false);

  useEffect(() => {
    api
      .selfTranscriptionAvailable(summary.session_id)
      .then((r) => setTranscriptionAvailable(r.available))
      .catch(() => {});
  }, [summary.session_id]);

  return (
    <div className="min-h-screen p-8">
      <div className="mx-auto flex max-w-xl flex-col gap-8">
        <h1 className="text-xl text-neutral-300">Session summary</h1>

        <p className="text-neutral-300">
          {ENDED_REASON_TEXT[summary.ended_reason] ?? summary.ended_reason}
        </p>

        <ProbeSection title="Near transfer (versus your near median)" probe={summary.near} />
        <ProbeSection title="Far transfer (versus your far median)" probe={summary.far} />

        <section>
          <p className="text-sm text-neutral-500">
            Support level: {summary.support_ceiling}
            {summary.support_changed === "down" && " (eased down since last time)"}
            {summary.support_changed === "up" && " (brought back up a notch)"}
          </p>
        </section>

        {transcriptionAvailable && (
          <button className="btn self-start" onClick={onSelfTranscription}>
            Optional: transcribe your first round yourself
          </button>
        )}

        <button className="btn self-start" onClick={onBack}>
          Back
        </button>
      </div>
    </div>
  );
}
