import { useEffect, useState } from "react";
import { api, Domain } from "../api/client";

interface Props {
  onBack: () => void;
}

export default function ProfileScreen({ onBack }: Props) {
  const [content, setContent] = useState("");
  const [savedMsg, setSavedMsg] = useState(false);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [newDomain, setNewDomain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api.getPersonalContext().then((r) => setContent(r.content)).catch(() => {});
    api.listDomains().then(setDomains).catch(() => {});
    api.suggestDomains().then(setSuggestions).catch(() => {});
  };

  useEffect(load, []);

  const saveContext = async () => {
    setBusy(true);
    try {
      await api.setPersonalContext(content);
      setSavedMsg(true);
      setTimeout(() => setSavedMsg(false), 2000);
    } finally {
      setBusy(false);
    }
  };

  const addDomain = async (name?: string) => {
    const value = (name ?? newDomain).trim();
    if (!value) return;
    setError(null);
    try {
      await api.createDomain(value);
      setNewDomain("");
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const resumeDomain = async (id: number) => {
    setError(null);
    try {
      await api.reactivateDomain(id);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const activeDomain = domains.find((d) => d.status === "active");

  return (
    <div className="min-h-screen p-8">
      <div className="mx-auto flex max-w-xl flex-col gap-10">
        <div className="flex items-center justify-between">
          <h1 className="text-xl text-neutral-300">Profile</h1>
          <button className="text-sm text-neutral-500 underline" onClick={onBack}>
            back
          </button>
        </div>

        <section className="flex flex-col gap-3">
          <h2 className="text-sm uppercase tracking-wide text-neutral-500">
            Personal context
          </h2>
          <p className="text-xs text-neutral-600">
            Po polsku: praca, projekty, zainteresowania, powracające sytuacje.
            Generator sesji zakotwicza w tym seed texty, żeby nie musieć niczego
            wymyślać w trakcie mówienia.
          </p>
          <textarea
            className="min-h-[160px] rounded border border-neutral-800 bg-neutral-950 px-4 py-3 text-neutral-100"
            value={content}
            onChange={(e) => setContent(e.target.value)}
          />
          <div className="flex items-center gap-3">
            <button className="btn self-start" onClick={saveContext} disabled={busy}>
              Save
            </button>
            {savedMsg && <span className="text-sm text-emerald-400">Saved.</span>}
          </div>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-sm uppercase tracking-wide text-neutral-500">Domain</h2>
          {activeDomain ? (
            <div className="rounded border border-neutral-800 p-4">
              <p className="text-neutral-200">{activeDomain.name}</p>
              <p className="mt-1 text-sm text-neutral-500">
                session {activeDomain.session_count} / {activeDomain.target_sessions}
              </p>
              <button
                className="mt-3 text-sm text-neutral-500 underline"
                onClick={() => api.finishDomain(activeDomain.id).then(load)}
              >
                mark done, switch topic
              </button>
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              <p className="text-sm text-neutral-400">
                No active domain - sessions can't start without one.
              </p>
              <div className="flex gap-2">
                <input
                  className="flex-1 rounded border border-neutral-800 bg-neutral-950 px-4 py-2 text-neutral-100"
                  placeholder="e.g. remote work"
                  value={newDomain}
                  onChange={(e) => setNewDomain(e.target.value)}
                />
                <button className="btn" onClick={() => addDomain()}>
                  Create
                </button>
              </div>
              {suggestions.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {suggestions.map((s) => (
                    <button
                      key={s}
                      className="rounded-full border border-neutral-800 px-3 py-1 text-xs text-neutral-400 hover:border-neutral-600 hover:text-neutral-200"
                      onClick={() => addDomain(s)}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              )}
              {error && <p className="text-sm text-red-400">{error}</p>}
            </div>
          )}

          {domains.filter((d) => d.status === "done").length > 0 && (
            <div className="mt-2 flex flex-col gap-1">
              <p className="text-xs uppercase tracking-wide text-neutral-600">Past domains</p>
              {domains
                .filter((d) => d.status === "done")
                .map((d) => (
                  <div key={d.id} className="flex items-center justify-between text-sm text-neutral-500">
                    <span>
                      {d.name} - {d.session_count} sessions
                    </span>
                    <button
                      className="text-xs text-neutral-500 underline hover:text-neutral-300"
                      onClick={() => resumeDomain(d.id)}
                      disabled={!!activeDomain}
                      title={activeDomain ? "finish the active domain first" : "resume this domain"}
                    >
                      resume
                    </button>
                  </div>
                ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
