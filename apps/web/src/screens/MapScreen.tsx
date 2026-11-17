import { useEffect, useState } from "react";
import { api, LevelName, SkillDto, SkillGroup } from "../api/client";
import { LEVEL_COLOR, LEVEL_LABEL, LEVEL_ORDER } from "./HomeScreen";

interface Props {
  onBack: () => void;
}

const LEVEL_HELP: Record<LevelName, string> = {
  new: "You haven't met it yet. The first time is a cold try, with no help.",
  learning: "You get the sentence shape and the first words, then only the situation.",
  unaided: "Only the situation, mixed with everything else. A few right in a row moves it up.",
  solid: "Right and quick. Now it has to survive breaks of 3, 7 and 21 days.",
  mastered: "It survived every break. Checked every month or two.",
};

function dueText(s: SkillDto): string | null {
  if (!s.next_due) return null;
  if (s.due) return "check due now";
  const days = Math.round((new Date(s.next_due).getTime() - Date.now()) / 86_400_000) + 1;
  return days <= 1 ? "next check tomorrow" : `next check in ${days} days`;
}

export default function MapScreen({ onBack }: Props) {
  const [groups, setGroups] = useState<SkillGroup[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .grammarMap()
      .then((r) => setGroups(r.groups))
      .catch((e) => setError(String(e)));
  }, []);

  if (error) return <p className="p-8 text-red-400">{error}</p>;
  if (!groups) return <div className="flex min-h-screen items-center justify-center text-neutral-600">...</div>;

  const all = groups.flatMap((g) => g.skills);
  const done = all.filter((s) => s.level >= 3).length;

  return (
    <div className="mx-auto flex min-h-screen max-w-3xl flex-col gap-8 p-6 sm:p-10">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="eyebrow">Your grammar map</p>
          <p className="mt-2 text-3xl font-semibold text-neutral-50">
            {done}
            <span className="text-neutral-600"> / {all.length}</span>
          </p>
          <p className="mt-1 text-sm text-neutral-500">
            Each tile is one thing you can mean and the sentence shape that says it.
          </p>
        </div>
        <button className="btn" onClick={onBack}>
          Back
        </button>
      </div>

      <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-neutral-500">
        {[...LEVEL_ORDER].reverse().map((name) => (
          <span key={name} className="flex items-center gap-2" title={LEVEL_HELP[name]}>
            <span className={`h-3 w-3 rounded-sm ${LEVEL_COLOR[name]}`} />
            {LEVEL_LABEL[name]}
          </span>
        ))}
      </div>

      {groups.map((g) => (
        <section key={g.id} className="flex flex-col gap-3">
          <h2 className="eyebrow">{g.label}</h2>
          <div className="grid gap-2 sm:grid-cols-2">
            {g.skills.map((s) => {
              const expanded = open === s.id;
              return (
                <button
                  key={s.id}
                  className={`flex flex-col gap-2 rounded-xl border p-4 text-left transition-colors ${
                    expanded ? "border-neutral-500 sm:col-span-2" : "border-neutral-800 hover:border-neutral-600"
                  }`}
                  onClick={() => setOpen(expanded ? null : s.id)}
                >
                  <span className="flex items-start gap-3">
                    <span className={`mt-1.5 h-3 w-3 shrink-0 rounded-sm ${LEVEL_COLOR[s.level_name]}`} />
                    <span className="flex-1">
                      <span className="block text-neutral-200">{s.pl}</span>
                      <span className="block text-sm text-neutral-500">{s.meaning}</span>
                    </span>
                    {s.wild_uses > 0 && (
                      <span className="text-amber-300" title="used correctly in a real conversation">
                        ★
                      </span>
                    )}
                  </span>
                  {expanded && (
                    <span className="mt-2 flex flex-col gap-2 border-t border-neutral-800 pt-3">
                      <span className="font-mono text-sm text-amber-300">{s.pattern}</span>
                      <span className="italic text-neutral-300">{s.example}</span>
                      {s.trap_pl && <span className="text-sm text-neutral-400"><span className="mr-2 rounded border border-neutral-700 px-1.5 py-0.5 text-[10px] font-semibold tracking-wider text-neutral-400">PL</span>
                          {s.trap_pl}</span>}
                      <span className="text-sm text-neutral-500">
                        {LEVEL_LABEL[s.level_name]}: {LEVEL_HELP[s.level_name]}
                      </span>
                      <span className="text-xs text-neutral-600">
                        {s.attempts > 0 ? `${s.correct} of ${s.attempts} right so far` : "no answers yet"}
                        {dueText(s) ? ` · ${dueText(s)}` : ""}
                        {s.wild_uses > 0 ? ` · used in conversation ${s.wild_uses}×` : ""}
                        {s.name ? ` · textbook name: ${s.name}` : ""}
                      </span>
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
