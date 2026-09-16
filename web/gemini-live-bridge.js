const fs = require('fs');
const path = require('path');
const {WebSocket, WebSocketServer} = require('ws');
const {GoogleGenAI, Modality, Type} = require('@google/genai');
const {readFishConfig, synthesizeFish} = require('./fish-tts');

const DEFAULT_MODEL = 'gemini-3.8-live';
const DEFAULT_VOICE = 'Kore';
const EXPRESSIONS = new Set([
    'neutral', 'happy', 'sad', 'surprised', 'angry', 'love',
    'wink', 'sleepy', 'dizzy', 'cool', 'cute',
]);

function readGeminiKey(options = {}) {
    const env = options.env || process.env;
    if (typeof env.GEMINI_API_KEY === 'string' && env.GEMINI_API_KEY.trim()) {
        return env.GEMINI_API_KEY.trim();
    }

    const secretsPath = options.secretsPath || path.resolve(__dirname, '..', 'config', 'secrets.py');
    try {
        const source = fs.readFileSync(secretsPath, 'utf8');
        const match = source.match(/["']GEMINI_API_KEY["']\s*:\s*["']([^"']+)["']/);
        return match ? match[1].trim() : '';
    } catch (_) {
        return '';
    }
}

function normalizeExpression(value) {
    const expression = String(value || '').trim().toLowerCase();
    return EXPRESSIONS.has(expression) ? expression : 'neutral';
}

function preparePcmFrame(data) {
    const frame = Buffer.from(data);
    let hasSignal = false;
    for (let i = 0; i < frame.length; i++) {
        if (frame[i] !== 0) { hasSignal = true; break; }
    }
    if (hasSignal) return frame;

    // Browser noise suppression can gate a quiet microphone to exact digital
    // zero. Gemini Live closes the whole session with code 1007 for an all-zero
    // audio request. Alternating one least-significant bit is inaudible
    // (~-90 dBFS), still represents silence to VAD and keeps the PCM valid.
    for (let i = 0; i < frame.length; i += 2) {
        frame.writeInt16LE((i / 2) % 2 ? 1 : -1, i);
    }
    return frame;
}

function sameOrigin(req) {
    const origin = req.headers.origin;
    if (!origin) return true;
    try {
        return new URL(origin).host === req.headers.host;
    } catch (_) {
        return false;
    }
}

function attachGeminiLive(server, mqttClient, options = {}) {
    const wss = new WebSocketServer({noServer: true, maxPayload: 8192});
    const model = options.model || process.env.GEMINI_LIVE_MODEL || DEFAULT_MODEL;
    const voice = options.voice || process.env.GEMINI_LIVE_VOICE || DEFAULT_VOICE;
    const createClient = options.createClient || (apiKey => new GoogleGenAI({
        apiKey,
        httpOptions: {apiVersion: 'v1beta'},
    }));

    const publishFace = expression => {
        if (mqttClient?.connected) mqttClient.publish('panda/cmd/face', expression);
    };

    server.on('upgrade', (req, socket, head) => {
        const pathname = new URL(req.url, 'http://localhost').pathname;
        if (pathname !== '/live/ws') return;
        if (!sameOrigin(req)) {
            socket.write('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n');
            socket.destroy();
            return;
        }
        wss.handleUpgrade(req, socket, head, downstream => wss.emit('connection', downstream, req));
    });

    wss.on('connection', async (downstream, req) => {
        const query = new URL(req.url, 'http://localhost').searchParams;
        const outputMode = query.get('mode') === 'native' ? 'native' : 'fish';
        const fishConfig = readFishConfig(options);
        const synthesize = options.synthesizeFish || synthesizeFish;
        let session;
        let ready = false;
        let closed = false;
        let sentSpeaking = false;
        let pendingText = '';
        let responseGeneration = 0;
        let fishAbort;

        const cleanup = () => {
            if (closed) return;
            closed = true;
            ready = false;
            responseGeneration++;
            fishAbort?.abort();
            try { session?.sendRealtimeInput({audioStreamEnd: true}); } catch (_) {}
            try { session?.close(); } catch (_) {}
            if (session) publishFace('neutral');
        };
        downstream.once('close', cleanup);
        downstream.once('error', cleanup);

        const sendJson = value => {
            if (downstream.readyState === WebSocket.OPEN) downstream.send(JSON.stringify(value));
        };
        const fail = (text, code = 'live_error') => {
            sendJson({event: 'error', code, text});
            if (downstream.readyState === WebSocket.OPEN) downstream.close(1011, code.slice(0, 123));
        };
        const resetFace = () => {
            publishFace('neutral');
            sendJson({event: 'expression', expression: 'neutral'});
        };
        const interruptFish = () => {
            if (outputMode !== 'fish') return;
            responseGeneration++;
            fishAbort?.abort();
            fishAbort = undefined;
            pendingText = '';
        };
        const speakFish = async text => {
            const generation = ++responseGeneration;
            fishAbort?.abort();
            fishAbort = new AbortController();
            sendJson({event: 'fish_synthesizing'});
            try {
                const audio = await synthesize(text, fishConfig, {signal: fishAbort.signal});
                if (closed || generation !== responseGeneration || downstream.readyState !== WebSocket.OPEN) return;
                sentSpeaking = true;
                sendJson({event: 'speaking', format: 'mp3'});
                downstream.send(audio, {binary: true});
                sentSpeaking = false;
                sendJson({event: 'turn_complete'});
            } catch (error) {
                if (error?.name === 'AbortError' || generation !== responseGeneration || closed) return;
                resetFace();
                sendJson({event: 'turn_error', text: error?.message || 'Không tạo được giọng Fish Audio.'});
                sendJson({event: 'listening'});
            } finally {
                if (generation === responseGeneration) fishAbort = undefined;
            }
        };
        const handleToolCalls = calls => {
            if (!session || !Array.isArray(calls) || calls.length === 0) return;
            const functionResponses = calls.map(call => {
                if (call.name !== 'set_expression') {
                    return {id: call.id, name: call.name, response: {error: 'Unknown function'}};
                }
                const expression = normalizeExpression(call.args?.expression);
                publishFace(expression);
                sendJson({event: 'expression', expression});
                return {id: call.id, name: call.name, response: {output: `OLED is now ${expression}`}};
            });
            session.sendToolResponse({functionResponses});
        };
        const handleMessage = message => {
            if (message.setupComplete) {
                ready = true;
                sendJson({
                    event: 'ready',
                    model,
                    voice: outputMode === 'fish' ? 'Fish Voice' : voice,
                    outputMode,
                });
            }

            const activity = message.voiceActivity?.voiceActivityType;
            if (activity === 'ACTIVITY_START') {
                interruptFish();
                sendJson({event: 'user_speaking'});
            }
            if (activity === 'ACTIVITY_END') sendJson({event: 'thinking'});

            const content = message.serverContent;
            if (content?.interrupted) {
                interruptFish();
                sentSpeaking = false;
                sendJson({event: 'interrupted'});
            }

            if (outputMode === 'fish') {
                if (typeof content?.outputTranscription?.text === 'string') {
                    pendingText += content.outputTranscription.text;
                } else {
                    const textParts = content?.modelTurn?.parts?.filter(part =>
                        typeof part.text === 'string' && !part.thought) || [];
                    for (const part of textParts) pendingText += part.text;
                }
            }

            const audioParts = outputMode === 'native'
                ? (content?.modelTurn?.parts?.filter(part =>
                    part.inlineData?.data && String(part.inlineData.mimeType || '').startsWith('audio/')) || [])
                : [];
            for (const part of audioParts) {
                if (!sentSpeaking) {
                    sentSpeaking = true;
                    sendJson({event: 'speaking'});
                }
                if (downstream.readyState === WebSocket.OPEN) {
                    if (downstream.bufferedAmount > 512 * 1024) {
                        downstream.close(1013, 'Audio client is too slow');
                        return;
                    }
                    downstream.send(Buffer.from(part.inlineData.data, 'base64'), {binary: true});
                }
            }
            if (outputMode === 'native' && audioParts.length === 0 && message.data) {
                if (!sentSpeaking) {
                    sentSpeaking = true;
                    sendJson({event: 'speaking'});
                }
                if (downstream.readyState === WebSocket.OPEN) {
                    downstream.send(Buffer.from(message.data, 'base64'), {binary: true});
                }
            }

            if (content?.turnComplete) {
                sentSpeaking = false;
                if (outputMode === 'fish') {
                    const text = pendingText.trim();
                    pendingText = '';
                    if (text) void speakFish(text);
                    else {
                        sendJson({event: 'turn_error', text: 'Gemini chưa tạo được câu trả lời.'});
                        sendJson({event: 'listening'});
                    }
                } else {
                    sendJson({event: 'turn_complete'});
                }
            } else if (content?.waitingForInput) {
                sendJson({event: 'listening'});
            }
            if (message.toolCall?.functionCalls) handleToolCalls(message.toolCall.functionCalls);
            if (message.goAway) sendJson({event: 'reconnecting', text: 'Phiên Gemini sắp được làm mới.'});
        };

        const apiKey = readGeminiKey(options);
        if (!apiKey) {
            fail('Chưa có GEMINI_API_KEY. Hãy thêm key vào config/secrets.py rồi chạy lại start.bat.', 'missing_key');
            return;
        }
        if (outputMode === 'fish' && (!fishConfig.apiKey || !fishConfig.voiceId)) {
            fail('Chế độ Fish Voice cần FISH_AUDIO_API_KEY và FISH_VOICE_ID trong cấu hình.', 'missing_fish_config');
            return;
        }

        sendJson({event: 'connecting', model, voice: outputMode === 'fish' ? 'Fish Voice' : voice, outputMode});
        try {
            const ai = createClient(apiKey);
            session = await ai.live.connect({
                model,
                config: {
                    responseModalities: [Modality.AUDIO],
                    speechConfig: {voiceConfig: {prebuiltVoiceConfig: {voiceName: voice}}},
                    ...(outputMode === 'fish' ? {outputAudioTranscription: {}} : {}),
                    systemInstruction: {
                        parts: [{text: [
                            'Bạn là Moon, robot đồng hành thân thiện. Luôn trò chuyện tự nhiên bằng tiếng Việt.',
                            'Trả lời trực tiếp, ngắn gọn, thường từ một đến ba câu; có thể ngắt lời như hội thoại thật.',
                            'Dựa trên nội dung và giọng điệu người dùng, hãy gọi set_expression để OLED thể hiện cảm xúc phù hợp.',
                            'Không đọc transcript, không mô tả công cụ và không nói rằng bạn đang gọi công cụ.',
                            ...(outputMode === 'fish' ? [
                                'Câu trả lời sẽ được đọc bằng Fish Audio: chỉ viết lời nói tự nhiên, không Markdown, không emoji và không ký hiệu trang trí.',
                            ] : []),
                        ].join(' ')}],
                    },
                    tools: [{functionDeclarations: [{
                        name: 'set_expression',
                        description: 'Đổi biểu cảm OLED của Moon cho phù hợp với sắc thái hiện tại.',
                        parameters: {
                            type: Type.OBJECT,
                            properties: {
                                expression: {
                                    type: Type.STRING,
                                    enum: [...EXPRESSIONS],
                                    description: 'Biểu cảm OLED.',
                                },
                            },
                            required: ['expression'],
                        },
                    }]}],
                },
                callbacks: {
                    onopen: () => sendJson({event: 'connected'}),
                    onmessage: handleMessage,
                    onerror: event => fail(event?.message || 'Gemini Live gặp lỗi kết nối.'),
                    onclose: event => {
                        if (!closed && downstream.readyState === WebSocket.OPEN) {
                            const closeCode = Number(event?.code) || 0;
                            const closeReason = String(event?.reason || '').trim().slice(0, 240);
                            sendJson({
                                event: 'error',
                                code: `gemini_close_${closeCode}`,
                                text: closeReason
                                    ? `Gemini đóng phiên (${closeCode}): ${closeReason}`
                                    : `Gemini đóng phiên ngoài dự kiến (mã ${closeCode}).`,
                            });
                            downstream.close(1012, 'Gemini session closed');
                        }
                    },
                },
            });
            if (closed || downstream.readyState !== WebSocket.OPEN) {
                try { session.close(); } catch (_) {}
                return;
            }
        } catch (error) {
            fail(error?.message || 'Không kết nối được Gemini Live.');
            return;
        }

        downstream.on('message', (data, isBinary) => {
            if (!session || !ready) return;
            if (isBinary) {
                if (data.length === 0 || data.length > 4096 || data.length % 2 !== 0) {
                    downstream.close(1003, 'Invalid PCM frame');
                    return;
                }
                session.sendRealtimeInput({
                    audio: {data: preparePcmFrame(data).toString('base64'), mimeType: 'audio/pcm;rate=16000'},
                });
                return;
            }
            try {
                const command = JSON.parse(data.toString()).command;
                if (command === 'playback_complete') {
                    resetFace();
                    sendJson({event: 'listening'});
                } else if (command === 'audio_stream_end') {
                    session.sendRealtimeInput({audioStreamEnd: true});
                }
            } catch (_) {
                downstream.close(1003, 'Invalid control message');
            }
        });

    });

    return wss;
}

module.exports = {
    attachGeminiLive,
    readGeminiKey,
    normalizeExpression,
    preparePcmFrame,
    DEFAULT_MODEL,
    DEFAULT_VOICE,
};
