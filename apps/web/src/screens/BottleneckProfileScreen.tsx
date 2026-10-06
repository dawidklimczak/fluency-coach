import { useEffect, useState } from "react";
import { api, BottleneckProfile } from "../api/client";

const LABELS: Record<string, string> = {
  content_generation_sensitivity: "Content generation sensitivity",
  planning_benefit: "Planning benefit",
  repetition_benefit: "Repetition benefit",
  l2_specific_cost: "L2-specific cost",
  sustained_speech_cost: "Sustained-speech cost",
};

const ORDER = [
  "content_generation_sensitivity",
  "planning_benefit",
  "repetition_benefit",
  "l2_specific_cost",
  "sustained_speech_cost",
];

export default function BottleneckProfileScreen({ onBack }: { onBack: () => void }) {
  const [profile, setProfile] = useState<BottleneckProfile | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getBottleneckProfile()
      .then((r) => setProfile(r.profile))
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <div className="min-h-screen p-8">
      <div className="mx-auto flex max-w-xl flex-col gap-8">
        <div className="flex items-center justify-between">
          <h1 className="text-xl text-neutral-300">Bottleneck profile</h1>
          <button className="text-sm text-neutral-500 underline" onClick={onBack}>
            back
          </button>
        </div>

        {error && <p className="text-red-400">{error}</p>}

        {profile === undefined && !error && <p className="text-neutral-500">Loading...</p>}

        {profile === null && (
          <p className="text-neutral-500">
            Not enough data yet - complete at least 3 diagnostic sessions to see a profile.
          </p>
        )}

        {profile && (
          <>
            <div className="flex flex-col gap-3">
              {ORDER.map((key) => (
                <div key={key} className="flex items-center justify-between rounded border border-neutral-800 px-4 py-3">
                  <span className="text-neutral-300">{LABELS[key]}</span>
                  <span className="text-neutral-100 capitalize">{profile[key as keyof BottleneckProfile]}</span>
                </div>
              ))}
            </div>
            <p className="text-sm text-neutral-500">{profile.disclaimer}</p>
          </>
        )}
      </div>
    </div>
  );
}
