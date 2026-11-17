interface Props {
  calibrated: boolean;
  onBack: () => void;
  onReading: () => void;
  onProfile: () => void;
  onSettings: () => void;
  onCalibrate: () => void;
  onSession: () => void;
  onConversation: () => void;
  onRecoveryDrill: () => void;
  onDiagnostic: () => void;
  onBottleneckProfile: () => void;
  onProgress: () => void;
}

function Row({ title, note, onClick }: { title: string; note: string; onClick: () => void }) {
  return (
    <button
      className="rounded-xl border border-neutral-800 px-5 py-3 text-left transition-colors hover:border-neutral-600"
      onClick={onClick}
    >
      <span className="text-neutral-200">{title}</span>
      <span className="mt-0.5 block text-sm text-neutral-500">{note}</span>
    </button>
  );
}

/** Wszystko poza codzienną ścieżką: narzędzia poboczne, ustawienia i stare moduły pomiarowe. */
export default function MoreScreen(p: Props) {
  return (
    <div className="mx-auto flex min-h-screen max-w-xl flex-col gap-8 p-6 sm:p-10">
      <div className="flex items-center justify-between">
        <p className="eyebrow">More</p>
        <button className="link" onClick={p.onBack}>
          back
        </button>
      </div>

      <section className="flex flex-col gap-2">
        <Row title="Reading pace trainer" note="read a text aloud, see where you speed up and slow down" onClick={p.onReading} />
        <Row title="About me" note="a few lines about your work and life, used to write your exercises" onClick={p.onProfile} />
        <Row title="Settings" note="OpenAI key, password" onClick={p.onSettings} />
      </section>

      <section className="flex flex-col gap-2">
        <p className="eyebrow">Lab</p>
        <p className="text-sm text-neutral-500">
          The older measuring tools. They still work, but they are not part of the daily round.
        </p>
        {p.calibrated ? (
          <Row title="Long fluency session" note="about 40 minutes: one topic told four times, then two probes" onClick={p.onSession} />
        ) : (
          <Row title="Calibrate the microphone" note="10 seconds of silence, needed before the long fluency session" onClick={p.onCalibrate} />
        )}
        <Row title="Live voice conversation" note="talks back in real time - billed per minute by OpenAI" onClick={p.onConversation} />
        <Row title="Recovery drill" note="practise picking a thread back up" onClick={p.onRecoveryDrill} />
        <Row title="Bottleneck diagnostic" note="is it prep, repetition or content that costs you most" onClick={p.onDiagnostic} />
        <Row title="Bottleneck profile" note="available after three diagnostics" onClick={p.onBottleneckProfile} />
        <Row title="Fluency charts" note="timing metrics from the long sessions" onClick={p.onProgress} />
        {p.calibrated && <Row title="Recalibrate the microphone" note="if the room or the microphone changed" onClick={p.onCalibrate} />}
      </section>
    </div>
  );
}
