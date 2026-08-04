import { useCallback, useEffect, useRef, useState } from "react";
import { api, DrillConfig, SessionSummary, TaskDto } from "./api/client";
import { Recorder } from "./audio/recorder";
import { BrowserVad } from "./audio/vad";
import DrillScreen from "./drills/DrillScreen";
import CalibrationScreen from "./screens/CalibrationScreen";
import StartScreen from "./screens/StartScreen";
import SummaryScreen from "./screens/SummaryScreen";

type View =
  | { name: "start" }
  | { name: "calibrate" }
  | { name: "loading" }
  | {
      name: "drill";
      sessionId: number;
      firstTask: TaskDto;
      config: DrillConfig;
      recorder: Recorder;
      vad: BrowserVad;
      vadThreshold: number;
    }
  | { name: "summary"; summary: SessionSummary; fatigue: boolean };

export default function App() {
  const [view, setView] = useState<View>({ name: "loading" });
  const [calibrated, setCalibrated] = useState(false);
  const [fatal, setFatal] = useState<string | null>(null);
  const recorderRef = useRef<Recorder | null>(null);

  useEffect(() => {
    api
      .calibrationStatus()
      .then((s) => {
        setCalibrated(s.calibrated);
        setView({ name: "start" });
      })
      .catch((e) => setFatal(`Backend unavailable: ${e}`));
  }, []);

  const startSession = useCallback(async (module: string) => {
    setView({ name: "loading" });
    try {
      const [session, status, vad, recorder] = await Promise.all([
        api.createSession(module),
        api.calibrationStatus(),
        BrowserVad.create(),
        Recorder.create(),
      ]);
      recorderRef.current = recorder;
      setView({
        name: "drill",
        sessionId: session.session_id,
        firstTask: session.first_task,
        config: session.drill_config,
        recorder,
        vad,
        vadThreshold: status.vad_threshold,
      });
    } catch (e) {
      setFatal(String(e));
    }
  }, []);

  const endSession = useCallback(
    async (sessionId: number, reason: "completed" | "fatigue" | "aborted") => {
      setView({ name: "loading" });
      try {
        await recorderRef.current?.destroy();
        recorderRef.current = null;
        if (reason === "aborted") {
          // powrót do ekranu głównego bez podsumowania; sesję domykamy w tle
          api.endSession(sessionId).catch(() => {});
          setView({ name: "start" });
          return;
        }
        const { summary, fatigue_detected } = await api.endSession(sessionId);
        setView({ name: "summary", summary, fatigue: fatigue_detected });
      } catch (e) {
        setFatal(String(e));
      }
    },
    []
  );

  if (fatal) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-8">
        <p className="max-w-lg text-center text-red-400">{fatal}</p>
        <button className="btn" onClick={() => window.location.reload()}>
          Reload
        </button>
      </div>
    );
  }

  switch (view.name) {
    case "loading":
      return (
        <div className="flex min-h-screen items-center justify-center text-neutral-500">
          Loading...
        </div>
      );
    case "start":
      return (
        <StartScreen
          calibrated={calibrated}
          onStartSession={startSession}
          onCalibrate={() => setView({ name: "calibrate" })}
        />
      );
    case "calibrate":
      return (
        <CalibrationScreen
          onDone={() => {
            setCalibrated(true);
            setView({ name: "start" });
          }}
        />
      );
    case "drill":
      return (
        <DrillScreen
          sessionId={view.sessionId}
          firstTask={view.firstTask}
          config={view.config}
          vadThreshold={view.vadThreshold}
          recorder={view.recorder}
          vad={view.vad}
          onSessionEnd={(reason) => endSession(view.sessionId, reason)}
        />
      );
    case "summary":
      return (
        <SummaryScreen
          summary={view.summary}
          fatigue={view.fatigue}
          onBack={() => setView({ name: "start" })}
        />
      );
  }
}
