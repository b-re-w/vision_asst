/**
 * PCM capture worklet — runs on the dedicated audio thread (NOT the main/UI thread).
 *
 * Decimates the mic stream to 16 kHz mono and converts to Int16 PCM, posting each
 * ~80 ms chunk's ArrayBuffer back to the main thread (transferred, zero-copy). This
 * replaces the deprecated main-thread ScriptProcessorNode that was causing UI jank.
 */
class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.targetRate = 16000;
    this.ratio = sampleRate / this.targetRate; // e.g. 48000/16000 = 3
    this.phase = 0;
    this.chunk = 1280; // ~80 ms @ 16 kHz
    this.buf = new Float32Array(this.chunk);
    this.n = 0;
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.phase += 1;
      if (this.phase >= this.ratio) {
        this.phase -= this.ratio;
        this.buf[this.n++] = ch[i];
        if (this.n >= this.chunk) {
          const pcm = new Int16Array(this.chunk);
          for (let k = 0; k < this.chunk; k++) {
            pcm[k] = Math.max(-32768, Math.min(32767, this.buf[k] * 32768));
          }
          this.port.postMessage(pcm.buffer, [pcm.buffer]);
          this.n = 0;
        }
      }
    }
    return true; // keep the processor alive
  }
}

registerProcessor('pcm-capture', PcmCaptureProcessor);
