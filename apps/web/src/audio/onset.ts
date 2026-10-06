import { Recorder } from "./recorder";
import { BrowserVad } from "./vad";

/**
 * Mierzy czas od startu nagrywania do pierwszej wykrytej mowy (Chunk Drill
 * Tryb A - dodatek v2: "czas od pojawienia się promptu do pierwszego dźwięku").
 * Nagranie jest odrzucane - w Trybie A treść nie jest oceniana, liczy się
 * tylko rt_ms.
 */
export async function measureReactionTimeMs(
  recorder: Recorder,
  vad: BrowserVad,
  maxMs = 3000
): Promise<number> {
  vad.reset();
  await recorder.start();
  const startPerf = performance.now();

  return new Promise((resolve) => {
    let resolved = false;
    let processing = false;
    const queue: Float32Array[] = [];

    const finish = (ms: number) => {
      if (resolved) return;
      resolved = true;
      recorder.onVadFrame = null;
      recorder.stop();
      resolve(ms);
    };

    const drain = async () => {
      processing = true;
      while (queue.length && !resolved) {
        const frame = queue.shift()!;
        const prob = await vad.processFrame(frame);
        if (prob > 0.5) {
          finish(performance.now() - startPerf);
          break;
        }
      }
      processing = false;
    };

    recorder.onVadFrame = (frame) => {
      queue.push(frame);
      if (!processing) drain();
    };

    setTimeout(() => finish(maxMs), maxMs);
  });
}
