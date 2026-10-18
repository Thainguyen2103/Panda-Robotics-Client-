const assert = require('node:assert/strict');
const http = require('node:http');
const {WebSocket} = require('../web/node_modules/ws');
const {
    STT_LANGUAGES,
    attachGeminiTranscribe,
    wakeTail,
} = require('../web/gemini-transcribe-bridge');

function waitFor(check, timeoutMs = 2000) {
    const started = Date.now();
    return new Promise((resolve, reject) => {
        const poll = () => {
            const value = check();
            if (value) return resolve(value);
            if (Date.now() - started >= timeoutMs) return reject(new Error('Timed out waiting for STT bridge'));
            setTimeout(poll, 10);
        };
        poll();
    });
}

function openClient(port, mode) {
    const client = new WebSocket(`ws://127.0.0.1:${port}/transcribe/ws?mode=${mode}`, {
        origin: `http://127.0.0.1:${port}`,
    });
    const messages = [];
    client.on('message', data => messages.push(JSON.parse(data.toString())));
    return {client, messages};
}

(async () => {
    assert.equal(wakeTail('Moon ơi, nghe rõ không?'), 'nghe rõ không?');
    assert.equal(wakeTail('ねえ、ムーン！ 日本語を話して'), '日本語を話して');
    assert.equal(wakeTail('Môn Toán hôm nay khó'), null);
    assert.deepEqual(STT_LANGUAGES, ['vi-VN', 'en-US', 'ja-JP']);

    const server = http.createServer();
    const connections = [];
    const wss = attachGeminiTranscribe(server, {
        env: {GEMINI_API_KEY: 'unit-test-key'},
        createClient: () => ({
            live: {
                async connect(params) {
                    const inputs = [];
                    const session = {
                        sendRealtimeInput(input) { inputs.push(input); },
                        close() {},
                    };
                    connections.push({params, inputs, session});
                    queueMicrotask(() => params.callbacks.onopen());
                    return session;
                },
            },
        }),
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const port = server.address().port;

    const continuous = openClient(port, 'continuous');
    await waitFor(() => connections.length === 1);
    const first = connections[0];
    first.params.callbacks.onmessage({setupComplete: {sessionId: 'continuous'}});
    await waitFor(() => continuous.messages.some(message => message.event === 'ready'));
    assert.deepEqual(first.params.config.inputAudioTranscription.languageCodes, STT_LANGUAGES);
    assert.equal(first.params.config.inputAudioTranscription.mode, 'VERBATIM');
    assert(first.params.config.inputAudioTranscription.customVocabulary.includes('ムーン'));
    assert.equal(first.params.config.responseModalities[0], 'TEXT');

    first.params.callbacks.onmessage({voiceActivity: {voiceActivityType: 'ACTIVITY_START'}});
    first.params.callbacks.onmessage({
        serverContent: {interimInputTranscription: {text: '日本語を'}},
    });
    first.params.callbacks.onmessage({voiceActivity: {voiceActivityType: 'ACTIVITY_END'}});
    await waitFor(() => continuous.messages.some(message => message.event === 'partial'));
    assert.equal(continuous.messages.find(message => message.event === 'partial').text, '日本語を');

    continuous.client.send(Buffer.alloc(960), {binary: true});
    await waitFor(() => first.inputs.some(input => input.audio));
    const sentAudio = first.inputs.find(input => input.audio).audio;
    assert.equal(sentAudio.mimeType, 'audio/pcm;rate=16000');
    assert(Buffer.from(sentAudio.data, 'base64').some(byte => byte !== 0),
        'a browser frame gated to digital zero must still be sent as valid near-silence PCM');
    first.params.callbacks.onmessage({
        serverContent: {inputTranscription: {text: '日本語を勉強します。'}},
    });
    await waitFor(() => continuous.messages.some(message => message.event === 'question'));
    assert.equal(continuous.messages.find(message => message.event === 'question').text, '日本語を勉強します。');
    first.params.callbacks.onmessage({serverContent: {inputTranscription: {text: '   '}}});
    first.params.callbacks.onmessage({serverContent: {inputTranscription: {text: '日本語を勉強します。'}}});
    await new Promise(resolve => setTimeout(resolve, 30));
    assert.equal(continuous.messages.filter(message => message.event === 'question').length, 1,
        'empty and repeated final transcripts must not create extra Brain questions');

    const pausedInputCount = first.inputs.length;
    continuous.client.send(Buffer.alloc(960), {binary: true});
    await new Promise(resolve => setTimeout(resolve, 30));
    assert.equal(first.inputs.length, pausedInputCount, 'audio must stop while Brain answers');
    continuous.client.send(JSON.stringify({command: 'resume'}));
    await waitFor(() => continuous.messages.some(message => message.event === 'resumed'));
    continuous.client.send(Buffer.alloc(960), {binary: true});
    await waitFor(() => first.inputs.length > pausedInputCount);

    const wake = openClient(port, 'wake');
    await waitFor(() => connections.length === 2);
    const second = connections[1];
    second.params.callbacks.onmessage({setupComplete: {sessionId: 'wake'}});
    await waitFor(() => wake.messages.some(message => message.event === 'ready'));
    second.params.callbacks.onmessage({
        serverContent: {inputTranscription: {text: 'Môn Toán hôm nay khó'}},
    });
    await waitFor(() => wake.messages.some(message => message.event === 'ignored'));
    second.params.callbacks.onmessage({
        serverContent: {inputTranscription: {text: 'ムーン、日本語で話して'}},
    });
    const wakeEvent = await waitFor(() => wake.messages.find(message => message.event === 'wake'));
    assert.equal(wakeEvent.tail, '日本語で話して');

    const failingServer = http.createServer();
    const failingWss = attachGeminiTranscribe(failingServer, {
        env: {GEMINI_API_KEY: 'unit-test-key'},
        createClient: () => ({live: {connect: async () => { throw new Error('mock API unavailable'); }}}),
    });
    await new Promise(resolve => failingServer.listen(0, '127.0.0.1', resolve));
    const failing = openClient(failingServer.address().port, 'continuous');
    const failure = await waitFor(() => failing.messages.find(message => message.event === 'error'));
    assert.equal(failure.code, 'transcribe_connect_error');
    await new Promise(resolve => failingWss.close(resolve));
    await new Promise(resolve => failingServer.close(resolve));

    const closedServer = http.createServer();
    const closedSessions = [];
    const closedWss = attachGeminiTranscribe(closedServer, {
        env: {GEMINI_API_KEY: 'unit-test-key'},
        createClient: () => ({live: {connect: async params => {
            const session = {sendRealtimeInput() {}, close() {}};
            closedSessions.push({params, session});
            return session;
        }}}),
    });
    await new Promise(resolve => closedServer.listen(0, '127.0.0.1', resolve));
    const unexpectedlyClosed = openClient(closedServer.address().port, 'continuous');
    await waitFor(() => closedSessions.length === 1);
    closedSessions[0].params.callbacks.onmessage({setupComplete: {sessionId: 'close-test'}});
    await waitFor(() => unexpectedlyClosed.messages.some(message => message.event === 'ready'));
    closedSessions[0].params.callbacks.onclose({reason: 'mock socket closed'});
    const closeFailure = await waitFor(() => unexpectedlyClosed.messages.find(message => message.event === 'error'));
    assert.equal(closeFailure.code, 'transcribe_closed');
    unexpectedlyClosed.client.close();
    await new Promise(resolve => closedWss.close(resolve));
    await new Promise(resolve => closedServer.close(resolve));

    continuous.client.close();
    wake.client.close();
    await new Promise(resolve => setTimeout(resolve, 20));
    await new Promise(resolve => wss.close(resolve));
    await new Promise(resolve => server.close(resolve));
    console.log('Gemini Transcribe bridge: language config, transcript routing, deduplication and failure handling passed');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
