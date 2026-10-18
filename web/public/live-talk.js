(() => {
const $ = id => document.getElementById(`live-${id}`);
let stream, context, source, highpass, capture, ws;
let starting = false, active = false, ready = false, generation = 0;
let releaseMicLock, micLockHeld = false, startedAt = 0, clockTimer, micMonitorTimer;
let playHead = 0, turnComplete = false, outputMode = 'edge', incomingFormat = 'mp3';
let playbackGeneration = 0, decodingCount = 0;
let fallbackAudioElement = null, fallbackAudioUrl = null, pendingFallbackAudio = null;
let pipeline = 'gemini', turnTranscript = '', responseStartedAt = 0;
let brainWaiting = false, brainTimer, brainResumeTimer, brainTranscriptTimer;
let geminiResponseTimer;
let activation = 'manual', phase = 'idle', promotingWake = false, wakeCalibrating = false;
let wakeIdleTimer, returningToWake = false;
const configuredWakeIdleMs = Number(window.MOON_WAKE_IDLE_TIMEOUT_MS);
const WAKE_IDLE_TIMEOUT_MS = Number.isFinite(configuredWakeIdleMs) && configuredWakeIdleMs > 0
    ? configuredWakeIdleMs : 60000;
let localSpeech = false, localSilenceFrames = 0, localNoise = .0015;
let micAudioLogSent = false;
let micStats = {frames: 0, rmsTotal: 0, rmsPeak: 0, activeFrames: 0};
let lastSpeechEventAt = 0;
let micDiagnosticError = false;
const localSpeechVotes = [];
const playing = new Set();

function dispatch(event, extra = {}) {
    window.dispatchEvent(new CustomEvent('moon-live', {detail: {event, pipeline, ...extra}}));
}

function showHeard(text) {
    const clean = String(text || '').trim();
    $('heard').textContent = clean || 'Chưa nhận diện được nội dung';
}

function showCorrected(text, visible = true) {
    const label = $('corrected-label');
    const value = $('corrected');
    label.hidden = !visible;
    value.hidden = !visible;
    value.textContent = String(text || '').trim() || 'Giữ nguyên câu STT';
}

function showLatency(text) {
    $('latency').textContent = `Độ trễ: ${text || '—'}`;
}

function setState(state, text) {
    $('orb').dataset.state = state;
    $('badge').dataset.state = state;
    $('badge').textContent = ({
        idle: 'Chưa chạy', requesting_permission: 'Xin quyền mic', connecting: 'Đang kết nối', listening: 'Đang nghe',
        speech_detected: 'Đã phát hiện giọng nói', transcribing: 'Đang nhận diện', recognized: 'Đã nhận diện', stopped: 'Đã dừng',
        waiting: 'Chờ Moon', thinking: 'Đang nghĩ', speaking: 'Moon đang nói', error: 'Có lỗi',
    })[state] || state;
    $('state').textContent = text;
}

function wakeTick() {
    if (!context || context.state !== 'running') return;
    const tone = context.createOscillator();
    const volume = context.createGain();
    const now = context.currentTime;
    tone.frequency.setValueAtTime(1100, now);
    volume.gain.setValueAtTime(0, now);
    volume.gain.linearRampToValueAtTime(.07, now + .008);
    volume.gain.exponentialRampToValueAtTime(.0001, now + .08);
    tone.connect(volume);
    volume.connect(context.destination);
    tone.onended = () => { tone.disconnect(); volume.disconnect(); };
    tone.start(now);
    tone.stop(now + .09);
}

function speakWakeAcknowledgementFallback(token) {
    return new Promise(resolve => {
        if (token !== generation || !('speechSynthesis' in window)
                || typeof SpeechSynthesisUtterance === 'undefined') {
            resolve();
            return;
        }
        const utterance = new SpeechSynthesisUtterance('Moon nghe đây!');
        utterance.lang = 'vi-VN';
        utterance.rate = .98;
        const vietnameseVoice = window.speechSynthesis.getVoices().find(voice =>
            String(voice.lang || '').toLowerCase().startsWith('vi'));
        if (vietnameseVoice) utterance.voice = vietnameseVoice;
        let settled = false;
        const finish = () => {
            if (settled) return;
            settled = true;
            clearTimeout(timeout);
            resolve();
        };
        const timeout = setTimeout(finish, 3200);
        utterance.onend = finish;
        utterance.onerror = finish;
        window.speechSynthesis.cancel();
        window.speechSynthesis.speak(utterance);
    });
}

async function playWakeAcknowledgement(token) {
    if (token !== generation || !context) return;
    setState('speaking', 'Moon đã nghe — đang phản hồi…');
    dispatch('wake_ack');
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 4500);
    try {
        const response = await fetch('/api/live-ack', {
            cache: 'force-cache',
            signal: controller.signal,
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const encoded = await response.arrayBuffer();
        const buffer = await context.decodeAudioData(encoded.slice(0));
        if (token !== generation || !context) return;
        await new Promise(resolve => {
            const node = context.createBufferSource();
            node.buffer = buffer;
            node.connect(context.destination);
            const finish = () => {
                node.onended = null;
                try { node.disconnect(); } catch (_) {}
                resolve();
            };
            node.onended = finish;
            node.start(context.currentTime + .035);
            setTimeout(finish, Math.max(1000, buffer.duration * 1000 + 500));
        });
    } catch (_) {
        await speakWakeAcknowledgementFallback(token);
    } finally {
        clearTimeout(timeout);
    }
}

function resetGeminiTurnDetector() {
    localSpeech = false;
    localSilenceFrames = 0;
    localSpeechVotes.length = 0;
}

function clearWakeIdleTimeout() {
    clearTimeout(wakeIdleTimer);
    wakeIdleTimer = undefined;
}

function armWakeIdleTimeout() {
    clearWakeIdleTimeout();
    if (!active || activation !== 'wakeword' || phase !== 'live'
            || promotingWake || returningToWake) return;
    const token = generation;
    wakeIdleTimer = setTimeout(() => {
        if (token !== generation || !active || activation !== 'wakeword'
                || phase !== 'live' || promotingWake || returningToWake) return;
        void returnLiveToWake(token);
    }, WAKE_IDLE_TIMEOUT_MS);
}

function armGeminiResponseTimeout() {
    clearTimeout(geminiResponseTimer);
    const token = generation;
    geminiResponseTimer = setTimeout(() => {
        if (token !== generation || !active || pipeline !== 'gemini') return;
        $('error').textContent = 'Gemini đã nhận câu nhưng chưa phản hồi. Bạn hãy nói lại câu vừa rồi.';
        responseStartedAt = 0;
        resetGeminiTurnDetector();
        setState('listening', 'Moon vẫn đang nghe — hãy thử nói lại');
        dispatch('listening');
        armWakeIdleTimeout();
    }, 15000);
}

function armBrainTranscriptTimeout() {
    clearTimeout(brainTranscriptTimer);
    const token = generation;
    brainTranscriptTimer = setTimeout(() => {
        if (token !== generation || !active || pipeline !== 'brain' || brainWaiting) return;
        $('error').textContent = 'Gemini chưa trả transcript sau khi nghe giọng nói. Hãy thử nói lại hoặc kiểm tra kết nối STT.';
        showHeard('Chưa nhận diện được — hãy thử nói lại');
        setState('listening', 'Brain vẫn đang nghe — hãy thử nói lại');
        dispatch('transcription_timeout');
    }, 15000);
}

function startMicDiagnostics(track) {
    clearInterval(micMonitorTimer);
    micStats = {frames: 0, rmsTotal: 0, rmsPeak: 0, activeFrames: 0};
    lastSpeechEventAt = Date.now();
    micMonitorTimer = setInterval(() => {
        const stats = micStats;
        micStats = {frames: 0, rmsTotal: 0, rmsPeak: 0, activeFrames: 0};
        if (!active || !context || !track) return;
        const rmsAverage = stats.frames ? stats.rmsTotal / stats.frames : 0;
        const liveTracks = stream?.getAudioTracks().filter(item => item.readyState === 'live').length || 0;
        console.info(`[LIVE MIC] frames=${stats.frames} rms_avg=${rmsAverage.toFixed(5)} rms_peak=${stats.rmsPeak.toFixed(5)} active_frames=${stats.activeFrames} streams=${stream ? 1 : 0} tracks=${liveTracks} track=${track.readyState} muted=${track.muted} context=${context.state}`);
        if (track.muted) {
            micDiagnosticError = true;
            $('error').textContent = 'Microphone đang bị trình duyệt tạm tắt. Kiểm tra thiết bị hoặc quyền microphone.';
            showHeard('Microphone đang bị tắt tiếng');
        } else if (!stats.frames && Date.now() - startedAt >= 10000) {
            micDiagnosticError = true;
            $('error').textContent = 'AudioWorklet chưa tạo frame từ microphone. Hãy dừng rồi thử lại và kiểm tra quyền microphone của trình duyệt.';
            showHeard('Không nhận được frame audio từ microphone');
            setState('error', 'Luồng thu microphone không hoạt động');
        } else if (stats.frames && rmsAverage < 0.00003 && stats.rmsPeak < 0.0001
                && Date.now() - startedAt >= 10000) {
            micDiagnosticError = true;
            $('error').textContent = 'Mic đang gửi frame nhưng gần như không có tín hiệu. Kiểm tra đúng thiết bị đầu vào và âm lượng mic.';
            showHeard('Chưa có tín hiệu âm thanh từ microphone');
            setState('error', 'Microphone chưa có tín hiệu');
        } else if (pipeline === 'brain' && stats.activeFrames >= 10
                && Date.now() - lastSpeechEventAt >= 10000) {
            micDiagnosticError = true;
            $('error').textContent = 'Mic có tín hiệu âm thanh nhưng Gemini chưa phát hiện giọng nói. Kiểm tra thiết bị, khoảng cách và mức âm lượng.';
            showHeard('Có tín hiệu audio — chưa phát hiện giọng nói');
            setState('listening', 'Mic có tín hiệu — đang chờ Gemini phát hiện lời nói');
        } else if (micDiagnosticError && !track.muted && (rmsAverage >= 0.00003 || stats.frames === 0)) {
            micDiagnosticError = false;
            $('error').textContent = '';
            if (pipeline === 'brain' && active) {
                showHeard('Đang chờ giọng nói…');
                setState('listening', 'Brain đang nghe — không cần gọi Moon');
            } else if (active) {
                setState('listening', 'Microphone đã có tín hiệu');
            }
        }
    }, 3000);
}

function detectGeminiTurnEnd(rms) {
    if (pipeline !== 'gemini' || phase !== 'live' || !ready
            || !ws || ws.readyState !== WebSocket.OPEN) return;
    const threshold = Math.max(.001, localNoise * 1.5);
    const speech = rms >= threshold;
    if (!localSpeech && !speech) localNoise = localNoise * .985 + rms * .015;
    localSpeechVotes.push(speech);
    if (localSpeechVotes.length > 5) localSpeechVotes.shift();
    if (!localSpeech && localSpeechVotes.filter(Boolean).length >= 3) {
        localSpeech = true;
        localSilenceFrames = 0;
        return;
    }
    if (!localSpeech) return;
    const stillSpeaking = rms >= Math.max(.0008, threshold * .65);
    localSilenceFrames = stillSpeaking ? 0 : localSilenceFrames + 1;
    if (localSilenceFrames < 30) return; // 900 ms: chốt câu nếu VAD Gemini bỏ lỡ.

    resetGeminiTurnDetector();
    responseStartedAt = performance.now();
    ws.send(JSON.stringify({command: 'audio_stream_end'}));
    armGeminiResponseTimeout();
    setState('thinking', 'Đã nghe xong — đang chờ Gemini trả lời…');
    showLatency('đang chờ phản hồi');
    dispatch('thinking');
}

async function acquireMicLock() {
    if (!navigator.locks || micLockHeld) return true;
    let settle;
    const acquired = new Promise(resolve => { settle = resolve; });
    navigator.locks.request('moon-voice-microphone', {mode: 'exclusive', ifAvailable: true}, lock => {
        if (!lock) { settle(false); return; }
        micLockHeld = true;
        settle(true);
        return new Promise(resolve => { releaseMicLock = resolve; });
    }).catch(() => settle(false));
    return acquired;
}

function unlockMicrophone() {
    micLockHeld = false;
    const release = releaseMicLock;
    releaseMicLock = undefined;
    if (release) release();
}

function clearPlayback() {
    playbackGeneration++;
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    if (fallbackAudioElement) {
        fallbackAudioElement.onended = null;
        fallbackAudioElement.onerror = null;
        fallbackAudioElement.pause();
        fallbackAudioElement.removeAttribute('src');
        fallbackAudioElement.load();
        fallbackAudioElement = null;
    }
    if (fallbackAudioUrl) URL.revokeObjectURL(fallbackAudioUrl);
    fallbackAudioUrl = null;
    pendingFallbackAudio = null;
    $('unmute').hidden = true;
    decodingCount = 0;
    for (const node of playing) {
        node.onended = null;
        try { node.stop(); } catch (_) {}
        try { node.disconnect(); } catch (_) {}
    }
    playing.clear();
    playHead = context?.currentTime || 0;
    turnComplete = false;
}

function speakBrowserFallback(text, reason) {
    if (!('speechSynthesis' in window) || typeof SpeechSynthesisUtterance === 'undefined') {
        $('error').textContent = 'Edge/Gemini không có audio và trình duyệt không hỗ trợ giọng dự phòng.';
        setState('error', 'Không phát được âm thanh');
        if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({command: 'playback_complete'}));
        return;
    }
    const utterance = new SpeechSynthesisUtterance(String(text || '').trim());
    utterance.lang = 'vi-VN';
    utterance.rate = .96;
    const vietnameseVoice = window.speechSynthesis.getVoices().find(voice =>
        String(voice.lang || '').toLowerCase().startsWith('vi'));
    if (vietnameseVoice) utterance.voice = vietnameseVoice;
    utterance.onstart = () => {
        if (responseStartedAt) showLatency(`${Math.round(performance.now() - responseStartedAt)} ms tới âm thanh dự phòng`);
        setState('speaking', 'Đang phát giọng dự phòng của trình duyệt…');
        dispatch('speaking');
    };
    const finish = () => {
        if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({command: 'playback_complete'}));
        setState('listening', 'Moon đang nghe — cứ nói tự nhiên');
        armWakeIdleTimeout();
    };
    utterance.onend = finish;
    utterance.onerror = finish;
    $('error').textContent = `Edge TTS tạm lỗi (${reason || 'không có audio'}); đang dùng giọng trình duyệt cho câu này.`;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
}

function notifyPlaybackComplete() {
    if (!turnComplete || playing.size > 0 || fallbackAudioElement || pendingFallbackAudio
            || decodingCount > 0 || !ws || ws.readyState !== WebSocket.OPEN) return;
    turnComplete = false;
    ws.send(JSON.stringify({command: 'playback_complete'}));
    armWakeIdleTimeout();
}

async function playAudioBuffer(buffer) {
    if (!context) throw new Error('AudioContext is not initialized');
    if (context.state !== 'running') await context.resume();
    if (context.state !== 'running') throw new Error('AudioContext is not running');
    const node = context.createBufferSource();
    node.buffer = buffer;
    node.connect(context.destination);
    const startAt = Math.max(context.currentTime + 0.035, playHead);
    playHead = startAt + buffer.duration;
    playing.add(node);
    node.onended = () => {
        playing.delete(node);
        try { node.disconnect(); } catch (_) {}
        notifyPlaybackComplete();
    };
    node.start(startAt);
    return node;
}

function playPcm24k(arrayBuffer) {
    if (!context || arrayBuffer.byteLength < 2) return;
    const view = new DataView(arrayBuffer);
    const samples = Math.floor(arrayBuffer.byteLength / 2);
    const buffer = context.createBuffer(1, samples, 24000);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < samples; i++) channel[i] = view.getInt16(i * 2, true) / 32768;

    void playAudioBuffer(buffer).catch(error => {
        console.error('[AUDIO] PCM playback failed:', error?.name || 'Error');
        $('error').textContent = 'Trình duyệt chưa phát được âm thanh. Hãy bấm để bật tiếng.';
        $('unmute').hidden = false;
    });
}

