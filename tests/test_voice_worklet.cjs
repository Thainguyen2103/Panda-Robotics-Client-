const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const code = fs.readFileSync(require('node:path').join(__dirname, '../web/public/voice-worklet.js'), 'utf8');
for (const rate of [16000, 44100, 48000]) {
    let Processor;
    const frames = [];
    const sandbox = {sampleRate: rate, AudioWorkletProcessor: class {
        constructor() { this.port = {postMessage(buffer) {frames.push(new Int16Array(buffer).slice());}}; }
    }, registerProcessor(name, cls) { Processor = cls; }};
    vm.runInNewContext(code, sandbox);
    const capture = new Processor();
    // 300ms, intentionally split into irregular blocks like browser render quanta.
    let remaining = rate * .3;
    while (remaining) {
        const n = Math.min(128, remaining);
        capture.process([[new Float32Array(n).fill(.25)]]);
        remaining -= n;
    }
    assert.equal(frames.length, 10, `exact frame count at ${rate}Hz`);
    assert(frames.every(f => f.length === 480 && f.every(v => Math.abs(v - 8192) <= 1)));
}
console.log('Voice worklet: 16/44.1/48kHz resampling and frame continuity passed');
