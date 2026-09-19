(() => {
const $ = id => document.getElementById(`live-${id}`);
let stream, context, source, highpass, capture, ws;
let starting = false, active = false, ready = false, generation = 0;
let releaseMicLock, micLockHeld = false, startedAt = 0, clockTimer;
let playHead = 0, turnComplete = false, outputMode = 'fish', incomingFormat = 'mp3';
let playbackGeneration = 0, decodingCount = 0;
let pipeline = 'gemini', turnTranscript = '', responseStartedAt = 0;
let brainWaiting = false, brainTimer, brainResumeTimer;
let geminiResponseTimer;
let activation = 'manual', phase = 'idle', promotingWake = false, wakeCalibrating = false;
let localSpeech = false, localSilenceFrames = 0, localNoise = .0015;
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
        idle: 'Chưa chạy', connecting: 'Đang kết nối', listening: 'Đang nghe',
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

function resetGeminiTurnDetector() {
    localSpeech = false;
    localSilenceFrames = 0;
    localSpeechVotes.length = 0;
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
    }, 15000);
}

function detectGeminiTurnEnd(rms) {
    if (pipeline !== 'gemini' || phase !== 'live' || !ready
            || !ws || ws.readyState !== WebSocket.OPEN) return;
    const threshold = Math.max(.0035, localNoise * 2.5);
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
    const stillSpeaking = rms >= Math.max(.0025, threshold * .65);
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
    }).catch(() => settle(true));
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
        $('error').textContent = 'Fish/Gemini không có audio và trình duyệt không hỗ trợ giọng dự phòng.';
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
    };
    utterance.onend = finish;
    utterance.onerror = finish;
    $('error').textContent = `Fish Audio tạm lỗi (${reason || 'không có audio'}); đang dùng giọng trình duyệt cho câu này.`;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
}

function notifyPlaybackComplete() {
    if (!turnComplete || playing.size > 0 || decodingCount > 0 || !ws || ws.readyState !== WebSocket.OPEN) return;
    turnComplete = false;
    ws.send(JSON.stringify({command: 'playback_complete'}));
}

function playAudioBuffer(buffer) {
    if (!context) return;
    const node = context.createBufferSource();
    node.buffer = buffer;
    node.connect(context.destination);
    const startAt = Math.max(context.currentTime + 0.035, playHead);
    playHead = startAt + buffer.duration;
    playing.add(node);
    node.onended = () => {
        playing.delete(node);
        node.disconnect();
        notifyPlaybackComplete();
    };
    node.start(startAt);
}

function playPcm24k(arrayBuffer) {
    if (!context || arrayBuffer.byteLength < 2) return;
    const view = new DataView(arrayBuffer);
    const samples = Math.floor(arrayBuffer.byteLength / 2);
    const buffer = context.createBuffer(1, samples, 24000);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < samples; i++) channel[i] = view.getInt16(i * 2, true) / 32768;

    playAudioBuffer(buffer);
}

