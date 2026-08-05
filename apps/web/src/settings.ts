// Proste ustawienia lokalne: nadpisanie limitu czasu mówienia per moduł.
// Puste = domyślny limit z konfiguracji drilla na backendzie.

const KEY = "time_limit_overrides";

export function getTimeLimitOverrides(): Record<string, number> {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Record<string, number>) : {};
  } catch {
    return {};
  }
}

export function getTimeLimit(moduleId: string): number | null {
  const v = getTimeLimitOverrides()[moduleId];
  return typeof v === "number" && v > 0 ? v : null;
}

export function setTimeLimit(moduleId: string, seconds: number | null): void {
  const all = getTimeLimitOverrides();
  if (seconds == null || !(seconds > 0)) {
    delete all[moduleId];
  } else {
    all[moduleId] = Math.max(5, Math.min(300, Math.round(seconds)));
  }
  localStorage.setItem(KEY, JSON.stringify(all));
}
