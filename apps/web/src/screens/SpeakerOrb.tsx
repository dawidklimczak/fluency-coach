import { MutableRefObject, useEffect, useRef } from "react";

interface Props {
  label: string;
  sublabel: string;
  /** bieżący poziom 0..1, aktualizowany poza Reactem (bez re-renderów) */
  levelRef: MutableRefObject<number>;
  active: boolean;
  /** kolor akcentu jako r,g,b */
  rgb: string;
}

/**
 * Krąg mówiącego: rdzeń skaluje się z głośnością, dwa pierścienie rozchodzą się
 * z opóźnieniem (jak fala), a nieaktywny krąg przygasa. Animacja idzie z
 * requestAnimationFrame i zapisuje styl bezpośrednio - 20 aktualizacji poziomu
 * na sekundę nie powinno przerysowywać drzewa Reacta.
 */
export default function SpeakerOrb({ label, sublabel, levelRef, active, rgb }: Props) {
  const core = useRef<HTMLDivElement>(null);
  const ring1 = useRef<HTMLDivElement>(null);
  const ring2 = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let raf = 0;
    let smooth = 0;
    let slow = 0;
    let slower = 0;
    const tick = () => {
      const target = levelRef.current;
      // szybki atak, wolne opadanie - jak miernik głośności
      smooth = target > smooth ? smooth + (target - smooth) * 0.5 : smooth * 0.92;
      slow += (smooth - slow) * 0.12;
      slower += (slow - slower) * 0.1;
      if (core.current) {
        core.current.style.transform = `scale(${1 + smooth * 0.35})`;
        core.current.style.boxShadow = `0 0 ${20 + smooth * 70}px ${smooth * 14}px rgba(${rgb}, ${0.15 + smooth * 0.5})`;
      }
      if (ring1.current) {
        ring1.current.style.transform = `scale(${1.15 + slow * 0.7})`;
        ring1.current.style.opacity = String(Math.min(0.6, slow * 1.1));
      }
      if (ring2.current) {
        ring2.current.style.transform = `scale(${1.3 + slower * 0.95})`;
        ring2.current.style.opacity = String(Math.min(0.4, slower * 0.8));
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [levelRef, rgb]);

  const color = `rgb(${rgb})`;
  return (
    <div
      className="flex flex-col items-center gap-6 transition-opacity duration-500"
      style={{ opacity: active ? 1 : 0.45 }}
    >
      <div className="relative flex h-40 w-40 items-center justify-center">
        <div
          ref={ring2}
          className="absolute inset-0 rounded-full border"
          style={{ borderColor: color, opacity: 0 }}
        />
        <div
          ref={ring1}
          className="absolute inset-0 rounded-full border-2"
          style={{ borderColor: color, opacity: 0 }}
        />
        <div
          ref={core}
          className="h-28 w-28 rounded-full"
          style={{
            background: `radial-gradient(circle at 35% 30%, rgba(${rgb}, 0.95), rgba(${rgb}, 0.35) 70%)`,
          }}
        />
      </div>
      <div className="text-center">
        <div className="text-lg text-neutral-200">{label}</div>
        <div className="h-5 text-sm text-neutral-500">{active ? sublabel : ""}</div>
      </div>
    </div>
  );
}
