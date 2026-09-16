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

module.exports = {
    readFishConfig,
    synthesizeFish,
    FISH_TTS_URL,
    DEFAULT_FISH_MODEL,
};
