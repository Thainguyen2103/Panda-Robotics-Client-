const path = require('node:path');
const {spawn} = require('node:child_process');

const VOICE = Object.freeze({
    ja: process.env.MOON_EDGE_TTS_JA_VOICE || 'ja-JP-NanamiNeural',
    en: process.env.MOON_EDGE_TTS_EN_VOICE || 'en-US-AnaNeural',
    vi: process.env.MOON_EDGE_TTS_VI_VOICE || 'vi-VN-HoaiMyNeural',
});
const SYNTH_SCRIPT = path.resolve(__dirname, '..', 'server', 'voice', 'edge_tts_cli.py');

function selectVoice(text) {
    const value = String(text || '');
    if (/[ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]/iu.test(value)) {
        return VOICE.vi;
    }
    if (/[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]/u.test(value)) {
        const letters = [...value].filter(char => /\p{L}/u.test(char));
        const latinLetters = letters.filter(char => /[A-Za-z]/u.test(char)).length;
        if (letters.length < 8 || latinLetters / letters.length < 0.65) return VOICE.ja;
    }
    return VOICE.en;
}

function synthesizeEdge(text, options = {}) {
    const voice = options.voice || selectVoice(text);
    const spawnProcess = options.spawn || spawn;
    const timeoutMs = Math.max(100, Number(options.timeoutMs) || 15000);
    const python = options.python || process.env.MOON_PYTHON || process.env.PYTHON || 'python';

    return new Promise((resolve, reject) => {
        if (options.signal?.aborted) {
            const error = new Error('Edge TTS request aborted');
            error.name = 'AbortError';
            reject(error);
            return;
        }

        const child = spawnProcess(python, [SYNTH_SCRIPT], {
            windowsHide: true,
            stdio: ['pipe', 'pipe', 'pipe'],
        });
        const audioChunks = [];
        let audioLength = 0;
        let stderr = '';
        let settled = false;
        let timer;

        const finish = (error, audio) => {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            options.signal?.removeEventListener('abort', abort);
            if (error) reject(error);
            else resolve(audio);
        };
        const abort = () => {
            const error = new Error('Edge TTS request aborted');
            error.name = 'AbortError';
            child.kill();
            finish(error);
        };

        timer = setTimeout(() => {
            child.kill();
            finish(new Error('Edge TTS timed out'));
        }, timeoutMs);
        options.signal?.addEventListener('abort', abort, {once: true});
        child.stdout.on('data', chunk => {
            audioLength += chunk.length;
            if (audioLength > 16 * 1024 * 1024) {
                child.kill();
                finish(new Error('Edge TTS audio exceeded the size limit'));
                return;
            }
            audioChunks.push(chunk);
        });
        child.stderr.on('data', chunk => {
            if (stderr.length < 256) stderr += chunk.toString('utf8').slice(0, 256 - stderr.length);
        });
        child.once('error', error => finish(new Error(`Edge TTS process failed: ${error.code || error.name}`)));
        child.once('close', code => {
            if (settled) return;
            if (code !== 0) {
                finish(new Error(`Edge TTS synthesis failed${stderr ? ` (${stderr.trim()})` : ''}`));
                return;
            }
            const audio = Buffer.concat(audioChunks, audioLength);
            finish(audio.length ? null : new Error('Edge TTS returned empty audio'), audio);
        });
        child.stdin.on('error', error => {
            if (!settled) finish(new Error(`Edge TTS input failed: ${error.code || error.name}`));
        });
        child.stdin.end(JSON.stringify({text: String(text || ''), voice}));
    });
}

module.exports = {VOICE, selectVoice, synthesizeEdge};
