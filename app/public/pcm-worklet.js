// AudioWorklet: resample float32 mic input to PCM16 LE frames of 100 ms at 16 kHz.
class PcmWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this.frame = new Int16Array(1600);
    this.n = 0;
    this.step = sampleRate / 16000;
    this.pos = 0;
    this.last = 0;
  }
  push(value) {
    const s = Math.max(-1, Math.min(1, value));
    this.frame[this.n++] = s < 0 ? s * 0x8000 : s * 0x7fff;
    if (this.n === this.frame.length) {
      this.port.postMessage(this.frame.buffer, [this.frame.buffer]);
      this.frame = new Int16Array(1600);
      this.n = 0;
    }
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch && ch.length) {
      const buf = new Float32Array(ch.length + 1);
      buf[0] = this.last;
      buf.set(ch, 1);
      while (this.pos + 1 < buf.length) {
        const i = Math.floor(this.pos);
        const f = this.pos - i;
        this.push(buf[i] + (buf[i + 1] - buf[i]) * f);
        this.pos += this.step;
      }
      this.pos -= buf.length - 1;
      this.last = buf[buf.length - 1];
    }
    return true;
  }
}
registerProcessor('pcm-worklet', PcmWorklet);
