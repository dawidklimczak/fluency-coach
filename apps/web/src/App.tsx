import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  DrillConfig,
  LearningSessionState,
  LearningSessionSummary,
  TaskDto,
} from "./api/client";
import { Recorder } from "./audio/recorder";
import { BrowserVad } from "./audio/vad";
import DrillScreen from "./drills/DrillScreen";
import { getTimeLimit } from "./settings";
import CalibrationScreen from "./screens/CalibrationScreen";
import ObservationsScreen from "./screens/ObservationsScreen";
import ProgressScreen from "./screens/ProgressScreen";
import SessionHub from "./screens/SessionHub";
import SessionSummaryScreen from "./screens/SessionSummaryScreen";
import StartScreen from "./screens/StartScreen";
import StructuresScreen from "./screens/StructuresScreen";

type View =
  | { name: "start" }
  | { name: "calibrate" }
  | { name: "loading" }
  | { name: "progress" }
  | { name: "structures" }
  | { name: "observations" }
  | { name: "hub"; session: LearningSessionState }
  | {
      name: "drill";
      learningSession: LearningSessionState;
      sessionId: number;
      firstTask: TaskDto;
      config: DrillConfig;
      recorder: Recorder;
      vad: BrowserVad;
      vadThreshold: number;
    }
  | { name: "sessionSummary"; summary: LearningSessionSummary };

export default function App() {
  const [view, setView] = useState<View>({ name: "loading" });
  const [calibrated, setCalibrated] = useState(false);
  const [openSession, setOpenSession] = useState<LearningSessionState | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);
  const recorderRef = useRef<Recorder | null>(null);

  const refreshStart = useCallback(async () => {
    const [status, current] = await Promise.all([
      api.calibrationStatus(),
      api.learningSessionCurrent(),
    ]);
    setCalibrated(status.calibrated);
    setOpenSession(current.open ? (current as LearningSessionState) : null);
    setView({ name: "start" });
  }, []);

  useEffect(() => {
    refreshStart().catch((e) => setFatal(`Backend unavailable: ${e}`));
  }, [refreshStart]);

  const openLearningSession = useCallback(async () => {
    setView({ name: "loading" });
    try {
      const session = await api.learningSessionStart();
      setView({ name: "hub", session });
    } catch (e) {
      setFatal(String(e));
    }
  }, []);

  const backToHub = useCallback(async () => {
    setView({ name: "loading" });
    try {
      const current = await api.learningSessionCurrent();
      if (current.open) {
        setView({ name: "hub", session: current as LearningSessionState });
      } else {
        await refreshStart();
      }
    } catch (e) {
      setFatal(String(e));
    }
  }, [refreshStart]);

  const startDrill = useCallback(
    async (
      learningSession: LearningSessionState,
      module: string,
      structureFilter: string | null
    ) => {
      setView({ name: "loading" });
      try {
        const [session, status, vad, recorder] = await Promise.all([
          api.createSession(module, structureFilter, learningSession.id),
          api.calibrationStatus(),
          BrowserVad.create(),
          Recorder.create(),
        ]);
        recorderRef.current = recorder;
        // lokalne nadpisanie limitu czasu mówienia (ustawienia na ekranie startu)
        const override = getTimeLimit(module);
        const config = override
          ? {
              ...session.drill_config,
              max_speak_s: override,
              min_speak_s: Math.min(session.drill_config.min_speak_s, override),
            }
          : session.drill_config;
        setView({
          name: "drill",
          learningSession,
          sessionId: session.session_id,
          firstTask: session.first_task,
          config,
          recorder,
          vad,
          vadThreshold: status.vad_threshold,
        });
      } catch (e) {
        setFatal(String(e));
      }
    },
    []
  );

  // koniec przebiegu drilla -> powrót do huba sesji (podsumowanie dopiero
  // przy zamknięciu całej sesji nauki)
  const endDrillRun = useCallback(
    async (sessionId: number) => {
      setView({ name: "loading" });
      try {
        await recorderRef.current?.destroy();
        recorderRef.current = null;
        api.endSession(sessionId).catch(() => {});
        await backToHub();
      } catch (e) {
        setFatal(String(e));
      }
    },
    [backToHub]
  );

  const endLearningSession = useCallback(async (session: LearningSessionState) => {
    setView({ name: "loading" });
    try {
      const { summary } = await api.learningSessionEnd(session.id);
      setOpenSession(null);
      setView({ name: "sessionSummary", summary });
    } catch (e) {
      setFatal(String(e));
    }
  }, []);

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
          openSession={openSession}
          onOpenSession={openLearningSession}
          onCalibrate={() => setView({ name: "calibrate" })}
          onProgress={() => setView({ name: "progress" })}
          onStructures={() => setView({ name: "structures" })}
          onObservations={() => setView({ name: "observations" })}
        />
      );
    case "progress":
      return <ProgressScreen onBack={() => refreshStart()} />;
    case "structures":
      return <StructuresScreen onBack={() => refreshStart()} />;
    case "observations":
      return <ObservationsScreen onBack={() => refreshStart()} />;
    case "calibrate":
      return (
        <CalibrationScreen
          onDone={() => {
            setCalibrated(true);
            refreshStart();
          }}
        />
      );
    case "hub":
      return (
        <SessionHub
          session={view.session}
          onStartDrill={(module, filter) => startDrill(view.session, module, filter)}
          onEndSession={() => endLearningSession(view.session)}
          onLeave={() => refreshStart()}
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
          onSessionEnd={() => endDrillRun(view.sessionId)}
        />
      );
    case "sessionSummary":
      return (
        <SessionSummaryScreen summary={view.summary} onBack={() => refreshStart()} />
      );
  }
}