async function playHtmlAudio(arrayBuffer, token) {
    if (token !== playbackGeneration || !arrayBuffer?.byteLength) return false;
    if (fallbackAudioElement) {
        fallbackAudioElement.pause();
        fallbackAudioElement.onended = null;
        fallbackAudioElement.onerror = null;
    }
    if (fallbackAudioUrl) URL.revokeObjectURL(fallbackAudioUrl);
    fallbackAudioUrl = URL.createObjectURL(new Blob([arrayBuffer], {type: 'audio/mpeg'}));
    fallbackAudioElement = new Audio(fallbackAudioUrl);
    fallbackAudioElement.preload = 'auto';
    pendingFallbackAudio = arrayBuffer;
    const audio = fallbackAudioElement;
    audio.onended = () => {
        if (audio !== fallbackAudioElement) return;
        fallbackAudioElement = null;
        pendingFallbackAudio = null;
        if (fallbackAudioUrl) URL.revokeObjectURL(fallbackAudioUrl);
        fallbackAudioUrl = null;
        $('unmute').hidden = true;
        notifyPlaybackComplete();
    };
    audio.onerror = () => {
        if (audio !== fallbackAudioElement) return;
        fallbackAudioElement = null;
        pendingFallbackAudio = null;
        $('error').textContent = 'Web Audio và HTML Audio không phát được MP3 Edge TTS.';
        $('unmute').hidden = true;
        if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({command: 'playback_failed'}));
    };
    try {
        await audio.play();
        if (token !== playbackGeneration) return false;
        pendingFallbackAudio = null;
        $('unmute').hidden = true;
        $('error').textContent = '';
        console.info('[AUDIO] HTMLAudio fallback playback started');
        return true;
    } catch (error) {
        if (token !== playbackGeneration) return false;
        if (error?.name === 'NotAllowedError') {
            $('error').textContent = 'Trình duyệt đã chặn tự động phát âm thanh. Bấm nút bên dưới để bật tiếng.';
            $('unmute').hidden = false;
            setState('error', 'Cần thao tác để bật âm thanh');
            console.warn('[AUDIO] HTMLAudio playback blocked; user gesture required');
            return false;
        }
        audio.onerror = null;
        audio.onended = null;
        audio.pause();
        audio.removeAttribute('src');
        audio.load();
        if (fallbackAudioElement === audio) fallbackAudioElement = null;
        pendingFallbackAudio = null;
        if (fallbackAudioUrl) URL.revokeObjectURL(fallbackAudioUrl);
        fallbackAudioUrl = null;
        throw error;
    }
}

