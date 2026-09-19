const assert = require('node:assert/strict');
const http = require('node:http');
const {WebSocket} = require('../web/node_modules/ws');
const {attachGeminiLive} = require('../web/gemini-live-bridge');

function waitFor(check, timeoutMs = 2000) {
    const start = Date.now();
    return new Promise((resolve, reject) => {
        const poll = () => {
            const value = check();
            if (value) return resolve(value);
            if (Date.now() - start >= timeoutMs) return reject(new Error('Timed out waiting for Fish bridge event'));
            setTimeout(poll, 10);
        };
        poll();
    });
}

(async () => {
    const server = http.createServer();
    let callbacks;
    let connectParams;
    let synthRequest;
    const fakeSession = {
        sendRealtimeInput() {},
        sendToolResponse() {},
        close() {},
    };
    const expectedAudio = Buffer.from('fake-fish-mp3');
    const wss = attachGeminiLive(server, {connected: false}, {
        env: {
            GEMINI_API_KEY: 'gemini-test-key',
            FISH_AUDIO_API_KEY: 'fish-test-key',
            FISH_VOICE_ID: 'fish-test-voice',
            FISH_LIVE_TTS_MODEL: 'fish-test-model',
        },
        synthesizeFish: async (text, config) => {
            synthRequest = {text, config};
            if (text === 'Câu dự phòng.' || text === 'Chỉ còn bản chữ.') throw new Error('Fish timeout');
            return expectedAudio;
        },
        createClient: () => ({
            live: {
                async connect(params) {
                    connectParams = params;
                    callbacks = params.callbacks;
                    queueMicrotask(() => callbacks.onopen());
                    return fakeSession;
                },
            },
        }),
    });

    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const port = server.address().port;
    const client = new WebSocket(`ws://127.0.0.1:${port}/live/ws?mode=fish`, {
        origin: `http://127.0.0.1:${port}`,
    });
    const jsonMessages = [];
    const audioMessages = [];
    client.on('message', (data, binary) => {
        if (binary) audioMessages.push(Buffer.from(data));
        else jsonMessages.push(JSON.parse(data.toString()));
    });

    await waitFor(() => callbacks);
    callbacks.onmessage({setupComplete: {sessionId: 'fish-test'}});
    await waitFor(() => jsonMessages.some(message => message.event === 'ready'));
    assert.equal(connectParams.config.responseModalities[0], 'AUDIO');
    assert.deepEqual(connectParams.config.outputAudioTranscription, {});
    assert.equal(jsonMessages.find(message => message.event === 'ready').outputMode, 'fish');

    const decodeFallbackPcm = Buffer.from([3, 0, 4, 0]);
    callbacks.onmessage({serverContent: {
        modelTurn: {parts: [{inlineData: {mimeType: 'audio/pcm;rate=24000', data: decodeFallbackPcm.toString('base64')}}]},
        outputTranscription: {text: 'Xin chào '},
    }});
    callbacks.onmessage({serverContent: {outputTranscription: {text: 'bạn.'}}});
    callbacks.onmessage({serverContent: {turnComplete: true}});
    await waitFor(() => audioMessages.length === 1);
    assert.equal(synthRequest.text, 'Xin chào bạn.');
    assert.equal(synthRequest.config.voiceId, 'fish-test-voice');
    assert.deepEqual(audioMessages[0], expectedAudio);
    assert.equal(jsonMessages.some(message => message.event === 'fish_synthesizing'), true);
    assert.equal(jsonMessages.some(message => message.event === 'turn_complete'), true);

    client.send(JSON.stringify({command: 'playback_failed'}));
    await waitFor(() => audioMessages.length === 2);
    assert.deepEqual(audioMessages[1], decodeFallbackPcm);

    const fallbackPcm = Buffer.from([0, 0, 1, 0, 2, 0]);
    callbacks.onmessage({serverContent: {
        modelTurn: {parts: [{inlineData: {mimeType: 'audio/pcm;rate=24000', data: fallbackPcm.toString('base64')}}]},
        outputTranscription: {text: 'Câu dự phòng.'},
    }});
    callbacks.onmessage({serverContent: {turnComplete: true}});
    await waitFor(() => audioMessages.length === 3);
    assert.deepEqual(audioMessages[2], fallbackPcm);
    assert.equal(jsonMessages.some(message => message.event === 'fish_fallback'), true);
    assert.equal(jsonMessages.some(message => message.event === 'speaking' && message.format === 'pcm'), true);

    callbacks.onmessage({serverContent: {outputTranscription: {text: 'Chỉ còn bản chữ.'}}});
    callbacks.onmessage({serverContent: {turnComplete: true}});
    const browserFallback = await waitFor(() => jsonMessages.find(message => message.event === 'browser_tts_fallback'));
    assert.equal(browserFallback.text, 'Chỉ còn bản chữ.');
    assert.match(browserFallback.reason, /Fish timeout/);

    await new Promise(resolve => {
        client.once('close', resolve);
        client.close();
    });
    await new Promise(resolve => wss.close(resolve));
    await new Promise(resolve => server.close(resolve));
    console.log('Gemini Live Fish bridge tests passed');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
