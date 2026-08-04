import { SAMPLE_RATE } from "./wav";

/**
 * Nagrywanie surowego audio (spec 4.1).
 *
 * getUserMedia z wyłączonym echoCancellation / noiseSuppression / autoGainControl
 * (wymóg twardy - przetwarzanie przeglądarki psuje energię sygnału i detekcję pauz).
 * AudioWorklet zbiera Float32 w częstotliwości kontekstu, Recorder downsampluje
 * strumieniowo do 16 kHz. t0 znaczone jako offset próbki w buforze (markT0),
 * nie zegarem systemowym.
 */
export class Recorder {
  private ctx: AudioContext;
  private stream: MediaStream;
  private node: AudioWorkletNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;

  private chunks: Float32Array[] = [];
  private recording = false;

  /** liczba próbek 16 kHz zebranych od start() */
  samplesRecorded = 0;

  /** callback z ramkami 512 próbek (16 kHz) do VAD na żywo */
  onVadFrame: ((frame: Float32Array) => void) | null = null;

  private vadBuf = new Float32Array(512);
  private vadFill = 0;

  // stan resamplera liniowego ctx.sampleRate -> 16 kHz
  private resamplePos = 0;
  private lastSample = 0;

  private constructor(ctx: AudioContext, stream: MediaStream) {
    this.ctx = ctx;
    this.stream = stream;
  }

  static async create(): Promise<Recorder> {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
        channelCount: 1,
      },
    });
    const ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
    await ctx.audioWorklet.addModule("/recorder-worklet.js");
    const rec = new Recorder(ctx, stream);
    rec.source = ctx.createMediaStreamSource(stream);
    rec.node = new AudioWorkletNode(ctx, "recorder-processor");
    rec.node.port.onmessage = (e: MessageEvent<Float32Array>) => rec.ingest(e.data);
    rec.source.connect(rec.node);
    // worklet nie potrzebuje wyjścia audio - nie podłączamy do destination
    return rec;
  }

  get deviceId(): string {
    return this.stream.getAudioTracks()[0]?.getSettings().deviceId ?? "";
  }

  private ingest(block: Float32Array) {
    if (!this.recording) return;
    const inRate = this.ctx.sampleRate;
    let out: Float32Array;
    if (inRate === SAMPLE_RATE) {
      out = block;
    } else {
      // resampling liniowy strumieniowy
      const ratio = inRate / SAMPLE_RATE;
      const produced: number[] = [];
      let pos = this.resamplePos;
      while (pos < block.length) {
        const i = Math.floor(pos);
        const frac = pos - i;
        const a = i === 0 ? this.lastSample : block[i - 1];
        const b = block[i];
        produced.push(a + (b - a) * frac);
        pos += ratio;
      }
      this.resamplePos = pos - block.length;
      this.lastSample = block[block.length - 1];
      out = new Float32Array(produced);
    }

    this.chunks.push(out.slice(0));
    this.samplesRecorded += out.length;

    if (this.onVadFrame) {
      let i = 0;
      while (i < out.length) {
        const take = Math.min(512 - this.vadFill, out.length - i);
        this.vadBuf.set(out.subarray(i, i + take), this.vadFill);
        this.vadFill += take;
        i += take;
        if (this.vadFill === 512) {
          this.onVadFrame(this.vadBuf.slice(0));
          this.vadFill = 0;
        }
      }
    }
  }

  async start() {
    if (this.ctx.state === "suspended") await this.ctx.resume();
    this.chunks = [];
    this.samplesRecorded = 0;
    this.vadFill = 0;
    this.resamplePos = 0;
    this.lastSample = 0;
    this.recording = true;
  }

  /** Wywołać w momencie pojawienia się bodźca. Zwraca t0 jako offset próbek. */
  markT0(): number {
    return this.samplesRecorded;
  }

  stop(): Float32Array {
    this.recording = false;
    const total = this.chunks.reduce((n, c) => n + c.length, 0);
    const out = new Float32Array(total);
    let off = 0;
    for (const c of this.chunks) {
      out.set(c, off);
      off += c.length;
    }
    this.chunks = [];
    return out;
  }

  async destroy() {
    this.recording = false;
    this.node?.disconnect();
    this.source?.disconnect();
    this.stream.getTracks().forEach((t) => t.stop());
    await this.ctx.close();
  }
}