async function playEncodedAudio(arrayBuffer) {
    if (!arrayBuffer || arrayBuffer.byteLength === 0) {
        console.warn('[AUDIO] Empty binary audio payload received');
        return;
    }
    console.log('[AUDIO] Playing audio payload bytes:', arrayBuffer.byteLength);
    const token = playbackGeneration;
    decodingCount++;
    try {
        if (!context) throw new Error('AudioContext is not initialized');
        if (context.state !== 'running') await context.resume();
        const buffer = await context.decodeAudioData(arrayBuffer.slice(0));
        if (token === playbackGeneration && context) await playAudioBuffer(buffer);
    } catch (error) {
        if (token === playbackGeneration) {
            console.warn('[AUDIO] Web Audio decode/play failed:', error?.name || 'Error');
            try {
                await playHtmlAudio(arrayBuffer, token);
            } catch (fallbackError) {
                $('error').textContent = `Không phát được MP3 Edge TTS (${fallbackError?.name || 'lỗi audio'}).`;
                if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({command: 'playback_failed'}));
            }
        }
    } finally {
        if (token === playbackGeneration) {
            decodingCount = Math.max(0, decodingCount - 1);
            notifyPlaybackComplete();
        }
    }
}

function activateAudioFromGesture() {
    try {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextClass) throw new Error('Web Audio API is unavailable');
        if (!context || context.state === 'closed') context = new AudioContextClass();
        playHead = context.currentTime;
        const resume = context.resume();
        return resume.catch(error => {
            console.warn('[AUDIO] AudioContext resume deferred:', error?.name || 'Error');
            return false;
        });
    } catch (error) {
        console.warn('[AUDIO] AudioContext initialization failed:', error?.name || 'Error');
        return Promise.resolve(false);
    }
}

