const assert = require('node:assert/strict');
const http = require('node:http');
const {WebSocket} = require('../web/node_modules/ws');
const {
    attachGeminiLive,
    normalizeExpression,
    preparePcmFrame,
    readGeminiKey,
} = require('../web/gemini-live-bridge');

function waitFor(check, timeoutMs = 2000) {
    const start = Date.now();
    return new Promise((resolve, reject) => {
        const poll = () => {
            const value = check();
            if (value) return resolve(value);
            if (Date.now() - start >= timeoutMs) return reject(new Error('Timed out waiting for bridge event'));
            setTimeout(poll, 10);
        };
        poll();
    });
}

(async () => {
    assert.equal(normalizeExpression('HAPPY'), 'happy');
    assert.equal(normalizeExpression('drive_forward'), 'neutral');
    assert.equal(readGeminiKey({env: {GEMINI_API_KEY: '  test-key  '}}), 'test-key');
    const digitalSilence = preparePcmFrame(Buffer.alloc(960));
    assert.equal(digitalSilence.some(byte => byte !== 0), true);
    assert.equal(Math.max(...new Int16Array(digitalSilence.buffer, digitalSilence.byteOffset, 480)), 1);
    const realPcm = Buffer.from([1, 0, 2, 0]);
    assert.deepEqual(preparePcmFrame(realPcm), realPcm);

    const server = http.createServer();
    const published = [];
    const mqtt = {
        connected: true,
        publish(topic, payload) { published.push({topic, payload}); },
    };
    const inputs = [];
    const toolResponses = [];
    let callbacks;
    let connectParams;
    let closed = false;
    let rejectInput = false;
    const fakeSession = {
        sendRealtimeInput(input) {
            inputs.push(input);
            if (rejectInput) return Promise.reject(new Error('socket already closed'));
        },
        sendToolResponse(response) { toolResponses.push(response); },
        close() { closed = true; },
    };
    const wss = attachGeminiLive(server, mqtt, {
        env: {GEMINI_API_KEY: 'unit-test-key'},
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
    const client = new WebSocket(`ws://127.0.0.1:${port}/live/ws?mode=native`, {
        origin: `http://127.0.0.1:${port}`,
    });
    const jsonMessages = [];
    const audioMessages = [];
    client.on('message', (data, binary) => {
        if (binary) audioMessages.push(Buffer.from(data));
        else jsonMessages.push(JSON.parse(data.toString()));
    });

    await waitFor(() => callbacks);
    callbacks.onmessage({setupComplete: {sessionId: 'test'}});
    await waitFor(() => jsonMessages.some(message => message.event === 'ready'));
    assert.equal(Object.hasOwn(connectParams.config, 'enableAffectiveDialog'), false);
    assert.equal(connectParams.config.responseModalities[0], 'AUDIO');

    client.send(Buffer.alloc(960), {binary: true});
    await waitFor(() => inputs.some(input => input.audio));
    assert.equal(inputs.find(input => input.audio).audio.mimeType, 'audio/pcm;rate=16000');
    assert.equal(Buffer.from(inputs.find(input => input.audio).audio.data, 'base64').some(byte => byte !== 0), true);

    callbacks.onmessage({
        toolCall: {functionCalls: [{id: 'call-1', name: 'set_expression', args: {expression: 'happy'}}]},
    });
    await waitFor(() => toolResponses.length === 1);
    assert.deepEqual(published.at(-1), {topic: 'panda/cmd/face', payload: 'happy'});
    assert.equal(toolResponses[0].functionResponses[0].id, 'call-1');

    const pcm = Buffer.from([0, 0, 1, 0]);
    callbacks.onmessage({
        serverContent: {modelTurn: {parts: [{inlineData: {mimeType: 'audio/pcm;rate=24000', data: pcm.toString('base64')}}]}},
    });
    await waitFor(() => audioMessages.length === 1);
    assert.deepEqual(audioMessages[0], pcm);

    callbacks.onmessage({serverContent: {turnComplete: true}});
    await waitFor(() => jsonMessages.some(message => message.event === 'turn_complete'));
    client.send(JSON.stringify({command: 'playback_complete'}));
    await waitFor(() => published.some(item => item.payload === 'neutral'));

    const closePromise = new Promise(resolve => client.once('close', resolve));
    rejectInput = true;
    client.send(Buffer.from([1, 0]), {binary: true});
    await waitFor(() => jsonMessages.some(message => message.code === 'gemini_send_error'));
    await closePromise;
    await waitFor(() => closed);
    assert.equal(closed, true);
    await new Promise(resolve => wss.close(resolve));
    await new Promise(resolve => server.close(resolve));
    console.log('Gemini Live bridge tests passed');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
