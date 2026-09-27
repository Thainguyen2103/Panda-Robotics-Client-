// Integrate input samples into 16kHz bins; state survives render-block boundaries.
// This handles 44.1/48kHz devices without relying on requested AudioContext rate.
class MoonCapture extends AudioWorkletProcessor {
    constructor() {
        super();
        this.ratio = sampleRate / 16000;
        this.remaining = this.ratio;
        this.sum = 0;
        this.frame = new Int16Array(480);
        this.index = 0;
    }
    process(inputs) {
        const input = inputs[0]?.[0];
        if (!input) return true;
        for (const sample of input) {
            let weight = 1;
            while (weight > 1e-8) {
                const take = Math.min(weight, this.remaining);
                this.sum += sample * take;
                this.remaining -= take;
                weight -= take;
                if (this.remaining < 1e-8) {
                    this.frame[this.index++] = Math.round(Math.max(-1, Math.min(1, this.sum / this.ratio)) * 32767);
                    this.sum = 0;
                    this.remaining = this.ratio;
                    if (this.index === 480) {
                        this.port.postMessage(this.frame.buffer, [this.frame.buffer]);
                        this.frame = new Int16Array(480);
                        this.index = 0;
                    }
                }
            }
        }
        return true;
    }
}
registerProcessor('moon-capture', MoonCapture);