async function unlockAudioFromButton() {
    try {
        if (context && context.state !== 'running') await context.resume();
        const payload = pendingFallbackAudio;
        const token = playbackGeneration;
        if (payload) {
            await playHtmlAudio(payload, token);
            return;
        }
        $('unmute').hidden = true;
        $('error').textContent = '';
    } catch (error) {
        $('error').textContent = `Không bật được âm thanh (${error?.name || 'lỗi audio'}).`;
    }
}

function handleServer(message) {
    if (message.event === 'connecting' || message.event === 'connected') {
        setState('connecting', 'Đang mở phiên Gemini Live…');
    } else if (message.event === 'ready') {
        ready = true;
        resetGeminiTurnDetector();
        if (pipeline === 'brain') {
            outputMode = 'brain';
            $('model').textContent = 'Brain · Gemini STT (VI/EN/JA) · Qwen 3.5 2B · Edge TTS';
            showHeard('Đang chờ giọng nói…');
            setState('listening', message.calibrating
                ? 'Đang đo tiếng nền — hãy giữ im lặng' : 'Brain đang nghe — không cần gọi Moon');
            dispatch('ready', {engine: message.engine});
            return;
        }
        outputMode = message.outputMode || 'native';
        incomingFormat = outputMode === 'edge' ? 'mp3' : 'pcm';
        $('model').textContent = `${message.model} · ${message.voice}`;
        setState('listening', 'Moon đang nghe — cứ nói tự nhiên');
        dispatch('ready');
    } else if (message.event === 'user_speaking' || message.event === 'listening') {
        if (message.event === 'user_speaking') {
            lastSpeechEventAt = Date.now();
            if (micDiagnosticError) { micDiagnosticError = false; $('error').textContent = ''; }
            clearWakeIdleTimeout();
            clearTimeout(geminiResponseTimer);
            if (pipeline === 'brain') armBrainTranscriptTimeout();
            clearPlayback();
            $('error').textContent = '';
            turnTranscript = '';
            responseStartedAt = 0;
            showHeard(pipeline === 'brain' ? 'Đã phát hiện giọng nói…' : 'Đang nghe…');
            showLatency('đang đo');
        }
        setState(message.event === 'user_speaking' && pipeline === 'brain' ? 'speech_detected' : 'listening',
            message.event === 'user_speaking' ? 'Đã phát hiện giọng nói — đang nhận diện…' : 'Moon đang nghe — cứ nói tự nhiên');
        if (message.event === 'listening') {
            resetGeminiTurnDetector();
            armWakeIdleTimeout();
        }
        dispatch(message.event);
    } else if (message.event === 'thinking') {
        clearWakeIdleTimeout();
        resetGeminiTurnDetector();
        if (!responseStartedAt) responseStartedAt = performance.now();
        armGeminiResponseTimeout();
        setState('thinking', 'Moon đang suy nghĩ…');
        dispatch('thinking');
    } else if (message.event === 'edge_synthesizing') {
        clearWakeIdleTimeout();
        clearTimeout(geminiResponseTimer);
        setState('thinking', 'Đang tạo giọng Edge TTS Neural…');
        dispatch('thinking');
    } else if (message.event === 'browser_tts_fallback') {
        speakBrowserFallback(message.text, message.reason);
    } else if (message.event === 'speaking') {
        clearWakeIdleTimeout();
        clearTimeout(geminiResponseTimer);
        resetGeminiTurnDetector();
        incomingFormat = message.format || (outputMode === 'edge' ? 'mp3' : 'pcm');
        if (responseStartedAt) showLatency(`${Math.round(performance.now() - responseStartedAt)} ms tới âm thanh`);
        setState('speaking', 'Moon đang trả lời — bạn có thể ngắt lời');
        dispatch('speaking');
    } else if (message.event === 'input_transcript') {
        clearWakeIdleTimeout();
        turnTranscript += message.text || '';
        showHeard(turnTranscript);
    } else if (message.event === 'input_committed') {
        clearWakeIdleTimeout();
        if (!responseStartedAt) responseStartedAt = performance.now();
        setState('thinking', 'Gemini đã nhận câu — đang tạo phản hồi…');
    } else if (pipeline === 'brain' && message.event === 'calibrated') {
        setState('listening', 'Brain đang nghe — nói trực tiếp, không cần gọi Moon');
    } else if (pipeline === 'brain' && message.event === 'meter') {
        if (typeof message.rms === 'number') $('level').value = message.rms;
    } else if (pipeline === 'brain' && message.event === 'processing') {
        lastSpeechEventAt = Date.now();
        clearWakeIdleTimeout();
        armBrainTranscriptTimeout();
        setState('transcribing', 'Đang chuyển giọng nói thành văn bản…');
    } else if (pipeline === 'brain' && message.event === 'partial') {
        lastSpeechEventAt = Date.now();
        clearWakeIdleTimeout();
        armBrainTranscriptTimeout();
        $('error').textContent = '';
        showHeard(message.text || 'Đang nghe…');
        showLatency('STT trực tiếp');
    } else if (pipeline === 'brain' && message.event === 'transcript') {
        clearWakeIdleTimeout();
        clearTimeout(brainTranscriptTimer);
        showHeard(message.text);
        setState('recognized', 'Đã nhận diện transcript — đang chuyển cho Brain…');
        showCorrected('', false);
        showLatency(`STT ${message.latency_ms || 0} ms · đang chờ Brain`);
    } else if (pipeline === 'brain' && message.event === 'question') {
        clearWakeIdleTimeout();
        clearTimeout(brainTranscriptTimer);
        brainWaiting = true;
        responseStartedAt = performance.now();
        showHeard(message.text);
        setState('thinking', 'Brain và LLM đang xử lý…');
        if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({command: 'pause'}));
        dispatch('brain_question', {text: message.text});
        clearTimeout(brainTimer);
        brainTimer = setTimeout(() => {
            if (!brainWaiting) return;
            $('error').textContent = 'Brain chưa phản hồi sau 60 giây. Mic đã được mở lại.';
            brainWaiting = false;
            if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({command: 'resume'}));
            setState('listening', 'Brain đang nghe — hãy thử hỏi lại');
            armWakeIdleTimeout();
        }, 60000);
    } else if (pipeline === 'brain' && message.event === 'rejected') {
        clearTimeout(brainTranscriptTimer);
        $('error').textContent = message.text || 'Chưa nghe rõ — hãy nói lại.';
        setState('listening', 'Brain đang nghe — hãy nói lại');
        armWakeIdleTimeout();
    } else if (pipeline === 'brain' && message.event === 'state') {
        if (!brainWaiting) {
            setState('listening', 'Brain đang nghe — không cần gọi Moon');
            armWakeIdleTimeout();
        }
    } else if (message.event === 'edge_fallback') {
        $('error').textContent = message.text || 'Edge TTS tạm lỗi; đang dùng giọng Gemini cho câu này.';
        setState('speaking', 'Đang chuyển sang giọng Gemini dự phòng…');
    } else if (message.event === 'interrupted') {
        clearPlayback();
        setState('listening', 'Đã ngắt câu trả lời — Moon đang nghe');
        dispatch('interrupted');
        armWakeIdleTimeout();
    } else if (message.event === 'turn_complete') {
        turnComplete = true;
        notifyPlaybackComplete();
    } else if (message.event === 'turn_error') {
        clearTimeout(geminiResponseTimer);
        $('error').textContent = message.text || 'Không tạo được câu trả lời bằng Edge TTS.';
        setState('error', 'Lỗi tạo giọng — phiên vẫn đang nghe');
        dispatch('error', {text: message.text});
        armWakeIdleTimeout();
    } else if (message.event === 'expression') {
        dispatch('expression', {expression: message.expression});
    } else if (message.event === 'reconnecting') {
        clearWakeIdleTimeout();
        setState('connecting', message.text || 'Đang làm mới phiên…');
    } else if (message.event === 'error') {
        clearWakeIdleTimeout();
        clearTimeout(geminiResponseTimer);
        $('error').textContent = message.text;
        setState('error', 'Không thể bắt đầu Live Talk');
        dispatch('error', {text: message.text});
    }
}