async function playEncodedAudio(arrayBuffer) {
    if (!context || arrayBuffer.byteLength === 0) return;
    const token = playbackGeneration;
    decodingCount++;
    try {
        const buffer = await context.decodeAudioData(arrayBuffer.slice(0));
        if (token === playbackGeneration && context) playAudioBuffer(buffer);
    } catch (_) {
        if (token === playbackGeneration) {
            $('error').textContent = 'Trình duyệt không giải mã được âm thanh Fish Audio.';
            turnComplete = false;
            if (ws?.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({command: 'playback_failed'}));
            }
        }
    } finally {
        if (token === playbackGeneration) {
            decodingCount = Math.max(0, decodingCount - 1);
            notifyPlaybackComplete();
        }
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
            $('model').textContent = 'Brain · Groq STT · LLM · Fish';
            setState('listening', message.calibrating
                ? 'Đang đo tiếng nền — hãy giữ im lặng' : 'Brain đang nghe — không cần gọi Moon');
            dispatch('ready', {engine: message.engine});
            return;
        }
        outputMode = message.outputMode || 'native';
        incomingFormat = outputMode === 'fish' ? 'mp3' : 'pcm';
        $('model').textContent = `${message.model} · ${message.voice}`;
        setState('listening', 'Moon đang nghe — cứ nói tự nhiên');
        dispatch('ready');
    } else if (message.event === 'user_speaking' || message.event === 'listening') {
        if (message.event === 'user_speaking') {
            clearTimeout(geminiResponseTimer);
            clearPlayback();
            $('error').textContent = '';
            turnTranscript = '';
            responseStartedAt = 0;
            showHeard('Đang nghe…');
            showLatency('đang đo');
        }
        setState('listening', message.event === 'user_speaking' ? 'Bạn đang nói…' : 'Moon đang nghe — cứ nói tự nhiên');
        if (message.event === 'listening') resetGeminiTurnDetector();
        dispatch(message.event);
    } else if (message.event === 'thinking') {
        resetGeminiTurnDetector();
        if (!responseStartedAt) responseStartedAt = performance.now();
        armGeminiResponseTimeout();
        setState('thinking', 'Moon đang suy nghĩ…');
        dispatch('thinking');
    } else if (message.event === 'fish_synthesizing') {
        clearTimeout(geminiResponseTimer);
        setState('thinking', 'Đang tạo giọng Fish Audio…');
        dispatch('thinking');
    } else if (message.event === 'fish_retrying') {
        setState('thinking', 'Fish Audio chưa phản hồi — đang thử lại lần cuối…');
    } else if (message.event === 'browser_tts_fallback') {
        speakBrowserFallback(message.text, message.reason);
    } else if (message.event === 'speaking') {
        clearTimeout(geminiResponseTimer);
        resetGeminiTurnDetector();
        incomingFormat = message.format || (outputMode === 'fish' ? 'mp3' : 'pcm');
        if (responseStartedAt) showLatency(`${Math.round(performance.now() - responseStartedAt)} ms tới âm thanh`);
        setState('speaking', 'Moon đang trả lời — bạn có thể ngắt lời');
        dispatch('speaking');
    } else if (message.event === 'input_transcript') {
        turnTranscript += message.text || '';
        showHeard(turnTranscript);
    } else if (message.event === 'input_committed') {
        if (!responseStartedAt) responseStartedAt = performance.now();
        setState('thinking', 'Gemini đã nhận câu — đang tạo phản hồi…');
    } else if (pipeline === 'brain' && message.event === 'calibrated') {
        setState('listening', 'Brain đang nghe — nói trực tiếp, không cần gọi Moon');
    } else if (pipeline === 'brain' && message.event === 'meter') {
        if (typeof message.rms === 'number') $('level').value = message.rms;
    } else if (pipeline === 'brain' && message.event === 'processing') {
        setState('thinking', 'Đang chuyển giọng nói thành văn bản…');
    } else if (pipeline === 'brain' && message.event === 'transcript') {
        showHeard(message.text);
        showCorrected('', false);
        showLatency(`STT ${message.latency_ms || 0} ms · đang chờ Brain`);
    } else if (pipeline === 'brain' && message.event === 'question') {
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
        }, 60000);
    } else if (pipeline === 'brain' && message.event === 'rejected') {
        $('error').textContent = message.text || 'Chưa nghe rõ — hãy nói lại.';
        setState('listening', 'Brain đang nghe — hãy nói lại');
    } else if (pipeline === 'brain' && message.event === 'state') {
        if (!brainWaiting) setState('listening', 'Brain đang nghe — không cần gọi Moon');
    } else if (message.event === 'fish_fallback') {
        $('error').textContent = message.text || 'Fish Audio tạm lỗi; đang dùng giọng Gemini cho câu này.';
        setState('speaking', 'Đang chuyển sang giọng Gemini dự phòng…');
    } else if (message.event === 'interrupted') {
        clearPlayback();
        setState('listening', 'Đã ngắt câu trả lời — Moon đang nghe');
        dispatch('interrupted');
    } else if (message.event === 'turn_complete') {
        turnComplete = true;
        notifyPlaybackComplete();
    } else if (message.event === 'turn_error') {
        clearTimeout(geminiResponseTimer);
        $('error').textContent = message.text || 'Không tạo được câu trả lời bằng Fish Audio.';
        setState('error', 'Lỗi tạo giọng — phiên vẫn đang nghe');
        dispatch('error', {text: message.text});
    } else if (message.event === 'expression') {
        dispatch('expression', {expression: message.expression});
    } else if (message.event === 'reconnecting') {
        setState('connecting', message.text || 'Đang làm mới phiên…');
    } else if (message.event === 'error') {
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
            ? 'Đang đo tiếng nền — hãy giữ im lặng' : 'Đang chờ bạn nói “Hey Moon”');
        $('model').textContent = `Wakeword · ${message.engine || 'Whisper'}`;
    } else if (message.event === 'calibrated' || message.event === 'resumed') {
        wakeCalibrating = false;
        setState('waiting', 'Sẵn sàng — hãy nói “Hey Moon”');
    } else if (message.event === 'recalibrating') {
        wakeCalibrating = true;
        setState('connecting', 'Tiếng nền thay đổi — hãy giữ im lặng để đo lại');
    } else if (message.event === 'meter') {
        if (typeof message.rms === 'number') $('level').value = message.rms;
    } else if (message.event === 'processing') {
        setState('waiting', 'Đang kiểm tra từ khóa…');
    } else if (message.event === 'verifying_wake') {
        if (message.text) showHeard(`Đang xác minh: ${message.text}`);
        setState('waiting', 'Đang xác minh “Hey Moon”…');
    } else if (message.event === 'transcript') {
        showHeard(message.text || 'Đã nhận wakeword');
        showLatency(`wake STT ${message.latency_ms || 0} ms`);
    } else if (message.event === 'ignored') {
        showHeard(message.text ? `Chưa khớp wakeword: ${message.text}` : 'Chưa nghe rõ wakeword');
        showLatency(`wake STT ${message.latency_ms || 0} ms`);
        if (!promotingWake) setState('waiting', 'Chưa nhận đúng — hãy nói lại “Hey Moon”');
    } else if (message.event === 'state') {
        if (!promotingWake) setState('waiting', 'Đang chờ bạn nói “Hey Moon”');
    } else if (message.event === 'wake') {
        void promoteWakeToLive(token);
    } else if (message.event === 'error') {
        $('error').textContent = message.text || 'Không thể nhận diện wakeword.';
        setState('error', 'Wakeword gặp lỗi');
    }
}

