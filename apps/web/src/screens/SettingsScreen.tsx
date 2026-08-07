import { useEffect, useState } from "react";
import { api, InstanceSettings, ModuleInfo } from "../api/client";
import { getTimeLimitOverrides, setTimeLimit } from "../settings";

interface Props {
  onBack: () => void;
  onLoggedOut: () => void;
}

export default function SettingsScreen({ onBack, onLoggedOut }: Props) {
  const [settings, setSettings] = useState<InstanceSettings | null>(null);
  const [modules, setModules] = useState<ModuleInfo[]>([]);
  const [overrides, setOverrides] = useState<Record<string, number>>(
    getTimeLimitOverrides()
  );

  const [apiKey, setApiKey] = useState("");
  const [keyMsg, setKeyMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [keyBusy, setKeyBusy] = useState(false);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [pwMsg, setPwMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = () => api.settings().then(setSettings).catch(() => {});

  useEffect(() => {
    load();
    api.modules().then(setModules).catch(() => {});
  }, []);

  const saveKey = async () => {
    setKeyBusy(true);
    setKeyMsg(null);
    try {
      await api.setOpenAiKey(apiKey);
      setApiKey("");
      setKeyMsg({ ok: true, text: "Key saved and verified against OpenAI." });
      load();
    } catch (e) {
      setKeyMsg({ ok: false, text: String(e instanceof Error ? e.message : e) });
    } finally {
      setKeyBusy(false);
    }
  };

  const savePassword = async () => {
    setPwMsg(null);
    try {
      await api.setPassword(newPassword, currentPassword || null);
      setCurrentPassword("");
      setNewPassword("");
      setPwMsg({ ok: true, text: "Password updated." });
      load();
    } catch (e) {
      setPwMsg({ ok: false, text: String(e instanceof Error ? e.message : e) });
    }
  };

  return (
    <div className="min-h-screen p-8">
      <div className="mx-auto flex max-w-xl flex-col gap-10">
        <div className="flex items-center justify-between">
          <h1 className="text-xl text-neutral-300">Settings</h1>
          <button className="text-sm text-neutral-500 underline" onClick={onBack}>
            back
          </button>
        </div>

        <section className="flex flex-col gap-3">
          <h2 className="text-sm uppercase tracking-wide text-neutral-500">
            OpenAI API key
          </h2>
          {settings?.openai_key_set ? (
            <p className="text-sm text-neutral-400">
              Set: <span className="font-mono">{settings.openai_key_hint}</span>
              {settings.openai_key_from_env && " (from environment variable)"}
            </p>
          ) : (
            <p className="text-sm text-amber-400">
              Not set - transcription and feedback are unavailable without it.
            </p>
          )}
          <input
            type="password"
            className="rounded border border-neutral-800 bg-neutral-950 px-4 py-2 font-mono text-neutral-100"
            placeholder="sk-..."
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
          {keyMsg && (
            <p className={`text-sm ${keyMsg.ok ? "text-emerald-400" : "text-red-400"}`}>
              {keyMsg.text}
            </p>
          )}
          <button
            className="btn self-start"
            onClick={saveKey}
            disabled={keyBusy || !apiKey}
          >
            {keyBusy ? "checking..." : "Save key"}
          </button>
          <p className="text-xs text-neutral-600">
            The key is stored on this instance only and is never sent anywhere
            except OpenAI. Create one at platform.openai.com/api-keys.
          </p>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-sm uppercase tracking-wide text-neutral-500">Password</h2>
          <p className="text-sm text-neutral-400">
            {settings?.password_set
              ? "This instance is password protected."
              : "No password set - this instance only accepts connections from this computer."}
          </p>
          {settings?.password_set && (
            <input
              type="password"
              className="rounded border border-neutral-800 bg-neutral-950 px-4 py-2 text-neutral-100"
              placeholder="current password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
            />
          )}
          <input
            type="password"
            className="rounded border border-neutral-800 bg-neutral-950 px-4 py-2 text-neutral-100"
            placeholder="new password (min 8 characters)"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
          />
          {pwMsg && (
            <p className={`text-sm ${pwMsg.ok ? "text-emerald-400" : "text-red-400"}`}>
              {pwMsg.text}
            </p>
          )}
          <button
            className="btn self-start"
            onClick={savePassword}
            disabled={newPassword.length < 8}
          >
            Save password
          </button>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-sm uppercase tracking-wide text-neutral-500">
            Speaking time limits
          </h2>
          <p className="text-xs text-neutral-600">
            Seconds per attempt; empty means the module default. Story Loop rounds
            scale proportionally.
          </p>
          <div className="flex flex-col gap-2">
            {modules.map((m) => (
              <label
                key={m.id}
                className="flex items-center justify-between text-sm text-neutral-400"
              >
                <span>{m.name}</span>
                <input
                  type="number"
                  min={5}
                  max={300}
                  className="w-24 rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-right font-mono text-neutral-200"
                  placeholder={String(m.max_speak_s)}
                  value={overrides[m.id] ?? ""}
                  onChange={(e) => {
                    const v = e.target.value === "" ? null : Number(e.target.value);
                    setTimeLimit(m.id, v);
                    setOverrides(getTimeLimitOverrides());
                  }}
                />
              </label>
            ))}
          </div>
        </section>

        {settings?.password_set && (
          <button
            className="self-start text-sm text-neutral-500 underline"
            onClick={async () => {
              await api.logout();
              onLoggedOut();
            }}
          >
            log out
          </button>
        )}
      </div>
    </div>
  );
}