function handleWakeServer(message, token) {
    if (token !== generation || phase !== 'wake') return;
    if (message.event === 'ready') {
        ready = true;
        wakeCalibrating = Boolean(message.calibrating);
        setState(wakeCalibrating ? 'connecting' : 'waiting', wakeCalibrating
            ? 'Đang đo tiếng nền — hãy giữ im lặng' : 'Đang chờ bạn gọi tên “Moon”');
        $('model').textContent = `Wakeword · ${message.engine || 'Whisper'}`;
    } else if (message.event === 'calibrated' || message.event === 'resumed') {
        wakeCalibrating = false;
        setState('waiting', 'Sẵn sàng — chỉ cần gọi “Moon”, “Môn” hoặc “Mun”');
    } else if (message.event === 'recalibrating') {
        wakeCalibrating = true;
        setState('connecting', 'Tiếng nền thay đổi — hãy giữ im lặng để đo lại');
    } else if (message.event === 'meter') {
        if (typeof message.rms === 'number') $('level').value = message.rms;
    } else if (message.event === 'processing') {
        setState('waiting', 'Đang kiểm tra từ khóa…');
    } else if (message.event === 'partial') {
        showHeard(message.text || 'Đang nghe tên Moon…');
    } else if (message.event === 'verifying_wake') {
        if (message.text) showHeard(`Đang xác minh: ${message.text}`);
        setState('waiting', 'Đang xác minh tên Moon…');
    } else if (message.event === 'verification_timeout') {
        showHeard(message.text
            ? `Xác minh quá thời gian: ${message.text}`
            : 'Xác minh wakeword quá thời gian');
        $('error').textContent = 'Mạng xác minh wakeword chậm — hãy gọi lại tên Moon.';
        setState('waiting', 'Chưa xác minh được — hãy gọi lại tên Moon');
    } else if (message.event === 'transcript') {
        showHeard(message.text || 'Đã nhận wakeword');
        showLatency(`wake STT ${message.latency_ms || 0} ms`);
    } else if (message.event === 'ignored') {
        showHeard(message.text ? `Chưa khớp wakeword: ${message.text}` : 'Chưa nghe rõ wakeword');
        showLatency(`wake STT ${message.latency_ms || 0} ms`);
        if (!promotingWake) setState('waiting', 'Chưa nghe thấy tên Moon — hãy gọi lại');
    } else if (message.event === 'state') {
        if (!promotingWake) setState('waiting', 'Đang chờ bạn gọi tên Moon');
    } else if (message.event === 'wake') {
        void promoteWakeToLive(token);
    } else if (message.event === 'error') {
        $('error').textContent = message.text || 'Không thể nhận diện wakeword.';
        setState('error', 'Wakeword gặp lỗi');
    }
}

