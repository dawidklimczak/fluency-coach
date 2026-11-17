import { Recorder } from "./recorder";
import { BrowserVad } from "./vad";

/**
 * Nagranie jednej krótkiej odpowiedzi: start od razu, koniec po ciszy.
 *
 * Koniec wypowiedzi wykrywa Silero VAD w przeglądarce (ten sam model co na
 * serwerze). Model reaguje na kształt mowy, a nie na głośność, więc działa też
 * z cichym mikrofonem. Stały próg energii (pierwsza wersja) nie łapał cichych
 * mikrofonów wcale. Gdy modelu nie da się wczytać, zostaje próg energii
 * dopasowany do szumu w pokoju.
 *
 * To, czy w nagraniu w ogóle była mowa, rozstrzyga serwer. `spoke` służy tylko
 * do sterowania nagraniem, nigdy do odrzucania odpowiedzi.
 */

const FRAME_S = 512 / 16000; // 32 ms
const SPEECH_PROB = 0.5;
const SILENCE_PROB = 0.35;
const MIN_SPEECH_FRAMES = 4; // ~130 ms mowy, zanim zaczniemy czekać na ciszę
const END_SILENCE_FRAMES = Math.round(1.4 / FRAME_S); // ~1.4 s ciszy po mowie kończy odpowiedź
// próg zapasowy (bez modelu): wielokrotność szumu, ale nie mniej niż absolutne minimum
const FALLBACK_MIN_RMS = 0.003;
const FALLBACK_NOISE_FACTOR = 3.5;
// skala wskaźnika: cichy mikrofon (RMS mowy ~0.01) ma zapalać połowę pasków
const METER_GAIN = 25;

export interface CaptureControl {
  /** ustaw na true, żeby zakończyć nagranie ręcznie */
  stop: boolean;
  /** ustaw na true, żeby porzucić nagranie (wynik: pusta tablica) */
  cancel: boolean;
}

export interface CaptureResult {
  samples: Float32Array;
  spoke: boolean;
}

export interface CaptureTick {
  secondsLeft: number;
  level: number;
  speaking: boolean;
}

function rms(frame: Float32Array): number {
  let sum = 0;
  for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
  return Math.sqrt(sum / frame.length);
}

export function meterLevel(rmsValue: number): number {
  return Math.min(1, Math.sqrt(rmsValue * METER_GAIN));
}

/** Wczytuje model VAD; null, gdy się nie da (wtedy capture używa progu energii). */
export async function loadVad(): Promise<BrowserVad | null> {
  try {
    return await BrowserVad.create();
  } catch (e) {
    console.warn("Browser VAD unavailable, falling back to an energy threshold", e);
    return null;
  }
}

export async function captureAnswer(
  recorder: Recorder,
  vad: BrowserVad | null,
  maxMs: number,
  control: CaptureControl,
  onTick?: (info: CaptureTick) => void
): Promise<CaptureResult> {
  let speechFrames = 0;
  let silentFrames = 0;
  let level = 0;
  let speaking = false;

  const classify = (isSpeech: boolean, isSilence: boolean) => {
    if (isSpeech) {
      speechFrames++;
      silentFrames = 0;
      speaking = true;
    } else {
      if (isSilence) speaking = false;
      if (speechFrames >= MIN_SPEECH_FRAMES && isSilence) {
        silentFrames++;
        if (silentFrames >= END_SILENCE_FRAMES) control.stop = true;
      }
    }
  };

  if (vad) {
    vad.reset();
    // ramki przychodzą szybciej, niż model czasem liczy - kolejka, jedna naraz
    const queue: Float32Array[] = [];
    let busy = false;
    const drain = async () => {
      busy = true;
      while (queue.length && !control.stop && !control.cancel) {
        const prob = await vad.processFrame(queue.shift()!);
        classify(prob >= SPEECH_PROB, prob < SILENCE_PROB);
      }
      busy = false;
    };
    recorder.onVadFrame = (frame) => {
      level = meterLevel(rms(frame));
      queue.push(frame);
      if (!busy) void drain();
    };
  } else {
    let noise = -1;
    recorder.onVadFrame = (frame) => {
      const value = rms(frame);
      level = meterLevel(value);
      // szum tła: szybko schodzi w dół (cisza), bardzo wolno rośnie (mowa go nie podbija)
      if (noise < 0) noise = value;
      else if (value < noise) noise = 0.7 * noise + 0.3 * value;
      else noise = 0.998 * noise + 0.002 * value;
      const threshold = Math.max(FALLBACK_MIN_RMS, noise * FALLBACK_NOISE_FACTOR);
      classify(value >= threshold, value < threshold);
    };
  }

  await recorder.start();
  const t0 = performance.now();
  await new Promise<void>((resolve) => {
    const tick = () => {
      const elapsed = performance.now() - t0;
      onTick?.({ secondsLeft: Math.max(0, Math.ceil((maxMs - elapsed) / 1000)), level, speaking });
      if (control.stop || control.cancel || elapsed >= maxMs) resolve();
      else requestAnimationFrame(tick);
    };
    tick();
  });
  recorder.onVadFrame = null;
  const samples = recorder.stop();
  if (control.cancel) return { samples: new Float32Array(0), spoke: false };
  return { samples, spoke: speechFrames >= MIN_SPEECH_FRAMES };
}
