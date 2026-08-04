// Zbiera surowy Float32 z wejścia mikrofonu i wysyła do wątku głównego.
// Żadnego przetwarzania sygnału - downsampling robi Recorder.
class RecorderProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch && ch.length > 0) {
      this.port.postMessage(ch.slice(0));
    }
    return true;
  }
}
registerProcessor("recorder-processor", RecorderProcessor);