async function connectWakeSocket(token) {
    const endpoint = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/transcribe/ws?mode=wake`;
    const socket = new WebSocket(endpoint);
    ws = socket;
    await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error('Bộ nhận wakeword không phản hồi sau 25 giây.')), 25000);
        socket.onerror = () => { clearTimeout(timeout); reject(new Error('Không kết nối được bộ nhận wakeword.')); };
        socket.onclose = event => { clearTimeout(timeout); reject(new Error(event.reason || 'Bộ nhận wakeword đã đóng kết nối.')); };
        socket.onmessage = event => {
            if (token !== generation || typeof event.data !== 'string') return;
            const message = JSON.parse(event.data);
            handleWakeServer(message, token);
            if (message.event === 'ready') { clearTimeout(timeout); resolve(); }
            if (message.event === 'error') { clearTimeout(timeout); reject(new Error(message.text)); }
        };
    });
    socket.onmessage = event => {
        if (token === generation && typeof event.data === 'string') {
            handleWakeServer(JSON.parse(event.data), token);
        }
    };
    socket.onclose = event => {
        if (token !== generation || promotingWake || (!active && !starting)) return;
        $('error').textContent ||= event.reason || 'Bộ nhận wakeword đã ngắt.';
        stop(false, true);
    };
}

async function promoteWakeToLive(token) {
    if (promotingWake || token !== generation || phase !== 'wake') return;
    promotingWake = true;
    clearWakeIdleTimeout();
    clearTimeout(brainTranscriptTimer);
    wakeCalibrating = false;
    ready = false;
    wakeTick();
    setState('connecting', 'Đã nghe tên Moon — đang mở hội thoại trực tiếp…');
    showHeard('Đã nhận ra tên Moon');
    showLatency('đang kết nối hội thoại');
    dispatch('wake');

    const wakeSocket = ws;
    ws = null;
    if (wakeSocket) {
        wakeSocket.onclose = null;
        if (wakeSocket.readyState === WebSocket.OPEN) {
            wakeSocket.send(JSON.stringify({command: 'pause'}));
        }
        wakeSocket.close();
    }

    try {
        phase = 'live';
        await connectSocket(token);
        if (token !== generation) return;
        await playWakeAcknowledgement(token);
        if (token !== generation) return;
        promotingWake = false;
        wakeTick();
        setState('listening', pipeline === 'brain'
            ? 'Đã thức — Brain đang nghe, bạn hãy nói tự nhiên'
            : 'Đã thức — Moon đang nghe, bạn hãy nói tự nhiên');
        dispatch('listening', {activatedBy: 'wakeword'});
        armWakeIdleTimeout();
    } catch (error) {
        if (token !== generation) return;
        promotingWake = false;
        $('error').textContent = error.message;
        await stop(false, true);
    }
}

async function returnLiveToWake(token) {
    if (returningToWake || token !== generation || !active
            || activation !== 'wakeword' || phase !== 'live') return;
    returningToWake = true;
    clearWakeIdleTimeout();
    clearTimeout(brainTimer);
    clearTimeout(brainResumeTimer);
    clearTimeout(brainTranscriptTimer);
    clearTimeout(geminiResponseTimer);
    brainWaiting = false;
    ready = false;
    resetGeminiTurnDetector();
    clearPlayback();
    $('error').textContent = '';
    setState('connecting', 'Đã im lặng 1 phút — đang quay lại chờ tên Moon…');
    dispatch('idle_timeout', {seconds: Math.round(WAKE_IDLE_TIMEOUT_MS / 1000)});

    const liveSocket = ws;
    ws = null;
    if (liveSocket) {
        liveSocket.onmessage = null;
        liveSocket.onclose = null;
        liveSocket.onerror = null;
        if (liveSocket.readyState === WebSocket.OPEN) {
            liveSocket.send(JSON.stringify({
                command: pipeline === 'brain' ? 'pause' : 'audio_stream_end',
            }));
        }
        liveSocket.close();
    }

    try {
        phase = 'wake';
        await connectWakeSocket(token);
        if (token !== generation) return;
        returningToWake = false;
        showHeard('Phiên hội thoại đã nghỉ do im lặng');
        showCorrected('', false);
        showLatency('đã quay lại chờ wakeword');
        setState(wakeCalibrating ? 'connecting' : 'waiting', wakeCalibrating
            ? 'Đang đo lại tiếng nền — hãy giữ im lặng'
            : 'Sẵn sàng — chỉ cần gọi tên Moon');
        dispatch('waiting_wake', {
            calibrating: wakeCalibrating,
            reason: 'idle_timeout',
        });
    } catch (error) {
        if (token !== generation) return;
        returningToWake = false;
        $('error').textContent = error.message;
        await stop(false, true);
    }
}

async function connectSocket(token) {
    pipeline = $('pipeline').value === 'brain' ? 'brain' : 'gemini';
    const mode = $('mode').value === 'native' ? 'native' : 'edge';
    const path = pipeline === 'brain' ? '/transcribe/ws?mode=continuous&provider=edge' : `/live/ws?mode=${encodeURIComponent(mode)}&provider=edge`;
    const endpoint = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${path}`;
    const socket = new WebSocket(endpoint);
    socket.binaryType = 'arraybuffer';
    ws = socket;
    await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error(`${pipeline === 'brain' ? 'Voice/Brain' : 'Gemini Live'} không phản hồi sau 25 giây.`)), 25000);
        socket.onerror = () => { clearTimeout(timeout); reject(new Error('Không kết nối được Live Talk server.')); };
        socket.onclose = event => { clearTimeout(timeout); reject(new Error(event.reason || 'Live Talk server đã đóng kết nối.')); };
        socket.onmessage = event => {
            if (token !== generation) return;
            if (typeof event.data !== 'string') return;
            const message = JSON.parse(event.data);
            handleServer(message);
            if (message.event === 'ready') { clearTimeout(timeout); resolve(); }
            if (message.event === 'error') { clearTimeout(timeout); reject(new Error(message.text)); }
        };
    });
    socket.onmessage = event => {
        if (token !== generation) return;
        if (typeof event.data === 'string') handleServer(JSON.parse(event.data));
        else if (pipeline === 'gemini') {
            if (incomingFormat === 'mp3') void playEncodedAudio(event.data);
            else playPcm24k(event.data);
        }
    };
    socket.onclose = event => {
        if (token !== generation || (!active && !starting)) return;
        $('error').textContent ||= event.reason || 'Phiên Live Talk đã ngắt.';
        stop(false, true);
    };
}

