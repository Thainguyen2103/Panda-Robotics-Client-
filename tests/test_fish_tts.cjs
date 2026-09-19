const assert = require('node:assert/strict');
const {readFishConfig, synthesizeFish, synthesizeFishWithRetry, FISH_TTS_URL} = require('../web/fish-tts');

(async () => {
    const config = readFishConfig({
        env: {
            FISH_AUDIO_API_KEY: 'test-key',
            FISH_VOICE_ID: 'test-voice',
            FISH_LIVE_TTS_MODEL: 'test-model',
        },
        settingsPath: 'missing-settings.py',
    });
    assert.deepEqual(config, {apiKey: 'test-key', voiceId: 'test-voice', model: 'test-model'});

    let request;
    const expected = Buffer.from('fake-mp3');
    const audio = await synthesizeFish(' Xin chào Moon ', config, {
        fetchImpl: async (url, options) => {
            request = {url, options};
            return {
                ok: true,
                status: 200,
                async arrayBuffer() { return expected; },
            };
        },
    });

    assert.equal(request.url, FISH_TTS_URL);
    assert.equal(request.options.headers.Authorization, 'Bearer test-key');
    assert.equal(request.options.headers.model, 'test-model');
    assert.deepEqual(JSON.parse(request.options.body), {
        text: 'Xin chào Moon',
        reference_id: 'test-voice',
        format: 'mp3',
        latency: 'balanced',
        normalize: true,
    });
    assert.deepEqual(audio, expected);

    await assert.rejects(() => synthesizeFish('Xin chào', config, {
        fetchImpl: async () => ({ok: false, status: 422, async text() { return 'invalid model'; }}),
    }), /Fish Audio từ chối yêu cầu \(422\): invalid model/);

    let attempts = 0;
    const retriedAudio = await synthesizeFishWithRetry('Thử lại', config, {
        retryDelayMs: 1,
        timeoutMs: 1000,
        synthesize: async () => {
            attempts++;
            if (attempts === 1) throw new Error('network timeout');
            return expected;
        },
    });
    assert.equal(attempts, 2);
    assert.deepEqual(retriedAudio, expected);

    attempts = 0;
    await assert.rejects(() => synthesizeFishWithRetry('Không retry 422', config, {
        synthesize: async () => {
            attempts++;
            throw new Error('Fish Audio từ chối yêu cầu (422): invalid model');
        },
    }), /422/);
    assert.equal(attempts, 1);
    console.log('Fish TTS tests passed');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
