import { useState } from "react";
import { api } from "../api/client";

// Jedno pole - aplikacja jest jednoosobowa, więc nie ma loginu ani rejestracji.
export default function LoginScreen({ onSuccess }: { onSuccess: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const res = await api.login(password);
    setBusy(false);
    if (res.ok) onSuccess();
    else setError(res.error);
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-8">
      <form onSubmit={submit} className="flex w-full max-w-sm flex-col gap-4">
        <h1 className="text-center text-xl text-neutral-300">
          Speaking Automaticity Trainer
        </h1>
        <input
          type="password"
          autoFocus
          className="rounded border border-neutral-800 bg-neutral-950 px-4 py-3 text-neutral-100"
          placeholder="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && <p className="text-sm text-red-400">{error}</p>}
        <button className="btn" type="submit" disabled={busy || !password}>
          {busy ? "..." : "Enter"}
        </button>
      </form>
    </div>
  );
}
