import { useCallback, useEffect, useState } from "react";
import { api, SessionSummary, UnauthorizedError } from "./api/client";
import BottleneckProfileScreen from "./screens/BottleneckProfileScreen";
import CalibrationScreen from "./screens/CalibrationScreen";
import ConversationScreen from "./screens/ConversationScreen";
import DiagnosticScreen from "./screens/DiagnosticScreen";
import LoginScreen from "./screens/LoginScreen";
import ProfileScreen from "./screens/ProfileScreen";
import ProgressScreen from "./screens/ProgressScreen";
import ReadingScreen from "./screens/ReadingScreen";
import RecoveryDrillScreen from "./screens/RecoveryDrillScreen";
import SelfTranscriptionScreen from "./screens/SelfTranscriptionScreen";
import SessionScreen from "./screens/SessionScreen";
import SessionSummaryScreen from "./screens/SessionSummaryScreen";
import SettingsScreen from "./screens/SettingsScreen";
import StartScreen from "./screens/StartScreen";

type View =
  | { name: "loading" }
  | { name: "login" }
  | { name: "start" }
  | { name: "calibrate" }
  | { name: "settings" }
  | { name: "profile" }
  | { name: "reading" }
  | { name: "progress" }
  | { name: "session" }
  | { name: "sessionSummary"; summary: SessionSummary }
  | { name: "selfTranscription"; sessionId: number }
  | { name: "diagnostic"; languageControlEnabled: boolean }
  | { name: "diagnosticNote"; note: string[] | null }
  | { name: "bottleneckProfile" }
  | { name: "recoveryDrill" }
  | { name: "conversation" };

export default function App() {
  const [view, setView] = useState<View>({ name: "loading" });
  const [calibrated, setCalibrated] = useState(false);
  const [fatal, setFatal] = useState<string | null>(null);

  const handleError = useCallback((e: unknown) => {
    if (e instanceof UnauthorizedError) setView({ name: "login" });
    else setFatal(String(e));
  }, []);

  const refreshStart = useCallback(async () => {
    const status = await api.calibrationStatus();
    setCalibrated(status.calibrated);
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
          onStartSession={() => setView({ name: "session" })}
          onCalibrate={() => setView({ name: "calibrate" })}
          onSettings={() => setView({ name: "settings" })}
          onProfile={() => setView({ name: "profile" })}
          onReading={() => setView({ name: "reading" })}
          onProgress={() => setView({ name: "progress" })}
          onDiagnostic={(languageControlEnabled) =>
            setView({ name: "diagnostic", languageControlEnabled })
          }
          onBottleneckProfile={() => setView({ name: "bottleneckProfile" })}
          onRecoveryDrill={() => setView({ name: "recoveryDrill" })}
          onConversation={() => setView({ name: "conversation" })}
        />
      );
    case "settings":
      return (
        <SettingsScreen
          onBack={() => refreshStart().catch(handleError)}
          onLoggedOut={() => setView({ name: "login" })}
        />
      );
    case "profile":
      return <ProfileScreen onBack={() => refreshStart().catch(handleError)} />;
    case "reading":
      return <ReadingScreen onBack={() => refreshStart().catch(handleError)} />;
    case "progress":
      return <ProgressScreen onBack={() => refreshStart().catch(handleError)} />;
    case "calibrate":
      return (
        <CalibrationScreen
          onDone={() => {
            setCalibrated(true);
            refreshStart().catch(handleError);
          }}
        />
      );
    case "session":
      return (
        <SessionScreen
          onDone={(summary) => setView({ name: "sessionSummary", summary })}
          onAbort={() => refreshStart().catch(handleError)}
        />
      );
    case "sessionSummary":
      return (
        <SessionSummaryScreen
          summary={view.summary}
          onBack={() => refreshStart().catch(handleError)}
          onSelfTranscription={() =>
            setView({ name: "selfTranscription", sessionId: view.summary.session_id })
          }
        />
      );
    case "selfTranscription":
      return (
        <SelfTranscriptionScreen
          sessionId={view.sessionId}
          onDone={() => refreshStart().catch(handleError)}
        />
      );
    case "diagnostic":
      return (
        <DiagnosticScreen
          languageControlEnabled={view.languageControlEnabled}
          onDone={(note) => setView({ name: "diagnosticNote", note })}
          onAbort={() => refreshStart().catch(handleError)}
        />
      );
    case "diagnosticNote":
      return (
        <div className="min-h-screen p-8">
          <div className="mx-auto flex max-w-xl flex-col gap-6">
            <h1 className="text-xl text-neutral-300">Diagnostic results</h1>
            {(view.note ?? []).map((line, i) => (
              <p key={i} className="text-neutral-300">
                {line}
              </p>
            ))}
            {(!view.note || view.note.length === 0) && (
              <p className="text-neutral-500">Nothing stands out yet - that's fine too.</p>
            )}
            <button className="btn self-start" onClick={() => refreshStart().catch(handleError)}>
              Back
            </button>
          </div>
        </div>
      );
    case "conversation":
      return <ConversationScreen onBack={() => refreshStart().catch(handleError)} />;
    case "bottleneckProfile":
      return <BottleneckProfileScreen onBack={() => refreshStart().catch(handleError)} />;
    case "recoveryDrill":
      return (
        <RecoveryDrillScreen
          onDone={() => refreshStart().catch(handleError)}
          onAbort={() => refreshStart().catch(handleError)}
        />
      );
  }
}