async function openMicrophone(token) {
    if (!navigator.mediaDevices || !window.AudioWorkletNode) {
        throw new Error('Live Talk cần Chrome/Edge trên localhost hoặc HTTPS.');
    }
    const selected = $('device').value;
    setState('requesting_permission', 'Đang xin quyền truy cập microphone…');
    const micRequest = navigator.mediaDevices.getUserMedia({audio: {
        deviceId: selected ? {exact: selected} : undefined,
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: activation !== 'wakeword',
    }});
    let permissionTimer;
    let acquired;
    try {
        acquired = await Promise.race([
            micRequest,
            new Promise((_, reject) => {
                permissionTimer = setTimeout(() => reject(new Error(
                    'Yêu cầu quyền microphone đã chờ quá lâu. Hãy cấp quyền cho trang rồi thử lại.',
                )), 30000);
            }),
        ]);
    } catch (error) {
        micRequest.then(lateStream => lateStream.getTracks().forEach(track => track.stop())).catch(() => {});
        throw error;
    } finally {
        clearTimeout(permissionTimer);
    }
    if (token !== generation) { acquired.getTracks().forEach(track => track.stop()); return; }
    stream = acquired;
    console.info('[LIVE MIC] Microphone permission granted');
    const micTrack = stream.getAudioTracks()[0];
    if (!micTrack) throw new Error('Trình duyệt không trả về audio track từ microphone.');
    console.info(`[LIVE MIC] tracks=${stream.getAudioTracks().length} track=${micTrack?.readyState} muted=${micTrack?.muted}`);
    micTrack.onmute = () => {
        console.warn('[LIVE MIC] Microphone track muted');
        micDiagnosticError = true;
        $('error').textContent = 'Microphone đang bị trình duyệt tạm tắt.';
        showHeard('Microphone đang bị tắt tiếng');
        setState('error', 'Microphone đang bị tắt tiếng');
    };
    micTrack.onunmute = () => {
        console.info('[LIVE MIC] Microphone track unmuted');
        if (micDiagnosticError) {
            micDiagnosticError = false;
            $('error').textContent = '';
            setState('listening', 'Microphone đã kết nối — đang chờ giọng nói');
        }
    };
    micTrack.onended = () => {
        $('error').textContent = 'Microphone đã ngắt kết nối.';
        showHeard('Microphone đã ngắt kết nối');
        stop(false, true);
    };

    const devices = await navigator.mediaDevices.enumerateDevices();
    $('device').replaceChildren(new Option('Microphone mặc định', ''));
    devices.filter(device => device.kind === 'audioinput').forEach(device =>
        $('device').add(new Option(device.label || 'Microphone', device.deviceId)));
    $('device').value = selected;

    if (!context || context.state === 'closed') {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextClass) throw new Error('Trình duyệt không hỗ trợ Web Audio API.');
        context = new AudioContextClass();
    }
    try {
        await context.resume();
    } catch (error) {
        console.warn('[AUDIO] Capture context resume deferred:', error?.name || 'Error');
    }
    await context.audioWorklet.addModule('/voice-worklet.js');
    source = context.createMediaStreamSource(stream);
    highpass = context.createBiquadFilter();
    highpass.type = 'highpass';
    highpass.frequency.value = 120;
    highpass.Q.value = 0.707;
    capture = new AudioWorkletNode(context, 'moon-capture');
    capture.port.onmessage = event => {
        const pcm = new Int16Array(event.data);
        let energy = 0;
        for (let i = 0; i < pcm.length; i++) energy += (pcm[i] / 32768) ** 2;
        const rms = Math.sqrt(energy / Math.max(1, pcm.length));
        $('level').value = rms;
        micStats.frames++;
        micStats.rmsTotal += rms;
        micStats.rmsPeak = Math.max(micStats.rmsPeak, rms);
        if (rms >= 0.001) micStats.activeFrames++;
        // Không gửi tiếng chuông/lời xác nhận của Moon ngược lại vào hội thoại.
        if (!ready || promotingWake || !ws || ws.readyState !== WebSocket.OPEN) return;
        if (ws.bufferedAmount > 65536) return;
        if (!micAudioLogSent) {
            micAudioLogSent = true;
            console.info('[LIVE MIC] First 16 kHz PCM chunk sent');
        }
        ws.send(event.data);
        detectGeminiTurnEnd(rms);
    };
    source.connect(highpass);
    highpass.connect(capture);
    capture.connect(context.destination); // Worklet chỉ phát silence.
    startMicDiagnostics(micTrack);
    console.info(`[LIVE MIC] Capture started context_sample_rate=${context.sampleRate} pcm_rate=16000 frame_samples=480 channels=1`);
}

async function start() {
    if (starting || active) return;
    // Create/resume Web Audio synchronously from the Start button gesture,
    // before waiting on permission prompts or the WebSocket handshake.
    const audioActivation = activateAudioFromGesture();
    starting = true;
    const token = ++generation;
    $('error').textContent = '';
    micDiagnosticError = false;
    $('start').disabled = true;
    $('stop').disabled = false;
    $('pipeline').disabled = true;
    $('mode').disabled = true;
    $('activation').disabled = true;
    $('device').disabled = true;
    setState('connecting', 'Đang chuẩn bị Live Talk…');
    pipeline = $('pipeline').value === 'brain' ? 'brain' : 'gemini';
    activation = $('activation').value === 'wakeword' ? 'wakeword' : 'manual';
    phase = activation === 'wakeword' ? 'wake' : 'live';
    promotingWake = false;
    returningToWake = false;
    clearWakeIdleTimeout();
    wakeCalibrating = false;
    localNoise = .0015;
    resetGeminiTurnDetector();
    micAudioLogSent = false;
    clearPlayback();
    turnTranscript = '';
    brainWaiting = false;
    showHeard('Đang chuẩn bị…');
    showCorrected('', false);
    showLatency('đang đo');
    dispatch('starting');
    window.dispatchEvent(new Event('moon-live-request-mic'));
    try {
        await audioActivation;
        if (!await acquireMicLock()) throw new Error('Microphone đang được dùng ở tab Moon khác.');
        if (phase === 'wake') await connectWakeSocket(token);
        else await connectSocket(token);
        active = true;
        await openMicrophone(token);
        if (token !== generation) return;
        starting = false;
        startedAt = Date.now();
        clockTimer = setInterval(() => {
            const seconds = Math.floor((Date.now() - startedAt) / 1000);
            $('duration').textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
        }, 1000);
        if (phase === 'wake') {
            // Chuẩn bị sẵn câu xác nhận trong lúc chờ wakeword; không làm tốn
            // Edge acknowledgement is cached by the server for repeated wakeword use.
            void fetch('/api/live-ack', {cache: 'force-cache'}).catch(() => {});
            setState(wakeCalibrating ? 'connecting' : 'waiting', wakeCalibrating
                ? 'Đang đo tiếng nền — hãy giữ im lặng'
                : 'Sẵn sàng — chỉ cần gọi tên Moon');
            dispatch('waiting_wake', {calibrating: wakeCalibrating});
        } else {
            setState('listening', pipeline === 'brain'
                ? 'Brain đang nghe — nói trực tiếp, không cần gọi Moon'
                : 'Moon đang nghe — cứ nói tự nhiên');
            dispatch('listening', {activatedBy: 'manual'});
        }
    } catch (error) {
        if (token === generation) {
            $('error').textContent = error.message;
            await stop(false, true);
        }
    }
}

