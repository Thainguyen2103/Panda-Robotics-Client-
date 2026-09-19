const fs = require('fs');
const path = require('path');

const FISH_TTS_URL = 'https://api.fish.audio/v1/tts';
const DEFAULT_FISH_MODEL = 's2.1-pro-free';

function readAssignment(source, name) {
    const pattern = new RegExp(`^\\s*${name}\\s*=\\s*["']([^"']+)["']`, 'm');
    return source.match(pattern)?.[1]?.trim() || '';
}

function readFishConfig(options = {}) {
    const env = options.env || process.env;
    const config = {
        apiKey: String(env.FISH_AUDIO_API_KEY || '').trim(),
        voiceId: String(env.FISH_VOICE_ID || '').trim(),
        model: String(env.FISH_LIVE_TTS_MODEL || env.FISH_TTS_MODEL || '').trim(),
    };

    const projectRoot = options.projectRoot || path.resolve(__dirname, '..');
    if (!config.apiKey) {
        try {
            const secrets = fs.readFileSync(options.secretsPath || path.join(projectRoot, 'config', 'secrets.py'), 'utf8');
            config.apiKey = secrets.match(/["']FISH_AUDIO_API_KEY["']\s*:\s*["']([^"']+)["']/)?.[1]?.trim() || '';
        } catch (_) {}
    }

    try {
        const settings = fs.readFileSync(options.settingsPath || path.join(projectRoot, 'config', 'settings.py'), 'utf8');
        if (!config.voiceId) config.voiceId = readAssignment(settings, 'FISH_VOICE_ID');
        if (!config.model) config.model = readAssignment(settings, 'FISH_TTS_MODEL');
    } catch (_) {}

    if (!config.model) config.model = DEFAULT_FISH_MODEL;
    return config;
}

async function synthesizeFish(text, config, options = {}) {
    const cleanText = String(text || '').trim().slice(0, 4000);
    if (!cleanText) throw new Error('Moon chưa tạo được nội dung để đọc.');
    if (!config?.apiKey) throw new Error('Chưa có FISH_AUDIO_API_KEY.');
    if (!config?.voiceId) throw new Error('Chưa có FISH_VOICE_ID.');

    const fetchImpl = options.fetchImpl || globalThis.fetch;
    if (typeof fetchImpl !== 'function') throw new Error('Phiên bản Node.js chưa hỗ trợ Fish Audio HTTP.');

    const response = await fetchImpl(options.url || FISH_TTS_URL, {
        method: 'POST',
        headers: {
            Authorization: `Bearer ${config.apiKey}`,
            'Content-Type': 'application/json',
            model: config.model || DEFAULT_FISH_MODEL,
        },
        body: JSON.stringify({
            text: cleanText,
            reference_id: config.voiceId,
            format: 'mp3',
            latency: 'balanced',
            normalize: true,
        }),
        signal: options.signal,
    });

    if (!response.ok) {
        let detail = '';
        try { detail = String(await response.text()).replace(/\s+/g, ' ').trim().slice(0, 240); } catch (_) {}
        throw new Error(`Fish Audio từ chối yêu cầu (${response.status})${detail ? `: ${detail}` : '.'}`);
    }

    const audio = Buffer.from(await response.arrayBuffer());
    if (audio.length === 0) throw new Error('Fish Audio trả về tệp âm thanh rỗng.');
    return audio;
}

function retryableFishError(error) {
    const status = Number(String(error?.message || '').match(/\((\d{3})\)/)?.[1] || 0);
    return !status || status === 408 || status === 429 || status >= 500;
}

async function synthesizeFishWithRetry(text, config, options = {}) {
    const synthesize = options.synthesize || synthesizeFish;
    const attempts = Math.max(1, Number(options.attempts) || 2);
    const timeoutMs = Math.max(1000, Number(options.timeoutMs) || 15000);
    const retryDelayMs = Math.max(0, Number(options.retryDelayMs) || 350);
    const parentSignal = options.signal;
    let lastError;

    for (let attempt = 1; attempt <= attempts; attempt++) {
        if (parentSignal?.aborted) throw Object.assign(new Error('Đã hủy Fish Audio.'), {name: 'AbortError'});
        const controller = new AbortController();
        const relayAbort = () => controller.abort();
        parentSignal?.addEventListener('abort', relayAbort, {once: true});
        let timer;
        try {
            const timeout = new Promise((_, reject) => {
                timer = setTimeout(() => {
                    controller.abort();
                    reject(new Error(`Fish Audio không phản hồi sau ${Math.round(timeoutMs / 1000)} giây.`));
                }, timeoutMs);
            });
            return await Promise.race([
                synthesize(text, config, {signal: controller.signal}),
                timeout,
            ]);
        } catch (error) {
            if (parentSignal?.aborted) throw Object.assign(new Error('Đã hủy Fish Audio.'), {name: 'AbortError'});
            lastError = error;
            if (attempt >= attempts || !retryableFishError(error)) break;
            options.onRetry?.(attempt + 1, error);
            await new Promise((resolve, reject) => {
                let onAbort;
                const done = () => {
                    parentSignal?.removeEventListener('abort', onAbort);
                    resolve();
                };
                const wait = setTimeout(done, retryDelayMs);
                onAbort = () => {
                    clearTimeout(wait);
                    parentSignal?.removeEventListener('abort', onAbort);
                    reject(Object.assign(new Error('Đã hủy Fish Audio.'), {name: 'AbortError'}));
                };
                parentSignal?.addEventListener('abort', onAbort, {once: true});
            });
        } finally {
            clearTimeout(timer);
            parentSignal?.removeEventListener('abort', relayAbort);
        }
    }
    throw lastError || new Error('Fish Audio không tạo được âm thanh.');
}

module.exports = {
    readFishConfig,
    synthesizeFish,
    synthesizeFishWithRetry,
    FISH_TTS_URL,
    DEFAULT_FISH_MODEL,
};
