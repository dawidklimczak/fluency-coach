import { api, ConversationWindow } from "../api/client";
import { Recorder } from "./recorder";
import { SAMPLE_RATE } from "./wav";

/**
 * Rozmowa GPT-Live przez WebRTC + równoległe surowe nagranie mikrofonu.
 *
 * Do WebRTC idzie osobny strumień z echoCancellation (inaczej rozmówca słyszałby
 * siebie), a do pomiarów Recorder bez przetwarzania - dlatego rozmowa wymaga
 * słuchawek: z głośnikami echo rozmówcy wpadłoby w surowe nagranie.
 *
 * Okna tur wykrywamy z energii dźwięku (głos rozmówcy: analyser na zdalnym
 * strumieniu, głos użytkownika: ramki Recordera), a nie ze zdarzeń kanału
 * danych - ich schemat nie jest w publicznej dokumentacji. Serwer i tak robi
 * własny VAD, więc te progi tylko wyznaczają granice okien.
 */

const AI_RMS_THRESHOLD = 0.01;
const USER_RMS_THRESHOLD = 0.02;
const AI_SILENCE_END_MS = 400; // tyle ciszy rozmówcy = koniec jego wypowiedzi
const USER_TAIL_S = 0.5; // zapas po ostatnim dźwięku użytkownika w turze

export interface LiveCallbacks {
  onAiSpeaking: (speaking: boolean) => void;
  onUserSpeaking: (speaking: boolean) => void;
  /** poziom głośności 0..1 (do wizualizacji), wołane ~20x/s dla rozmówcy i na każdą ramkę dla użytkownika */
  onAiLevel?: (level: number) => void;
  onUserLevel?: (level: number) => void;
  onTimeout: () => void;
  onError: (message: string) => void;
}

export interface LiveResult {
  wav: Float32Array;
  turns: ConversationWindow[];
  billedSeconds: number | null;
}

function rms(frame: Float32Array): number {
  let s = 0;
  for (let i = 0; i < frame.length; i++) s += frame[i] * frame[i];
  return Math.sqrt(s / frame.length);
}

/** RMS mowy to ~0.02-0.2; pierwiastek spłaszcza skalę, żeby ciche słowa też było widać. */
function toVisualLevel(rmsValue: number): number {
  return Math.min(1, Math.sqrt(rmsValue * 5));
}

export class LiveConversation {
  sessionId = 0;

  private pc: RTCPeerConnection | null = null;
  private channel: RTCDataChannel | null = null;
  private rtcStream: MediaStream | null = null;
  private recorder: Recorder | null = null;
  private audioEl: HTMLAudioElement | null = null;
  private analyserCtx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private poll: number | null = null;
  private timeout: number | null = null;

  private aiSpeaking = false;
  private aiSilentSince = 0;
  private userSpeaking = false;
  private turnStart: number | null = null; // t0 bieżącego okna (s w nagraniu)
  private lastUserSound = 0;
  private turns: ConversationWindow[] = [];
  private billedSeconds: number | null = null;
  private closedResolve: (() => void) | null = null;

  constructor(private cb: LiveCallbacks) {}

  private nowS(): number {
    return (this.recorder?.samplesRecorded ?? 0) / SAMPLE_RATE;
  }

