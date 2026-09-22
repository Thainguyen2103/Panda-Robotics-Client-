const {WebSocket, WebSocketServer} = require('ws');
const {
    AudioTranscriptionConfigMode,
    EndSensitivity,
    GoogleGenAI,
    Modality,
    StartSensitivity,
} = require('@google/genai');
const {preparePcmFrame, readGeminiKey} = require('./gemini-live-bridge');

const DEFAULT_MODEL = 'gemini-3.5-transcribe-live';
const STT_LANGUAGES = Object.freeze(['vi-VN', 'en-US', 'ja-JP']);
const STT_VOCABULARY = Object.freeze([
    'Moon', 'ムーン', 'Kanji', 'Hiragana', 'Katakana', 'Romaji',
]);

function sameOrigin(req) {
    const origin = req.headers.origin;
    if (!origin) return true;
    try {
        return new URL(origin).host === req.headers.host;
    } catch (_) {
        return false;
    }
}

function wakeTail(text) {
    const source = String(text || '').normalize('NFKC').trim();
    if (!source) return null;
    const match = /(?:^|[\s,，、。.!?！？:：;；—-])(moon|ムーン)(?=$|[\s,，、。.!?！？:：;；—-])/iu.exec(source);
    if (!match) return null;
    const tail = source.slice(match.index + match[0].length)
        .replace(/^[\s,，、。.!?！？:：;；—-]+/u, '')
        .replace(/^ơi\b[\s,，、。.!?！？:：;；—-]*/iu, '')
        .trim();
    return tail;
}