async function stop(userRequested = true, preserveError = false) {
    generation++;
    starting = false;
    active = false;
    ready = false;
    promotingWake = false;
    returningToWake = false;
    wakeCalibrating = false;
    resetGeminiTurnDetector();
    clearInterval(clockTimer);
    clearInterval(micMonitorTimer);
    clearTimeout(brainTimer);
    clearTimeout(brainResumeTimer);
    clearTimeout(brainTranscriptTimer);
    clearTimeout(geminiResponseTimer);
    clearWakeIdleTimeout();
    brainWaiting = false;
    clearPlayback();
    if (capture) { capture.port.onmessage = null; capture.disconnect(); capture = null; }
    if (source) { source.disconnect(); source = null; }
    if (highpass) { highpass.disconnect(); highpass = null; }
    stream?.getTracks().forEach(track => track.stop());
    stream = null;
    const socket = ws;
    ws = null;
    if (socket) {
        socket.onclose = null;
        if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({
            command: phase === 'wake' || pipeline === 'brain' ? 'pause' : 'audio_stream_end',
        }));
        socket.close();
    }
    const oldContext = context;
    context = null;
    if (oldContext && oldContext.state !== 'closed') await oldContext.close();
    unlockMicrophone();
    $('start').disabled = false;
    $('stop').disabled = true;
    $('pipeline').disabled = false;
    $('activation').disabled = false;
    $('device').disabled = false;
    $('level').value = 0;
    $('duration').textContent = '00:00';
    if (!preserveError) $('error').textContent = '';
    setState(preserveError ? 'error' : (userRequested ? 'stopped' : 'idle'),
        preserveError ? 'Phiên Live Talk đã dừng do lỗi' : (userRequested ? 'Đã dừng Live Talk' : 'Sẵn sàng kết nối'));
    dispatch(preserveError ? 'error' : 'stopped', preserveError ? {text: $('error').textContent} : {});
    if (userRequested) $('state').textContent = 'Đã kết thúc Live Talk';
    phase = 'idle';
    updatePipelineUi();
}

function updatePipelineUi() {
    pipeline = $('pipeline').value === 'brain' ? 'brain' : 'gemini';
    activation = $('activation').value === 'wakeword' ? 'wakeword' : 'manual';
    const brain = pipeline === 'brain';
    if (brain) $('mode').value = 'edge';
    $('mode').disabled = brain || active || starting;
    const activationText = activation === 'wakeword'
        ? ' Moon chỉ mở hội thoại sau khi nghe tên mình hoặc cách phát âm gần giống; 60 giây im lặng sẽ quay lại chờ wakeword.'
        : ' Hội thoại bắt đầu ngay khi bạn bấm nút.';
    $('description').textContent = (brain
        ? 'Gemini STT nhận tiếng Việt, Anh và Nhật rồi chuyển câu nói cho Qwen local; Edge TTS Neural đọc câu trả lời.'
        : 'Gemini nghe và hiểu âm thanh trực tiếp; có thể trả lời bằng Edge TTS Neural hoặc Gemini Native.')
        + activationText + ' OLED chỉ hiển thị biểu cảm phù hợp.';
    $('model').textContent = brain
        ? 'Brain · Gemini STT (VI/EN/JA) · Qwen 3.5 2B · Edge TTS'
        : `gemini-3.8-live · ${$('mode').value === 'edge' ? 'Edge TTS Neural' : 'Kore'}`;
    $('start').innerHTML = activation === 'wakeword'
        ? '<i data-lucide="ear"></i> Bắt đầu chờ tên Moon'
        : '<i data-lucide="radio"></i> Bắt đầu Live Talk';
    if (window.lucide) lucide.createIcons();
    if (!active && !starting) $('state').textContent = activation === 'wakeword'
        ? 'Sẵn sàng chờ bạn gọi tên Moon'
        : (brain ? 'Sẵn sàng kết nối Brain Live' : 'Sẵn sàng kết nối Gemini Live');
    showHeard('Chưa có dữ liệu');
    showCorrected('', false);
    showLatency('—');
}

$('start').onclick = start;
$('stop').onclick = () => stop(true);
$('unmute').onclick = unlockAudioFromButton;
$('pipeline').onchange = updatePipelineUi;
$('activation').onchange = updatePipelineUi;
$('mode').onchange = () => {
    const edge = $('mode').value === 'edge';
    $('model').textContent = edge ? 'gemini-3.8-live · Edge TTS Neural' : 'gemini-3.8-live · Kore';
    $('state').textContent = edge
        ? 'Phản hồi bằng Edge TTS Neural'
        : 'Gemini Native phản hồi nhanh hơn';
};
window.addEventListener('moon-brain-pipeline', ({detail}) => {
    if (!active || pipeline !== 'brain') return;
    if (detail.event === 'corrected') {
        showCorrected(detail.changed ? detail.text : 'Giữ nguyên câu STT');
        setState('thinking', detail.changed
            ? 'Brain đã sửa lỗi nghe nhầm — đang hỏi LLM…'
            : 'Brain xác nhận câu STT — đang hỏi LLM…');
    } else if (detail.event === 'state' && detail.state === 'thinking') {
        setState('thinking', 'Brain và LLM đang xử lý…');
    } else if (detail.event === 'answer_ready' && $('orb').dataset.state !== 'speaking') {
        setState('thinking', 'Đã có câu trả lời — đang tạo giọng Edge TTS…');
    } else if (detail.event === 'tts_fallback') {
        $('error').textContent = detail.text || 'Edge TTS lỗi — câu trả lời chưa phát được.';
        setState('error', 'Không phát được câu trả lời bằng Edge TTS');
    } else if (detail.event === 'state' && detail.state === 'speaking') {
        if (responseStartedAt) showLatency(`${Math.round(performance.now() - responseStartedAt)} ms tới âm thanh`);
        setState('speaking', 'Moon đang trả lời bằng Brain + Edge TTS…');
    } else if (detail.event === 'state' && detail.state === 'standby' && brainWaiting) {
        clearTimeout(brainTimer);
        clearTimeout(brainResumeTimer);
        const token = generation;
        brainResumeTimer = setTimeout(() => {
            if (token !== generation || !active || pipeline !== 'brain') return;
            brainWaiting = false;
            if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({command: 'resume'}));
            setState('listening', 'Brain đang nghe — nói câu tiếp theo');
            armWakeIdleTimeout();
        }, 1200);
    }
});
updatePipelineUi();
window.addEventListener('pagehide', () => stop(false));
})();
