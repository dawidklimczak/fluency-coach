import { useCallback, useEffect, useState } from "react";
import { api, SessionSummary, UnauthorizedError } from "./api/client";
import BottleneckProfileScreen from "./screens/BottleneckProfileScreen";
import CalibrationScreen from "./screens/CalibrationScreen";
import ConversationScreen from "./screens/ConversationScreen";
import DiagnosticScreen from "./screens/DiagnosticScreen";
import HomeScreen from "./screens/HomeScreen";
import LoginScreen from "./screens/LoginScreen";
import MapScreen from "./screens/MapScreen";
import MoreScreen from "./screens/MoreScreen";
import PracticeScreen from "./screens/PracticeScreen";
import ProfileScreen from "./screens/ProfileScreen";
import ProgressScreen from "./screens/ProgressScreen";
import ReadingScreen from "./screens/ReadingScreen";
import RecoveryDrillScreen from "./screens/RecoveryDrillScreen";
import SelfTranscriptionScreen from "./screens/SelfTranscriptionScreen";
import SessionScreen from "./screens/SessionScreen";
import SessionSummaryScreen from "./screens/SessionSummaryScreen";
import SettingsScreen from "./screens/SettingsScreen";
import ShadowScreen from "./screens/ShadowScreen";
import TalkScreen from "./screens/TalkScreen";

// Codzienna ścieżka: home -> practice (rundy gramatyczne) / shadow.
// Wszystko od "more" w dół to narzędzia poboczne i stare moduły pomiarowe.
type View =
  | { name: "loading" }
  | { name: "login" }
  | { name: "home" }
  | { name: "practice" }
  | { name: "shadow" }
  | { name: "map" }
  | { name: "talk" }
  | { name: "more" }
  | { name: "calibrate" }
  | { name: "settings"; from: "home" | "more" }
  | { name: "profile" }
  | { name: "reading" }
  | { name: "progress" }
  | { name: "session" }
  | { name: "sessionSummary"; summary: SessionSummary }
  | { name: "selfTranscription"; sessionId: number }
  | { name: "diagnostic" }
  | { name: "diagnosticNote"; note: string[] | null }
  | { name: "bottleneckProfile" }
  | { name: "recoveryDrill" }
  | { name: "conversation" };

export default function App() {
  const [view, setView] = useState<View>({ name: "loading" });
  const [calibrated, setCalibrated] = useState(false);
  const [fatal, setFatal] = useState<string | null>(null);

  const home = useCallback(() => setView({ name: "home" }), []);

  const more = useCallback(async () => {
    try {
      // kalibracji wymaga tylko stara długa sesja, więc sprawdzamy ją dopiero tutaj
      setCalibrated((await api.calibrationStatus()).calibrated);
      setView({ name: "more" });
    } catch (e) {
      if (e instanceof UnauthorizedError) setView({ name: "login" });
      else setFatal(String(e));
    }
  }, []);

  const boot = useCallback(async () => {
    setView({ name: "loading" });
    try {
      const auth = await api.authState();
      setView(auth.authenticated ? { name: "home" } : { name: "login" });
    } catch (e) {
      if (e instanceof UnauthorizedError) setView({ name: "login" });
      else setFatal(`Backend unavailable: ${e}`);
    }
  }, []);

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
      return <div className="flex min-h-screen items-center justify-center text-neutral-600">...</div>;
    case "login":
      return <LoginScreen onSuccess={boot} />;
    case "home":
      return (
        <HomeScreen
          onPractice={() => setView({ name: "practice" })}
          onShadow={() => setView({ name: "shadow" })}
          onMap={() => setView({ name: "map" })}
          onTalk={() => setView({ name: "talk" })}
          onMore={more}
          onSettings={() => setView({ name: "settings", from: "home" })}
        />
      );
    case "practice":
      return <PracticeScreen onDone={home} onShadow={() => setView({ name: "shadow" })} />;
    case "shadow":
      return <ShadowScreen onBack={home} onPractice={() => setView({ name: "practice" })} />;
    case "map":
      return <MapScreen onBack={home} />;
    case "talk":
      return <TalkScreen onBack={home} onPractice={() => setView({ name: "practice" })} />;
    case "more":
      return (
        <MoreScreen
          calibrated={calibrated}
          onBack={home}
          onReading={() => setView({ name: "reading" })}
          onProfile={() => setView({ name: "profile" })}
          onSettings={() => setView({ name: "settings", from: "more" })}
          onCalibrate={() => setView({ name: "calibrate" })}
          onSession={() => setView({ name: "session" })}
          onConversation={() => setView({ name: "conversation" })}
          onRecoveryDrill={() => setView({ name: "recoveryDrill" })}
          onDiagnostic={() => setView({ name: "diagnostic" })}
          onBottleneckProfile={() => setView({ name: "bottleneckProfile" })}
          onProgress={() => setView({ name: "progress" })}
        />
      );
    case "settings":
      return (
        <SettingsScreen
          onBack={view.from === "home" ? home : more}
          onLoggedOut={() => setView({ name: "login" })}
        />
      );
    case "profile":
      return <ProfileScreen onBack={more} />;
    case "reading":
      return <ReadingScreen onBack={more} />;
    case "progress":
      return <ProgressScreen onBack={more} />;
    case "calibrate":
      return <CalibrationScreen onDone={more} />;
    case "session":
      return (
        <SessionScreen
          onDone={(summary) => setView({ name: "sessionSummary", summary })}
          onAbort={more}
        />
      );
    case "sessionSummary":
      return (
        <SessionSummaryScreen
          summary={view.summary}
          onBack={more}
          onSelfTranscription={() =>
            setView({ name: "selfTranscription", sessionId: view.summary.session_id })
          }
        />
      );
    case "selfTranscription":
      return <SelfTranscriptionScreen sessionId={view.sessionId} onDone={more} />;
    case "diagnostic":
      return (
        <DiagnosticScreen
          languageControlEnabled={false}
          onDone={(note) => setView({ name: "diagnosticNote", note })}
          onAbort={more}
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
            <button className="btn self-start" onClick={more}>
              Back
            </button>
          </div>
        </div>
      );
    case "conversation":
      return <ConversationScreen onBack={more} />;
    case "bottleneckProfile":
      return <BottleneckProfileScreen onBack={more} />;
    case "recoveryDrill":
      return <RecoveryDrillScreen onDone={more} onAbort={more} />;
  }
}