async function connectWakeSocket(token) {
    const endpoint = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/voice/ws`;
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
    wakeCalibrating = false;
    ready = false;
    wakeTick();
    setState('connecting', 'Đã nghe “Hey Moon” — đang mở hội thoại trực tiếp…');
    showHeard('Đã nhận wakeword “Hey Moon”');
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
        promotingWake = false;
        wakeTick();
        setState('listening', pipeline === 'brain'
            ? 'Đã thức — Brain đang nghe, bạn hãy nói tự nhiên'
            : 'Đã thức — Moon đang nghe, bạn hãy nói tự nhiên');
        dispatch('listening', {activatedBy: 'wakeword'});
    } catch (error) {
        if (token !== generation) return;
        promotingWake = false;
        $('error').textContent = error.message;
        await stop(false, true);
    }
}

async function connectSocket(token) {
    pipeline = $('pipeline').value === 'brain' ? 'brain' : 'gemini';
    const mode = $('mode').value === 'native' ? 'native' : 'fish';
    const path = pipeline === 'brain' ? '/voice/ws?mode=continuous' : `/live/ws?mode=${encodeURIComponent(mode)}`;
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
    const acquired = await navigator.mediaDevices.getUserMedia({audio: {
        deviceId: selected ? {exact: selected} : undefined,
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: activation !== 'wakeword',
    }});
    if (token !== generation) { acquired.getTracks().forEach(track => track.stop()); return; }
    stream = acquired;
    stream.getAudioTracks()[0].onended = () => {
        $('error').textContent = 'Microphone đã ngắt kết nối.';
        stop();
    };

    const devices = await navigator.mediaDevices.enumerateDevices();
    $('device').replaceChildren(new Option('Microphone mặc định', ''));
    devices.filter(device => device.kind === 'audioinput').forEach(device =>
        $('device').add(new Option(device.label || 'Microphone', device.deviceId)));
    $('device').value = selected;

    context = new AudioContext();
    playHead = 0;
    await context.resume();
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
        if (!ready || !ws || ws.readyState !== WebSocket.OPEN) return;
        if (ws.bufferedAmount > 65536) return;
        ws.send(event.data);
        detectGeminiTurnEnd(rms);
    };
    source.connect(highpass);
    highpass.connect(capture);
    capture.connect(context.destination); // Worklet chỉ phát silence.
}

async function start() {
    if (starting || active) return;
    starting = true;
    const token = ++generation;
    $('error').textContent = '';
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
    wakeCalibrating = false;
    localNoise = .0015;
    resetGeminiTurnDetector();
    clearPlayback();
    turnTranscript = '';
    brainWaiting = false;
    showHeard('Đang chuẩn bị…');
    showCorrected('', false);
    showLatency('đang đo');
    dispatch('starting');
    window.dispatchEvent(new Event('moon-live-request-mic'));
    try {
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
            setState(wakeCalibrating ? 'connecting' : 'waiting', wakeCalibrating
                ? 'Đang đo tiếng nền — hãy giữ im lặng'
                : 'Sẵn sàng — hãy nói “Hey Moon”');
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
    wakeCalibrating = false;
    resetGeminiTurnDetector();
    clearInterval(clockTimer);
    clearTimeout(brainTimer);
    clearTimeout(brainResumeTimer);
    clearTimeout(geminiResponseTimer);
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
    setState(preserveError ? 'error' : 'idle', preserveError ? 'Phiên Live Talk đã dừng' : 'Sẵn sàng kết nối');
    dispatch(preserveError ? 'error' : 'stopped', preserveError ? {text: $('error').textContent} : {});
    if (userRequested) $('state').textContent = 'Đã kết thúc Live Talk';
    phase = 'idle';
    updatePipelineUi();
}

function updatePipelineUi() {
    pipeline = $('pipeline').value === 'brain' ? 'brain' : 'gemini';
    activation = $('activation').value === 'wakeword' ? 'wakeword' : 'manual';
    const brain = pipeline === 'brain';
    if (brain) $('mode').value = 'fish';
    $('mode').disabled = brain || active || starting;
    const activationText = activation === 'wakeword'
        ? ' Moon chỉ mở hội thoại sau khi nghe “Hey Moon”.'
        : ' Hội thoại bắt đầu ngay khi bạn bấm nút.';
    $('description').textContent = (brain
        ? 'Groq STT chuyển câu nói cho Brain và LLM hiện tại; Fish Audio trả lời liên tục.'
        : 'Gemini nghe và hiểu âm thanh trực tiếp; có thể trả lời bằng Fish Voice hoặc Gemini Native.')
        + activationText + ' OLED chỉ hiển thị biểu cảm phù hợp.';
    $('model').textContent = brain
        ? 'Brain · Groq STT · LLM · Fish'
        : `gemini-3.8-live · ${$('mode').value === 'fish' ? 'Fish Voice' : 'Kore'}`;
    $('start').innerHTML = activation === 'wakeword'
        ? '<i data-lucide="ear"></i> Bắt đầu chờ “Hey Moon”'
        : '<i data-lucide="radio"></i> Bắt đầu Live Talk';
    if (window.lucide) lucide.createIcons();
    if (!active && !starting) $('state').textContent = activation === 'wakeword'
        ? 'Sẵn sàng chờ wakeword “Hey Moon”'
        : (brain ? 'Sẵn sàng kết nối Brain Live' : 'Sẵn sàng kết nối Gemini Live');
    showHeard('Chưa có dữ liệu');
    showCorrected('', false);
    showLatency('—');
}

$('start').onclick = start;
$('stop').onclick = () => stop(true);
$('pipeline').onchange = updatePipelineUi;
$('activation').onchange = updatePipelineUi;
$('mode').onchange = () => {
    const fish = $('mode').value === 'fish';
    $('model').textContent = fish ? 'gemini-3.8-live · Fish Voice' : 'gemini-3.8-live · Kore';
    $('state').textContent = fish
        ? 'Fish Voice chậm hơn một chút nhưng giữ đúng giọng Moon'
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
    } else if (detail.event === 'state' && detail.state === 'speaking') {
        if (responseStartedAt) showLatency(`${Math.round(performance.now() - responseStartedAt)} ms tới âm thanh`);
        setState('speaking', 'Moon đang trả lời bằng Brain + Fish…');
    } else if (detail.event === 'state' && detail.state === 'standby' && brainWaiting) {
        clearTimeout(brainTimer);
        clearTimeout(brainResumeTimer);
        const token = generation;
        brainResumeTimer = setTimeout(() => {
            if (token !== generation || !active || pipeline !== 'brain') return;
            brainWaiting = false;
            if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({command: 'resume'}));
            setState('listening', 'Brain đang nghe — nói câu tiếp theo');
        }, 1200);
    }
});
updatePipelineUi();
window.addEventListener('pagehide', () => stop(false));
})();
