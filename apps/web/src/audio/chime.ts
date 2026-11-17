import { SAMPLE_RATE } from "./wav";

/** Krótkie dźwięki interfejsu i odtwarzanie własnego nagrania. Jeden kontekst na całą aplikację. */

let ctx: AudioContext | null = null;

function context(): AudioContext {
  if (!ctx) ctx = new AudioContext();
  if (ctx.state === "suspended") void ctx.resume();
  return ctx;
}

function tone(freq: number, startS: number, durationS: number, gain: number) {
  const c = context();
  const osc = c.createOscillator();
  const g = c.createGain();
  osc.type = "sine";
  osc.frequency.value = freq;
  const t = c.currentTime + startS;
  g.gain.setValueAtTime(0, t);
  g.gain.linearRampToValueAtTime(gain, t + 0.015);
  g.gain.exponentialRampToValueAtTime(0.0001, t + durationS);
  osc.connect(g).connect(c.destination);
  osc.start(t);
  osc.stop(t + durationS + 0.02);
}

export function chimeCorrect() {
  tone(660, 0, 0.16, 0.07);
  tone(990, 0.09, 0.26, 0.07);
}

export function chimeLevelUp() {
  tone(523, 0, 0.14, 0.07);
  tone(659, 0.1, 0.14, 0.07);
  tone(784, 0.2, 0.34, 0.08);
}

export function chimeSoft() {
  tone(330, 0, 0.22, 0.05);
}

/** Odtwarza wycinek nagrania 16 kHz; zwraca obietnicę, która kończy się razem z dźwiękiem. */
export function playSamples(samples: Float32Array, fromS = 0, toS?: number): Promise<void> {
  const c = context();
  const start = Math.max(0, Math.floor(fromS * SAMPLE_RATE));
  const end = Math.min(samples.length, toS === undefined ? samples.length : Math.ceil(toS * SAMPLE_RATE));
  if (end - start < SAMPLE_RATE * 0.1) return Promise.resolve();
  const buffer = c.createBuffer(1, end - start, SAMPLE_RATE);
  buffer.getChannelData(0).set(samples.subarray(start, end));
  const src = c.createBufferSource();
  src.buffer = buffer;
  src.connect(c.destination);
  return new Promise((resolve) => {
    src.onended = () => resolve();
    src.start();
  });
}
