import { useEffect, useState } from "react";
import { api, GrammarHome, LevelName } from "../api/client";

interface Props {
  onPractice: () => void;
  onShadow: () => void;
  onMap: () => void;
  onTalk: () => void;
  onMore: () => void;
  onSettings: () => void;
}

export const LEVEL_ORDER: LevelName[] = ["mastered", "solid", "unaided", "learning", "new"];

export const LEVEL_COLOR: Record<LevelName, string> = {
  mastered: "bg-emerald-400",
  solid: "bg-emerald-600",
  unaided: "bg-sky-500",
  learning: "bg-amber-400",
  new: "bg-neutral-800",
};

export const LEVEL_LABEL: Record<LevelName, string> = {
  mastered: "mastered",
  solid: "solid",
  unaided: "unaided",
  learning: "learning",
  new: "not seen yet",
};

const DAYS = ["M", "T", "W", "T", "F", "S", "S"];

function todayLine(home: GrammarHome): string {
  const parts: string[] = [];
  if (home.due_today > 0) parts.push(`${home.due_today} back after a break`);
  if (home.in_progress.length > 0) parts.push(`working on: ${home.in_progress[0]}`);
  if (parts.length > 0) return parts.join(" · ");
  if (home.answers_total === 0) return "The first rounds find out what you can already say.";
  if (home.next_new) return `next up: ${home.next_new}`;
  return "Keeping everything fresh.";
}

export default function HomeScreen({ onPractice, onShadow, onMap, onTalk, onMore, onSettings }: Props) {
  const [home, setHome] = useState<GrammarHome | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .grammarHome()
      .then(setHome)
      .catch((e) => setError(String(e)));
  }, []);

  if (error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-8">
        <p className="max-w-lg text-center text-red-400">{error}</p>
        <button className="btn" onClick={() => window.location.reload()}>
          Reload
        </button>
      </div>
    );
  }
  if (!home) {
    return <div className="flex min-h-screen items-center justify-center text-neutral-600">...</div>;
  }

  const settled = home.counts.mastered + home.counts.solid;

  return (
    <div className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-10 p-6 sm:p-10">
      {!home.llm_ready && (
        <div className="rounded-xl border border-amber-900 p-4">
          <p className="text-amber-400">No OpenAI API key set.</p>
          <p className="mt-1 text-sm text-neutral-400">
            Answers can't be transcribed or checked without it.{" "}
            <button className="underline" onClick={onSettings}>
              Add the key
            </button>
          </p>
        </div>
      )}

      <div className="flex flex-col gap-4">
        <button className="btn-primary w-full py-7 text-3xl" onClick={onPractice} autoFocus>
          Start
          <span className="ml-3 text-lg font-normal text-emerald-900">3 min · out loud</span>
        </button>
        <p className="text-center text-neutral-400">{todayLine(home)}</p>
      </div>

      <button
        className="rounded-xl border border-neutral-800 px-6 py-4 text-left transition-colors hover:border-neutral-600"
        onClick={onShadow}
      >
        <span className="text-lg text-neutral-200">Shadowing</span>
        <span className="mt-1 block text-sm text-neutral-500">
          speak along with a recording · no thinking required · headphones
        </span>
      </button>

      <button className="group flex flex-col gap-3 text-left" onClick={onMap}>
        <div className="flex h-3 w-full overflow-hidden rounded-full bg-neutral-900">
          {LEVEL_ORDER.map((name) =>
            home.counts[name] > 0 ? (
              <span
                key={name}
                className={LEVEL_COLOR[name]}
                style={{ width: `${(home.counts[name] / home.total_skills) * 100}%` }}
                title={`${home.counts[name]} ${LEVEL_LABEL[name]}`}
              />
            ) : null
          )}
        </div>
        <p className="text-sm text-neutral-500 group-hover:text-neutral-300">
          {settled} of {home.total_skills} solid or mastered · {home.counts.unaided} unaided ·{" "}
          {home.counts.learning} learning · <span className="underline underline-offset-4">open the map</span>
        </p>
      </button>

      <div className="flex items-center gap-4">
        <div className="flex gap-2">
          {home.week.map((d, i) => (
            <span
              key={d.date}
              className={`flex h-9 w-9 items-center justify-center rounded-full text-xs ${
                d.done
                  ? "bg-emerald-400 font-semibold text-emerald-950"
                  : i === home.today_index
                    ? "border border-neutral-500 text-neutral-300"
                    : "border border-neutral-800 text-neutral-600"
              }`}
            >
              {DAYS[i]}
            </span>
          ))}
        </div>
        <span className="text-sm text-neutral-500">
          {home.week_days_done >= home.weekly_goal
            ? "weekly goal reached"
            : `${home.week_days_done} of ${home.weekly_goal} days this week`}
        </span>
      </div>

      <div className="flex gap-6">
        <button className="link" onClick={onTalk}>
          conversation kit
        </button>
        <button className="link" onClick={onMore}>
          more
        </button>
      </div>
    </div>
  );
}