function attachGeminiTranscribe(server, options = {}) {
    const wss = new WebSocketServer({noServer: true, maxPayload: 8192});
    const model = options.model || process.env.GEMINI_TRANSCRIBE_MODEL || DEFAULT_MODEL;
    const languages = options.languages || STT_LANGUAGES;
    const vocabulary = options.vocabulary || STT_VOCABULARY;
    const createClient = options.createClient || (apiKey => new GoogleGenAI({
        apiKey,
        httpOptions: {apiVersion: 'v1beta'},
    }));

    server.on('upgrade', (req, socket, head) => {
        const pathname = new URL(req.url, 'http://localhost').pathname;
        if (pathname !== '/transcribe/ws') return;
        if (!sameOrigin(req)) {
            socket.write('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n');
            socket.destroy();
            return;
        }
        wss.handleUpgrade(req, socket, head, downstream => wss.emit('connection', downstream, req));
    });

    wss.on('connection', async (downstream, req) => {
        const query = new URL(req.url, 'http://localhost').searchParams;
        const mode = query.get('mode') === 'wake' ? 'wake' : 'continuous';
        const apiKey = readGeminiKey(options);
        let session;
        let ready = false;
        let paused = false;
        let closed = false;
        let connectionGeneration = 0;
        let reconnecting = false;
        let lastFinal = '';
        let lastFinalAt = 0;

        const sendJson = value => {
            if (downstream.readyState !== WebSocket.OPEN) return false;
            try {
                downstream.send(JSON.stringify(value));
                return true;
            } catch (_) {
                return false;
            }
        };
        const closeSession = candidate => {
            if (!candidate) return;
            try {
                const result = candidate.close();
                if (result && typeof result.catch === 'function') result.catch(() => {});
            } catch (_) {}
        };
        const cleanup = () => {
            if (closed) return;
            closed = true;
            ready = false;
            connectionGeneration++;
            closeSession(session);
            session = undefined;
        };
        const fail = (text, code = 'transcribe_error') => {
            if (closed) return;
            sendJson({event: 'error', code, text});
            if (downstream.readyState === WebSocket.OPEN) {
                try { downstream.close(1011, code.slice(0, 123)); } catch (_) {}
            }
        };
        const callSession = input => {
            if (!session || !ready || closed) return;
            try {
                const result = session.sendRealtimeInput(input);
                if (result && typeof result.catch === 'function') {
                    result.catch(error => fail(
                        error?.message || 'Không gửi được audio tới Gemini Transcribe.',
                        'transcribe_send_error',
                    ));
                }
            } catch (error) {
                fail(error?.message || 'Không gửi được audio tới Gemini Transcribe.', 'transcribe_send_error');
            }
        };
        const acceptFinal = text => {
            const clean = String(text || '').trim();
            if (!clean || paused) return;
            const now = Date.now();
            if (clean === lastFinal && now - lastFinalAt < 3000) return;
            lastFinal = clean;
            lastFinalAt = now;
            sendJson({event: 'transcript', text: clean});
            if (mode === 'wake') {
                const tail = wakeTail(clean);
                if (tail === null) {
                    sendJson({event: 'ignored', text: clean});
                    return;
                }
                paused = true;
                sendJson({event: 'wake', text: clean, tail});
                return;
            }
            paused = true;
            sendJson({event: 'question', text: clean});
        };

        const connectUpstream = async ({replacement = false} = {}) => {
            const generation = ++connectionGeneration;
            ready = false;
            if (replacement) {
                reconnecting = true;
                sendJson({event: 'reconnecting', text: 'Đang làm mới phiên STT đa ngôn ngữ…'});
            }
            try {
                const ai = createClient(apiKey);
                const candidate = await ai.live.connect({
                    model,
                    config: {
                        responseModalities: [Modality.TEXT],
                        inputAudioTranscription: {
                            languageCodes: [...languages],
                            customVocabulary: [...vocabulary],
                            mode: AudioTranscriptionConfigMode.VERBATIM,
                        },
                        realtimeInputConfig: {
                            automaticActivityDetection: {
                                disabled: false,
                                startOfSpeechSensitivity: StartSensitivity.START_SENSITIVITY_HIGH,
                                endOfSpeechSensitivity: EndSensitivity.END_SENSITIVITY_HIGH,
                                prefixPaddingMs: 300,
                                silenceDurationMs: 700,
                            },
                        },
                    },
                    callbacks: {
                        onopen: () => {},
                        onmessage: message => {
                            if (closed || generation !== connectionGeneration) return;
                            if (message.setupComplete) {
                                ready = true;
                                reconnecting = false;
                                sendJson({
                                    event: 'ready', model, mode,
                                    languages: [...languages], calibrating: false,
                                    engine: 'Gemini Transcribe · Việt · English · 日本語',
                                });
                            }
                            const activity = message.voiceActivity?.voiceActivityType;
                            if (!paused && activity === 'ACTIVITY_START') {
                                lastFinal = '';
                                sendJson({event: 'user_speaking'});
                            } else if (!paused && activity === 'ACTIVITY_END') {
                                sendJson({event: 'processing'});
                            }
                            const content = message.serverContent;
                            const interim = content?.interimInputTranscription?.text;
                            if (!paused && typeof interim === 'string' && interim.trim()) {
                                sendJson({event: 'partial', text: interim.trim()});
                            }
                            const finalText = content?.inputTranscription?.text;
                            if (typeof finalText === 'string') acceptFinal(finalText);
                            if (message.goAway && !reconnecting) {
                                const previous = session;
                                session = undefined;
                                closeSession(previous);
                                void connectUpstream({replacement: true});
                            }
                        },
                        onerror: event => {
                            if (closed || generation !== connectionGeneration || reconnecting) return;
                            fail(event?.message || 'Gemini Transcribe gặp lỗi kết nối.');
                        },
                        onclose: event => {
                            if (closed || generation !== connectionGeneration || reconnecting) return;
                            const reason = String(event?.reason || '').trim();
                            fail(reason
                                ? `Gemini Transcribe đã đóng phiên: ${reason}`
                                : 'Gemini Transcribe đã đóng phiên ngoài dự kiến.', 'transcribe_closed');
                        },
                    },
                });
                if (closed || generation !== connectionGeneration) {
                    closeSession(candidate);
                    return;
                }
                session = candidate;
            } catch (error) {
                if (closed || generation !== connectionGeneration) return;
                const message = String(error?.message || error || 'Không kết nối được Gemini Transcribe.');
                const auth = /401|403|api.?key|permission|unauth/i.test(message);
                fail(auth
                    ? 'GEMINI_API_KEY không hợp lệ hoặc chưa có quyền dùng Transcribe Live.'
                    : message, auth ? 'invalid_gemini_key' : 'transcribe_connect_error');
            }
        };

        downstream.once('close', cleanup);
        downstream.once('error', cleanup);
        if (!apiKey) {
            fail('Chưa có GEMINI_API_KEY. Hãy thêm key vào config/secrets.py rồi chạy lại start.bat.', 'missing_key');
            return;
        }
        sendJson({event: 'connecting', model});
        await connectUpstream();

        downstream.on('message', (data, isBinary) => {
            if (closed) return;
            if (isBinary) {
                if (paused || !ready) return;
                if (data.length === 0 || data.length > 4096 || data.length % 2 !== 0) {
                    downstream.close(1003, 'Invalid PCM frame');
                    return;
                }
                callSession({
                    audio: {
                        data: preparePcmFrame(data).toString('base64'),
                        mimeType: 'audio/pcm;rate=16000',
                    },
                });
                return;
            }
            try {
                const command = JSON.parse(data.toString()).command;
                if (command === 'pause') {
                    paused = true;
                } else if (command === 'resume') {
                    paused = false;
                    lastFinal = '';
                    sendJson({event: 'resumed'});
                    sendJson({event: 'state', state: mode === 'wake' ? 'waiting' : 'listening'});
                } else if (command === 'audio_stream_end') {
                    callSession({audioStreamEnd: true});
                }
            } catch (_) {
                downstream.close(1003, 'Invalid control message');
            }
        });
    });

    return wss;
}

module.exports = {
    DEFAULT_MODEL,
    STT_LANGUAGES,
    STT_VOCABULARY,
    attachGeminiTranscribe,
    wakeTail,
};
