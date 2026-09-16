(() => {
const $ = id => document.getElementById(`live-${id}`);
let stream, context, source, highpass, capture, ws;
let starting = false, active = false, ready = false, generation = 0;
let releaseMicLock, micLockHeld = false, startedAt = 0, clockTimer;
let playHead = 0, turnComplete = false;
const playing = new Set();

function dispatch(event, extra = {}) {
    window.dispatchEvent(new CustomEvent('moon-live', {detail: {event, ...extra}}));
}

function setState(state, text) {
    $('orb').dataset.state = state;
    $('badge').dataset.state = state;
    $('badge').textContent = ({
        idle: 'Chưa chạy', connecting: 'Đang kết nối', listening: 'Đang nghe',
        thinking: 'Đang nghĩ', speaking: 'Moon đang nói', error: 'Có lỗi',
    })[state] || state;
    $('state').textContent = text;
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
    for (const node of playing) {
        node.onended = null;
        try { node.stop(); } catch (_) {}
        try { node.disconnect(); } catch (_) {}
    }
    playing.clear();
    playHead = context?.currentTime || 0;
    turnComplete = false;
}

function notifyPlaybackComplete() {
    if (!turnComplete || playing.size > 0 || !ws || ws.readyState !== WebSocket.OPEN) return;
    turnComplete = false;
    ws.send(JSON.stringify({command: 'playback_complete'}));
}

function playPcm24k(arrayBuffer) {
    if (!context || arrayBuffer.byteLength < 2) return;
    const view = new DataView(arrayBuffer);
    const samples = Math.floor(arrayBuffer.byteLength / 2);
    const buffer = context.createBuffer(1, samples, 24000);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < samples; i++) channel[i] = view.getInt16(i * 2, true) / 32768;

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

function handleServer(message) {
    if (message.event === 'connecting' || message.event === 'connected') {
        setState('connecting', 'Đang mở phiên Gemini Live…');
    } else if (message.event === 'ready') {
        ready = true;
        $('model').textContent = `${message.model} · ${message.voice}`;
        setState('listening', 'Moon đang nghe — cứ nói tự nhiên');
        dispatch('ready');
    } else if (message.event === 'user_speaking' || message.event === 'listening') {
        if (message.event === 'user_speaking') clearPlayback();
        setState('listening', message.event === 'user_speaking' ? 'Bạn đang nói…' : 'Moon đang nghe — cứ nói tự nhiên');
        dispatch(message.event);
    } else if (message.event === 'thinking') {
        setState('thinking', 'Moon đang suy nghĩ…');
        dispatch('thinking');
    } else if (message.event === 'speaking') {
        setState('speaking', 'Moon đang trả lời — bạn có thể ngắt lời');
        dispatch('speaking');
    } else if (message.event === 'interrupted') {
        clearPlayback();
        setState('listening', 'Đã ngắt câu trả lời — Moon đang nghe');
        dispatch('interrupted');
    } else if (message.event === 'turn_complete') {
        turnComplete = true;
        notifyPlaybackComplete();
    } else if (message.event === 'expression') {
        dispatch('expression', {expression: message.expression});
    } else if (message.event === 'reconnecting') {
        setState('connecting', message.text || 'Đang làm mới phiên…');
    } else if (message.event === 'error') {
        $('error').textContent = message.text;
        setState('error', 'Không thể bắt đầu Live Talk');
        dispatch('error', {text: message.text});
    }
}

async function connectSocket(token) {
    const endpoint = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/live/ws`;
    const socket = new WebSocket(endpoint);
    socket.binaryType = 'arraybuffer';
    ws = socket;
    await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error('Gemini Live không phản hồi sau 25 giây.')), 25000);
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
        else playPcm24k(event.data);
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
        autoGainControl: true,
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
        $('level').value = Math.sqrt(energy / Math.max(1, pcm.length));
        if (!ready || !ws || ws.readyState !== WebSocket.OPEN) return;
        if (ws.bufferedAmount > 65536) return;
        ws.send(event.data);
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
    $('device').disabled = true;
    setState('connecting', 'Đang chuẩn bị Live Talk…');
    dispatch('starting');
    window.dispatchEvent(new Event('moon-live-request-mic'));
    try {
        if (!await acquireMicLock()) throw new Error('Microphone đang được dùng ở tab Moon khác.');
        await connectSocket(token);
        active = true;
        await openMicrophone(token);
        if (token !== generation) return;
        starting = false;
        startedAt = Date.now();
        clockTimer = setInterval(() => {
            const seconds = Math.floor((Date.now() - startedAt) / 1000);
            $('duration').textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
        }, 1000);
        setState('listening', 'Moon đang nghe — cứ nói tự nhiên');
        dispatch('listening');
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
    clearInterval(clockTimer);
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
        if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({command: 'audio_stream_end'}));
        socket.close();
    }
    const oldContext = context;
    context = null;
    if (oldContext && oldContext.state !== 'closed') await oldContext.close();
    unlockMicrophone();
    $('start').disabled = false;
    $('stop').disabled = true;
    $('device').disabled = false;
    $('level').value = 0;
    $('duration').textContent = '00:00';
    if (!preserveError) $('error').textContent = '';
    setState(preserveError ? 'error' : 'idle', preserveError ? 'Phiên Live Talk đã dừng' : 'Sẵn sàng kết nối');
    dispatch(preserveError ? 'error' : 'stopped', preserveError ? {text: $('error').textContent} : {});
    if (userRequested) $('state').textContent = 'Đã kết thúc Live Talk';
}

$('start').onclick = start;
$('stop').onclick = () => stop(true);
window.addEventListener('pagehide', () => stop(false));
})();
