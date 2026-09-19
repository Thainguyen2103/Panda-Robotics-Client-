const fs = require('fs');
const path = require('path');
const {WebSocket, WebSocketServer} = require('ws');
const {
    GoogleGenAI, Modality, Type, StartSensitivity, EndSensitivity,
} = require('@google/genai');
const {readFishConfig, synthesizeFish, synthesizeFishWithRetry} = require('./fish-tts');

const DEFAULT_MODEL = 'gemini-3.8-live';
const DEFAULT_VOICE = 'Kore';
const EXPRESSIONS = new Set([
    'neutral', 'happy', 'sad', 'surprised', 'angry', 'love',
    'wink', 'sleepy', 'dizzy', 'cool', 'cute',
]);
const MAX_FALLBACK_AUDIO_BYTES = 6 * 1024 * 1024;

function ignoreRejection(result) {
    if (result && typeof result.catch === 'function') result.catch(() => {});
}

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
        let pendingNativeAudio = [];
        let pendingNativeBytes = 0;
        let responseGeneration = 0;
        let fishAbort;
        let fishFinalizeTimer;
        let toolContinuationTimer;
        let awaitingToolContinuation = false;
        let failed = false;
        let lastPlaybackFallback = [];
        let lastPlaybackText = '';
        let browserFallbackActive = false;

        const cleanup = () => {
            if (closed) return;
            closed = true;
            ready = false;
            responseGeneration++;
            clearTimeout(fishFinalizeTimer);
            clearTimeout(toolContinuationTimer);
            fishAbort?.abort();
            try { ignoreRejection(session?.sendRealtimeInput({audioStreamEnd: true})); } catch (_) {}
            try { ignoreRejection(session?.close()); } catch (_) {}
            if (session) publishFace('neutral');
        };
        downstream.once('close', cleanup);
        downstream.once('error', cleanup);

        const sendJson = value => {
            if (downstream.readyState !== WebSocket.OPEN) return;
            try { downstream.send(JSON.stringify(value)); } catch (_) {}
        };
        const fail = (text, code = 'live_error') => {
            if (failed || closed) return;
            failed = true;
            sendJson({event: 'error', code, text});
            if (downstream.readyState === WebSocket.OPEN) {
                try { downstream.close(1011, code.slice(0, 123)); } catch (_) {}
            }
        };
        const callSession = (method, payload) => {
            if (!session || closed || failed) return;
            try {
                const result = session[method](payload);
                if (result && typeof result.catch === 'function') {
                    result.catch(error => {
                        if (!closed) fail(error?.message || 'Mất kết nối với Gemini Live.', 'gemini_send_error');
                    });
                }
            } catch (error) {
                fail(error?.message || 'Mất kết nối với Gemini Live.', 'gemini_send_error');
            }
        };
        const resetFace = () => {
            publishFace('neutral');
            sendJson({event: 'expression', expression: 'neutral'});
        };
        const interruptFish = () => {
            if (outputMode !== 'fish') return;
            responseGeneration++;
            clearTimeout(fishFinalizeTimer);
            clearTimeout(toolContinuationTimer);
            fishFinalizeTimer = undefined;
            toolContinuationTimer = undefined;
            awaitingToolContinuation = false;
            fishAbort?.abort();
            fishAbort = undefined;
            pendingText = '';
            pendingNativeAudio = [];
            pendingNativeBytes = 0;
            lastPlaybackFallback = [];
            lastPlaybackText = '';
        };
        const sendAudio = (chunks, format, fallbackText = '', complete = true, announce = true) => {
            if (!Array.isArray(chunks) || chunks.length === 0 || downstream.readyState !== WebSocket.OPEN) return false;
            if (fallbackText) sendJson({event: 'fish_fallback', text: fallbackText});
            if (announce) sendJson({event: 'speaking', format});
            try {
                for (const chunk of chunks) {
                    if (downstream.bufferedAmount > 512 * 1024) throw new Error('Trình duyệt nhận audio quá chậm.');
                    downstream.send(chunk, {binary: true});
                }
                if (complete) sendJson({event: 'turn_complete'});
                return true;
            } catch (error) {
                fail(error?.message || 'Không gửi được audio tới trình duyệt.', 'audio_send_error');
                return false;
            }
        };
        const fallbackToGeminiAudio = (chunks, reason, spokenText = '') => {
            const text = reason
                ? `Fish Audio tạm lỗi (${reason}). Moon dùng giọng Gemini cho câu này.`
                : 'Không nhận được bản chữ Fish. Moon dùng giọng Gemini cho câu này.';
            if (sendAudio(chunks, 'pcm', text)) return;
            if (spokenText.trim()) {
                browserFallbackActive = true;
                sendJson({
                    event: 'browser_tts_fallback',
                    text: spokenText.trim(),
                    reason: reason || 'Gemini không gửi kèm audio native',
                });
                return;
            }
            resetFace();
            sendJson({event: 'turn_error', text: 'Gemini không trả về cả nội dung chữ lẫn âm thanh.'});
            sendJson({event: 'listening'});
        };
        const speakFish = async (text, fallbackAudio) => {
            const generation = ++responseGeneration;
            fishAbort?.abort();
            fishAbort = new AbortController();
            sendJson({event: 'fish_synthesizing'});
            try {
                const audio = await synthesizeFishWithRetry(text, fishConfig, {
                    signal: fishAbort.signal,
                    synthesize,
                    attempts: 2,
                    timeoutMs: 15000,
                    onRetry: () => sendJson({event: 'fish_retrying'}),
                });
                if (closed || generation !== responseGeneration || downstream.readyState !== WebSocket.OPEN) return;
                sentSpeaking = true;
                lastPlaybackFallback = fallbackAudio;
                lastPlaybackText = text;
                sendAudio([audio], 'mp3');
                sentSpeaking = false;
            } catch (error) {
                if (error?.name === 'AbortError' || generation !== responseGeneration || closed) return;
                fallbackToGeminiAudio(fallbackAudio, error?.message || 'không tạo được giọng Fish', text);
            } finally {
                if (generation === responseGeneration) fishAbort = undefined;
            }
        };
        const finalizeFishTurn = () => {
            fishFinalizeTimer = undefined;
            const text = pendingText.trim();
            const fallbackAudio = pendingNativeAudio;
            pendingText = '';
            pendingNativeAudio = [];
            pendingNativeBytes = 0;
            if (text) void speakFish(text, fallbackAudio);
            else fallbackToGeminiAudio(fallbackAudio, '');
        };
        const handleToolCalls = calls => {
            if (!session || !Array.isArray(calls) || calls.length === 0) return;
            awaitingToolContinuation = true;
            clearTimeout(toolContinuationTimer);
            const functionResponses = calls.map(call => {
                if (call.name !== 'set_expression') {
                    return {id: call.id, name: call.name, response: {error: 'Unknown function'}};
                }
                const expression = normalizeExpression(call.args?.expression);
                publishFace(expression);
                sendJson({event: 'expression', expression});
                return {id: call.id, name: call.name, response: {output: `OLED is now ${expression}`}};
            });
            callSession('sendToolResponse', {functionResponses});
            toolContinuationTimer = setTimeout(() => {
                if (!awaitingToolContinuation || closed) return;
                awaitingToolContinuation = false;
                sendJson({
                    event: 'turn_error',
                    text: 'Gemini đã đổi biểu cảm nhưng chưa gửi câu trả lời. Bạn hãy nói lại câu vừa rồi.',
                });
                sendJson({event: 'listening'});
            }, 8000);
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
            const hasToolCalls = Array.isArray(message.toolCall?.functionCalls)
                && message.toolCall.functionCalls.length > 0;
            if (hasToolCalls) handleToolCalls(message.toolCall.functionCalls);
            if (typeof content?.inputTranscription?.text === 'string') {
                sendJson({event: 'input_transcript', text: content.inputTranscription.text});
            }
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

            const audioParts = content?.modelTurn?.parts?.filter(part =>
                part.inlineData?.data && String(part.inlineData.mimeType || '').startsWith('audio/')) || [];
            const audioChunks = audioParts.map(part => Buffer.from(part.inlineData.data, 'base64'));
            if (audioChunks.length === 0 && message.data) audioChunks.push(Buffer.from(message.data, 'base64'));
            const hasResponseContent = audioChunks.length > 0
                || typeof content?.outputTranscription?.text === 'string'
                || (content?.modelTurn?.parts || []).some(part => typeof part.text === 'string' && !part.thought);
            if (hasResponseContent && awaitingToolContinuation) {
                awaitingToolContinuation = false;
                clearTimeout(toolContinuationTimer);
                toolContinuationTimer = undefined;
            }
            if (outputMode === 'fish') {
                for (const chunk of audioChunks) {
                    if (pendingNativeBytes + chunk.length > MAX_FALLBACK_AUDIO_BYTES) break;
                    pendingNativeAudio.push(chunk);
                    pendingNativeBytes += chunk.length;
                }
            } else if (audioChunks.length > 0) {
                if (!sentSpeaking) {
                    sentSpeaking = true;
                    sendJson({event: 'speaking', format: 'pcm'});
                }
                if (!sendAudio(audioChunks, 'pcm', '', false, false)) return;
            }

            if (content?.turnComplete) {
                sentSpeaking = false;
                if (outputMode === 'fish') {
                    // A tool-only turn (OLED expression) is not the spoken answer.
                    // Wait for the continuation produced after sendToolResponse().
                    if ((hasToolCalls || awaitingToolContinuation)
                            && !pendingText.trim() && pendingNativeAudio.length === 0) return;
                    clearTimeout(fishFinalizeTimer);
                    // Output transcription can arrive a fraction after turnComplete.
                    fishFinalizeTimer = setTimeout(finalizeFishTurn, 250);
                } else {
                    sendJson({event: 'turn_complete'});
                }
            } else if (content?.waitingForInput) {
                sendJson({event: 'listening'});
            }
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
                    inputAudioTranscription: {},
                    realtimeInputConfig: {
                        automaticActivityDetection: {
                            disabled: false,
                            startOfSpeechSensitivity: StartSensitivity.START_SENSITIVITY_HIGH,
                            endOfSpeechSensitivity: EndSensitivity.END_SENSITIVITY_HIGH,
                            prefixPaddingMs: 300,
                            silenceDurationMs: 700,
                        },
                    },
                    ...(outputMode === 'fish' ? {outputAudioTranscription: {}} : {}),
                    systemInstruction: {
                        parts: [{text: [
                            'Bạn là Moon, robot đồng hành thân thiện.',
                            'Mỗi lượt, hãy tự nhận biết ngôn ngữ trong câu nói mới nhất và trả lời đúng ngôn ngữ đó: tiếng Việt hỏi thì đáp tiếng Việt, tiếng Anh hỏi thì đáp tiếng Anh. Nếu người dùng trộn hai ngôn ngữ hoặc âm thanh không đủ rõ để chắc chắn, trả lời song ngữ thật ngắn: tiếng Việt trước rồi tiếng Anh tương đương. Không bị ngôn ngữ các lượt cũ chi phối.',
                            'Trả lời trực tiếp, ngắn gọn, thường từ một đến ba câu; có thể ngắt lời như hội thoại thật.',
                            'Dựa trên nội dung và giọng điệu người dùng, hãy gọi set_expression để OLED thể hiện cảm xúc phù hợp.',
                            'Không đọc transcript, không mô tả công cụ và không nói rằng bạn đang gọi công cụ.',
                            ...(outputMode === 'fish' ? [
                                'Câu trả lời sẽ được đọc bằng Fish Audio: chỉ viết lời nói tự nhiên, không Markdown, không emoji và không ký hiệu trang trí.',
                                'Để phát âm tiếng Việt rõ: dùng câu ngắn, dấu câu rõ; viết đầy đủ số, đơn vị và chữ viết tắt bằng tiếng Việt; ưu tiên từ tiếng Việt dễ đọc nếu có nghĩa tương đương.',
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
                    onmessage: message => {
                        try { handleMessage(message); }
                        catch (error) { fail(error?.message || 'Lỗi xử lý phản hồi Gemini.', 'gemini_message_error'); }
                    },
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
                try { ignoreRejection(session.close()); } catch (_) {}
                return;
            }
        } catch (error) {
            fail(error?.message || 'Không kết nối được Gemini Live.');
            return;
        }

        downstream.on('message', (data, isBinary) => {
            if (!session || !ready) return;
            if (isBinary) {
                if (browserFallbackActive) return;
                if (data.length === 0 || data.length > 4096 || data.length % 2 !== 0) {
                    downstream.close(1003, 'Invalid PCM frame');
                    return;
                }
                callSession('sendRealtimeInput', {
                    audio: {data: preparePcmFrame(data).toString('base64'), mimeType: 'audio/pcm;rate=16000'},
                });
                return;
            }
            try {
                const command = JSON.parse(data.toString()).command;
                if (command === 'playback_complete') {
                    browserFallbackActive = false;
                    lastPlaybackFallback = [];
                    lastPlaybackText = '';
                    resetFace();
                    sendJson({event: 'listening'});
                } else if (command === 'playback_failed' && outputMode === 'fish') {
                    const fallbackAudio = lastPlaybackFallback;
                    const fallbackText = lastPlaybackText;
                    lastPlaybackFallback = [];
                    lastPlaybackText = '';
                    fallbackToGeminiAudio(
                        fallbackAudio,
                        'trình duyệt không phát được MP3 Fish',
                        fallbackText,
                    );
                } else if (command === 'audio_stream_end') {
                    callSession('sendRealtimeInput', {audioStreamEnd: true});
                    sendJson({event: 'input_committed'});
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
