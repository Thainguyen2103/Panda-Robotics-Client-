const assert = require('node:assert/strict');
const {EventEmitter} = require('node:events');
const {Writable} = require('node:stream');
const {selectVoice, synthesizeEdge} = require('../web/edge-tts');

async function main() {
    assert.equal(selectVoice('こんにちは、ムーンです。'), 'ja-JP-NanamiNeural');
    assert.equal(selectVoice('Hello, I am Moon.'), 'en-US-AnaNeural');
    assert.equal(selectVoice('The word こんにちは means hello.'), 'en-US-AnaNeural');
    assert.equal(selectVoice('Chào bạn, mình là Moon.'), 'vi-VN-HoaiMyNeural');

    let request = '';
    const audio = Buffer.from('mock-mp3');
    const spawn = (command, args, options) => {
        assert.equal(command, 'python-test');
        assert.equal(args.at(-1).endsWith('server\\voice\\edge_tts_cli.py'), true);
        assert.deepEqual(options.stdio, ['pipe', 'pipe', 'pipe']);
        const child = new EventEmitter();
        child.stdout = new EventEmitter();
        child.stderr = new EventEmitter();
        child.kill = () => {};
        child.stdin = new Writable({
            write(chunk, _encoding, callback) {
                request += chunk.toString('utf8');
                callback();
            },
            final(callback) {
                process.nextTick(() => {
                    child.stdout.emit('data', audio);
                    child.emit('close', 0);
                });
                callback();
            },
        });
        return child;
    };
    const result = await synthesizeEdge('こんにちは', {python: 'python-test', spawn});
    assert.deepEqual(result, audio);
    assert.deepEqual(JSON.parse(request), {text: 'こんにちは', voice: 'ja-JP-NanamiNeural'});
    console.log('Edge TTS bridge tests passed');
}

main().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
