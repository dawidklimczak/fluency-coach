import { LearningSessionSummary } from "../api/client";

interface Props {
  summary: LearningSessionSummary;
  onBack: () => void;
}

// podsumowanie zamkniętej sesji nauki: metryki + konstruktywny feedback
// (w tym gramatyczny - zawsze po sesji, nigdy w trakcie)
export default function SessionSummaryScreen({ summary, onBack }: Props) {
  const fb = summary.feedback;
  return (
    <div className="min-h-screen p-8">
      <div className="mx-auto flex max-w-2xl flex-col gap-8">
        <div className="text-center">
          <h1 className="text-2xl font-medium tracking-tight text-neutral-200">
            Session #{summary.number} finished
          </h1>
          <p className="mt-2 font-mono text-sm text-neutral-500">
            {summary.attempts} attempts
            {summary.median_ttfw != null &&
              ` · median start ${summary.median_ttfw.toFixed(2)} s`}
          </p>
        </div>

        {summary.fatigue_detected && (
          <p className="text-center text-amber-400">
            Start time rose sharply during this session - that is cognitive
            fatigue, not regression.
          </p>
        )}

        {summary.modules.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="text-left uppercase tracking-wide text-neutral-500">
                  <th className="py-2 pr-4 font-normal">module</th>
                  <th className="px-3 py-2 text-right font-normal">attempts</th>
                  <th className="px-3 py-2 text-right font-normal">start</th>
                  <th className="px-3 py-2 text-right font-normal">run length</th>
                  <th className="px-3 py-2 text-right font-normal">long pauses</th>
                </tr>
              </thead>
              <tbody>
                {summary.modules.map((m) => (
                  <tr key={m.module} className="border-t border-neutral-800">
                    <td className="py-2 pr-4 text-neutral-300">{m.module}</td>
                    <td className="px-3 py-2 text-right font-mono text-neutral-400">
                      {m.attempts}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-neutral-400">
                      {m.median_ttfw != null ? `${m.median_ttfw.toFixed(2)} s` : "—"}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-neutral-400">
                      {m.median_mean_length_of_run != null
                        ? `${m.median_mean_length_of_run.toFixed(1)} words`
                        : "—"}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-neutral-400">
                      {m.long_pause_total}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {fb && (
          <div className="flex flex-col gap-6">
            <p className="text-neutral-200">{fb.comment}</p>

            {fb.went_well.length > 0 && (
              <div>
                <p className="mb-2 text-sm uppercase tracking-wide text-emerald-400">
                  went well
                </p>
                <ul className="flex flex-col gap-1 text-neutral-300">
                  {fb.went_well.map((s, i) => (
                    <li key={i}>· {s}</li>
                  ))}
                </ul>
              </div>
            )}

            {fb.to_improve.length > 0 && (
              <div>
                <p className="mb-2 text-sm uppercase tracking-wide text-sky-400">
                  to work on
                </p>
                <ul className="flex flex-col gap-1 text-neutral-300">
                  {fb.to_improve.map((s, i) => (
                    <li key={i}>· {s}</li>
                  ))}
                </ul>
              </div>
            )}

            {fb.grammar.length > 0 && (
              <div>
                <p className="mb-2 text-sm uppercase tracking-wide text-neutral-500">
                  grammar patterns this session
                </p>
                <div className="flex flex-col gap-3">
                  {fb.grammar.map((g, i) => (
                    <div key={i} className="rounded border border-neutral-800 p-3">
                      <p className="text-neutral-200">{g.pattern}</p>
                      {g.example && (
                        <p className="mt-1 font-mono text-sm text-neutral-400">
                          {g.example}
                        </p>
                      )}
                      {g.note && (
                        <p className="mt-1 text-sm text-neutral-500">{g.note}</p>
                      )}
                    </div>
                  ))}
                </div>
                <p className="mt-3 text-xs text-neutral-600">
                  Errors during fluent speech are part of the training - these
                  patterns feed your long-term observations.
                </p>
              </div>
            )}
          </div>
        )}

        <button className="btn self-center" onClick={onBack}>
          done
        </button>
      </div>
    </div>
  );
}
