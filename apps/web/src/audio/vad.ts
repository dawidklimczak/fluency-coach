import * as ort from "onnxruntime-web";

/**
 * Silero VAD w przeglądarce (spec 4.2) - wyłącznie wskaźnik "mówisz / cisza"
 * i auto-stop. Nie jest źródłem metryk (te liczy serwer z tego samego modelu).
 */
export class BrowserVad {
  private session: ort.InferenceSession;
  private h: ort.Tensor;
  private c: ort.Tensor;
  private sr: ort.Tensor;

  private constructor(session: ort.InferenceSession) {
    this.session = session;
    this.h = BrowserVad.zeroState();
    this.c = BrowserVad.zeroState();
    this.sr = new ort.Tensor("int64", BigInt64Array.from([16000n]), []);
  }

  private static zeroState(): ort.Tensor {
    return new ort.Tensor("float32", new Float32Array(2 * 64), [2, 1, 64]);
  }

  static async create(): Promise<BrowserVad> {
    ort.env.wasm.wasmPaths = "/ort/";
    ort.env.wasm.numThreads = 1;
    const session = await ort.InferenceSession.create("/models/silero_vad.onnx", {
      executionProviders: ["wasm"],
    });
    return new BrowserVad(session);
  }

  reset() {
    this.h = BrowserVad.zeroState();
    this.c = BrowserVad.zeroState();
  }

  /** Prawdopodobieństwo mowy dla ramki 512 próbek przy 16 kHz (~32 ms). */
  async processFrame(frame: Float32Array): Promise<number> {
    const input = new ort.Tensor("float32", frame, [1, frame.length]);
    const out = await this.session.run({
      input,
      sr: this.sr,
      h: this.h,
      c: this.c,
    });
    this.h = out.hn as ort.Tensor;
    this.c = out.cn as ort.Tensor;
    const prob = (out.output.data as Float32Array)[0];
    return prob;
  }
}