  async start(persona: string, maxMinutes: number): Promise<void> {
    this.recorder = await Recorder.create();
    this.recorder.onVadFrame = (f) => this.onUserFrame(f);

    this.rtcStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
    });

    const pc = new RTCPeerConnection();
    this.pc = pc;
    this.audioEl = new Audio();
    this.audioEl.autoplay = true;

    const started = new Promise<void>((resolve, reject) => {
      const t = window.setTimeout(() => reject(new Error("Połączenie z rozmówcą nie powiodło się")), 20000);
      const channel = pc.createDataChannel("oai-events");
      this.channel = channel;
      channel.onmessage = (e) => {
        let ev: { type?: string; usage?: { duration_seconds?: number } };
        try {
          ev = JSON.parse(e.data);
        } catch {
          return;
        }
        if (ev.type === "session.started") {
          window.clearTimeout(t);
          resolve();
        } else if (ev.type === "session.closed") {
          const d = ev.usage?.duration_seconds;
          this.billedSeconds = typeof d === "number" ? d : null;
          this.closedResolve?.();
        }
      };
      channel.onclose = () => this.closedResolve?.();
    });

    pc.ontrack = (e) => {
      const remote = e.streams[0];
      if (this.audioEl) this.audioEl.srcObject = remote;
      this.attachAnalyser(remote);
    };
    this.rtcStream.getAudioTracks().forEach((tr) => pc.addTrack(tr, this.rtcStream!));

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await this.waitForIce(pc);

    const res = await api.startConversation(pc.localDescription!.sdp, persona, maxMinutes);
    this.sessionId = res.session_id;
    await pc.setRemoteDescription({ type: "answer", sdp: res.sdp_answer });
    await started;

    await this.recorder.start();
    this.poll = window.setInterval(() => this.pollAi(), 50);
    // zamykanie rozmowy po stronie klienta - model nie zawsze kończy sam
    this.timeout = window.setTimeout(() => this.cb.onTimeout(), res.max_minutes * 60_000);
  }

  private waitForIce(pc: RTCPeerConnection): Promise<void> {
    if (pc.iceGatheringState === "complete") return Promise.resolve();
    return new Promise((resolve) => {
      const done = () => {
        if (pc.iceGatheringState === "complete") {
          pc.removeEventListener("icegatheringstatechange", done);
          resolve();
        }
      };
      pc.addEventListener("icegatheringstatechange", done);
      window.setTimeout(resolve, 3000);
    });
  }

  private attachAnalyser(stream: MediaStream) {
    const ctx = new AudioContext();
    const src = ctx.createMediaStreamSource(stream);
    const an = ctx.createAnalyser();
    an.fftSize = 1024;
    src.connect(an);
    this.analyserCtx = ctx;
    this.analyser = an;
  }

  private pollAi() {
    if (!this.analyser) return;
    const buf = new Float32Array(this.analyser.fftSize);
    this.analyser.getFloatTimeDomainData(buf);
    const level = rms(buf);
    this.cb.onAiLevel?.(toVisualLevel(level));
    const loud = level > AI_RMS_THRESHOLD;
    const now = performance.now();

    if (loud) {
      this.aiSilentSince = 0;
      if (!this.aiSpeaking) {
        this.aiSpeaking = true;
        this.cb.onAiSpeaking(true);
        this.closeWindow(); // rozmówca zaczął mówić - okno użytkownika się kończy
      }
    } else if (this.aiSpeaking) {
      if (this.aiSilentSince === 0) this.aiSilentSince = now;
      if (now - this.aiSilentSince >= AI_SILENCE_END_MS) {
        this.aiSpeaking = false;
        this.cb.onAiSpeaking(false);
        // koniec wypowiedzi rozmówcy = t0 okna (cofamy o czas ciszy użyty do detekcji)
        this.turnStart = Math.max(0, this.nowS() - AI_SILENCE_END_MS / 1000);
        this.lastUserSound = 0;
      }
    }
  }

  private onUserFrame(frame: Float32Array) {
    const level = rms(frame);
    this.cb.onUserLevel?.(toVisualLevel(level));
    const speaking = level > USER_RMS_THRESHOLD;
    if (speaking) this.lastUserSound = this.nowS();
    if (speaking !== this.userSpeaking) {
      this.userSpeaking = speaking;
      this.cb.onUserSpeaking(speaking);
    }
  }

  /** Zamyka okno tury; pomija okna bez żadnego dźwięku użytkownika. */
  private closeWindow() {
    if (this.turnStart === null) return;
    const start = this.turnStart;
    this.turnStart = null;
    if (this.lastUserSound > start) {
      this.turns.push({ start_s: start, end_s: this.lastUserSound + USER_TAIL_S });
    }
  }

  /** Kończy rozmowę: session.close, zwrot nagrania, okien tur i czasu rozliczeniowego. */
  async finish(): Promise<LiveResult> {
    if (this.timeout) window.clearTimeout(this.timeout);
    if (this.poll) window.clearInterval(this.poll);
    this.closeWindow();

    const closed = new Promise<void>((resolve) => {
      this.closedResolve = resolve;
      window.setTimeout(resolve, 5000);
    });
    if (this.channel?.readyState === "open") this.channel.send(JSON.stringify({ type: "session.close" }));
    await closed;

    const wav = this.recorder ? this.recorder.stop() : new Float32Array(0);
    await this.teardown();
    return { wav, turns: this.turns, billedSeconds: this.billedSeconds };
  }

  async abort() {
    if (this.timeout) window.clearTimeout(this.timeout);
    if (this.poll) window.clearInterval(this.poll);
    this.channel?.close();
    await this.teardown();
  }

  private async teardown() {
    this.pc?.close();
    this.rtcStream?.getTracks().forEach((t) => t.stop());
    if (this.audioEl) this.audioEl.srcObject = null;
    await this.analyserCtx?.close().catch(() => {});
    await this.recorder?.destroy().catch(() => {});
    this.pc = null;
    this.recorder = null;
  }
}
