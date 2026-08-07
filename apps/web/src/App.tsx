import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  DrillConfig,
  LearningSessionState,
  LearningSessionSummary,
  TaskDto,
  UnauthorizedError,
} from "./api/client";
import { Recorder } from "./audio/recorder";
import { BrowserVad } from "./audio/vad";
import DrillScreen from "./drills/DrillScreen";
import { getTimeLimit } from "./settings";
import CalibrationScreen from "./screens/CalibrationScreen";
import LoginScreen from "./screens/LoginScreen";
import ObservationsScreen from "./screens/ObservationsScreen";
import ProgressScreen from "./screens/ProgressScreen";
import ReadingScreen from "./screens/ReadingScreen";
import SessionHub from "./screens/SessionHub";
import SessionSummaryScreen from "./screens/SessionSummaryScreen";
import SettingsScreen from "./screens/SettingsScreen";
import StartScreen from "./screens/StartScreen";
import StructuresScreen from "./screens/StructuresScreen";

type View =
  | { name: "loading" }
  | { name: "login" }
  | { name: "start" }
  | { name: "calibrate" }
  | { name: "settings" }
  | { name: "reading" }
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

  // wygaśnięcie sesji w dowolnym miejscu odsyła na ekran logowania,
  // zamiast pokazywać surowy błąd
  const handleError = useCallback((e: unknown) => {
    if (e instanceof UnauthorizedError) setView({ name: "login" });
    else setFatal(String(e));
  }, []);

  const refreshStart = useCallback(async () => {
    const [status, current] = await Promise.all([
      api.calibrationStatus(),
      api.learningSessionCurrent(),
    ]);
    setCalibrated(status.calibrated);
    setOpenSession(current.open ? (current as LearningSessionState) : null);
    setView({ name: "start" });
  }, []);

  const boot = useCallback(async () => {
    setView({ name: "loading" });
    try {
      const auth = await api.authState();
      if (!auth.authenticated) {
        setView({ name: "login" });
        return;
      }
      await refreshStart();
    } catch (e) {
      if (e instanceof UnauthorizedError) setView({ name: "login" });
      else setFatal(`Backend unavailable: ${e}`);
    }
  }, [refreshStart]);

  useEffect(() => {
    boot();
  }, [boot]);

  const openLearningSession = useCallback(async () => {
    setView({ name: "loading" });
    try {
      const session = await api.learningSessionStart();
      setView({ name: "hub", session });
    } catch (e) {
      handleError(e);
    }
  }, [handleError]);

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
      handleError(e);
    }
  }, [refreshStart, handleError]);

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
        // lokalne nadpisanie limitu czasu mówienia (ekran ustawień)
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
        handleError(e);
      }
    },
    [handleError]
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
        handleError(e);
      }
    },
    [backToHub, handleError]
  );

  const endLearningSession = useCallback(
    async (session: LearningSessionState) => {
      setView({ name: "loading" });
      try {
        const { summary } = await api.learningSessionEnd(session.id);
        setOpenSession(null);
        setView({ name: "sessionSummary", summary });
      } catch (e) {
        handleError(e);
      }
    },
    [handleError]
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
    case "login":
      return <LoginScreen onSuccess={boot} />;
    case "start":
      return (
        <StartScreen
          calibrated={calibrated}
          openSession={openSession}
          onOpenSession={openLearningSession}
          onCalibrate={() => setView({ name: "calibrate" })}
          onSettings={() => setView({ name: "settings" })}
          onReading={() => setView({ name: "reading" })}
          onProgress={() => setView({ name: "progress" })}
          onStructures={() => setView({ name: "structures" })}
          onObservations={() => setView({ name: "observations" })}
        />
      );
    case "settings":
      return (
        <SettingsScreen
          onBack={() => refreshStart().catch(handleError)}
          onLoggedOut={() => setView({ name: "login" })}
        />
      );
    case "reading":
      return <ReadingScreen onBack={() => refreshStart().catch(handleError)} />;
    case "progress":
      return <ProgressScreen onBack={() => refreshStart().catch(handleError)} />;
    case "structures":
      return <StructuresScreen onBack={() => refreshStart().catch(handleError)} />;
    case "observations":
      return <ObservationsScreen onBack={() => refreshStart().catch(handleError)} />;
    case "calibrate":
      return (
        <CalibrationScreen
          onDone={() => {
            setCalibrated(true);
            refreshStart().catch(handleError);
          }}
        />
      );
    case "hub":
      return (
        <SessionHub
          session={view.session}
          onStartDrill={(module, filter) => startDrill(view.session, module, filter)}
          onEndSession={() => endLearningSession(view.session)}
          onLeave={() => refreshStart().catch(handleError)}
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
        <SessionSummaryScreen
          summary={view.summary}
          onBack={() => refreshStart().catch(handleError)}
        />
      );
  }
}
