(() => {
const $ = id => document.getElementById(id === 'question' ? 'ai-user-text' : `voice-${id}`);
let stream, context, capture, source, highpass, ws, starting = false, generation = 0, wakes = 0;
let reconnectTimer, reconnectAttempts = 0;
let pausedReason = '';
function wakeTick() {
    if (!context || context.state !== 'running') return;
    const tone = context.createOscillator(), volume = context.createGain();
    const now = context.currentTime;
    tone.frequency.setValueAtTime(1100, now);
    volume.gain.setValueAtTime(0, now);
    volume.gain.linearRampToValueAtTime(.06, now + .008);
    volume.gain.exponentialRampToValueAtTime(.0001, now + .07);
    tone.connect(volume); volume.connect(context.destination);
    tone.onended = () => { tone.disconnect(); volume.disconnect(); };
    tone.start(now); tone.stop(now + .08);
}
function addLog(text) {
    const li = document.createElement('li');
    li.textContent = `${new Date().toLocaleTimeString()} · ${text}`;
    $('log').prepend(li);
    while ($('log').children.length > 60) $('log').lastChild.remove();
}
async function stop(forgetAutoStart = false) {
    if (forgetAutoStart) localStorage.setItem('moonVoiceAutoStart','0');
    clearTimeout(reconnectTimer);
    generation++;
    starting = false;
    if (capture) { capture.port.onmessage = null; capture.disconnect(); capture = null; }
    if (source) { source.disconnect(); source = null; }
    if (highpass) { highpass.disconnect(); highpass = null; }
    stream?.getTracks().forEach(t => t.stop()); stream = null;
    const oldSocket = ws; ws = null;
    if (oldSocket) { oldSocket.onclose = null; oldSocket.close(); }
    const oldContext = context; context = null;
    if (oldContext) await oldContext.close();
    $('start').disabled = false; $('stop').disabled = true; $('device').disabled = false;
    window.dispatchEvent(new CustomEvent('moon-voice', {detail: {event: 'stopped'}}));
    $('state').textContent = 'Đã dừng'; $('level').value = 0; $('speech').textContent = '';
}
function event(msg) {
    window.dispatchEvent(new CustomEvent('moon-voice', {detail: msg}));
    if (msg.event === 'ready') {
        $('engine').textContent = msg.engine;
        $('state').textContent = pausedReason === 'tts' ? 'Moon đang nói — mic tạm nghỉ chống tự nghe'
            : (msg.calibrating ? 'Đo tiếng nền 1.8 giây — hãy giữ im lặng' : 'Đang chờ Moon');
    }
    if (msg.event === 'calibrated') {
        $('state').textContent = 'Đang chờ Moon';
        $('noise').textContent = `Nền ${msg.noise} · ngưỡng giọng ${msg.threshold}. Nếu đổi vị trí/quạt, dừng và bật mic để đo lại.`;
    }
    if (msg.event === 'recalibrating') $('state').textContent = 'Nhiễu thay đổi — đang tự đo nền lại 1.2 giây';
    if (msg.event === 'meter') { $('level').value = msg.rms; $('speech').textContent = msg.speech ? 'Có giọng nói' : 'Nền / im lặng'; }
    if (msg.event === 'wake') {
        wakeTick();
        $('state').textContent = 'Đã nghe Moon — đợi tín hiệu rồi hãy nói';
        $('wake').textContent = `Đã bắt wakeword: ${++wakes} lần (${msg.engine})`;
        addLog(`WAKE · ${msg.engine}`);
    }
    if (msg.event === 'armed') $('state').textContent = 'Moon đang nghe — hãy nói câu hỏi';
    if (msg.event === 'processing') $('state').textContent = msg.phase === 'question'
        ? 'Đang nhận diện câu hỏi — mic vẫn thu' : 'Đang kiểm tra từ khóa Moon — mic vẫn thu';
    if (msg.event === 'verifying_wake') {
        $('state').textContent = 'Đang xác minh tên Moon…';
        $('diagnostic').textContent = msg.text
            ? `Whisper tiếng Việt nghe thành “${msg.text}”; đang xác minh lại bằng pass tiếng Anh.`
            : 'Whisper tiếng Việt chưa nhận ra từ; đang xác minh lại tên Moon.';
    }
    if (msg.event === 'transcript') addLog(`${msg.text || '(không có text tin cậy)'} · STT ${msg.latency_ms} ms · audio ${msg.duration_ms} ms`);
    if (msg.event === 'ignored') {
        $('diagnostic').textContent = `Bỏ qua khi chờ Moon (có thể là nhiễu): ${msg.text || '(không đủ tin cậy)'} · ${msg.latency_ms} ms`;
    }
    if (msg.event === 'question') $('question').textContent = msg.text;
    if (msg.event === 'state') $('state').textContent = msg.state === 'listening' ? 'Đã nghe Moon — hãy nói tiếp' : 'Đang chờ Moon';
    if (msg.event === 'timeout') { $('state').textContent = msg.text; addLog(msg.text); }
    if (msg.event === 'error') { $('error').textContent = msg.text; addLog(msg.text); }
    if (msg.event === 'rejected') addLog(msg.text);
}
async function start(auto = false) {
    if (starting || stream) return true;
    starting = true;
    window.dispatchEvent(new CustomEvent('moon-voice', {detail: {event: 'starting'}}));
    const token = ++generation;
    $('start').disabled = true; $('stop').disabled = false; $('device').disabled = true;
    $('error').textContent = ''; $('state').textContent = 'Đang mở mic…';
    try {
        if (!navigator.mediaDevices || !window.AudioWorkletNode) throw new Error('Cần Chrome/Edge trên localhost hoặc HTTPS.');
        const selected = $('device').value;
        const acquired = await navigator.mediaDevices.getUserMedia({audio: {
            deviceId: selected ? {exact: selected} : undefined,
            channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: false
        }});
        if (token !== generation) { acquired.getTracks().forEach(t => t.stop()); return; }
        stream = acquired;
        stream.getAudioTracks()[0].onended = () => { $('error').textContent = 'Microphone đã ngắt kết nối.'; stop(); };
        const devices = await navigator.mediaDevices.enumerateDevices();
        if (token !== generation) return;
        $('device').replaceChildren(new Option('Microphone mặc định', ''));
        devices.filter(d => d.kind === 'audioinput').forEach(d => $('device').add(new Option(d.label || 'Microphone', d.deviceId)));
        $('device').value = selected;
        context ||= new AudioContext();
        await context.resume();
        if (token !== generation) return;
        await context.audioWorklet.addModule('/voice-worklet.js');
        if (token !== generation) return;
        ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${document.getElementById('dashboard-voice').dataset.endpoint}`);
        const socket = ws;
        // Wait for server readiness (including keys/model) before sending any audio.
        await new Promise((resolve, reject) => {
            const timeout = setTimeout(() => reject(new Error('Voice server không phản hồi.')), 20000);
            socket.onerror = () => { clearTimeout(timeout); reject(new Error('Không kết nối được Voice server.')); };
            socket.onclose = () => { clearTimeout(timeout); reject(new Error('Voice server đã đóng kết nối.')); };
            socket.onmessage = e => {
                if (token !== generation) return;
                const msg = JSON.parse(e.data); event(msg);
                if (msg.event === 'ready') { clearTimeout(timeout); reconnectAttempts = 0; resolve(); }
                if (msg.event === 'error') { clearTimeout(timeout); reject(new Error(msg.text)); }
            };
        });
        if (token !== generation) return;
        socket.onmessage = e => { if (token === generation) event(JSON.parse(e.data)); };
        socket.onclose = async () => {
            $('error').textContent ||= 'Mất kết nối Voice server — đang tự nối lại.';
            await stop();
            scheduleReconnect();
        };
        source = context.createMediaStreamSource(stream);
        capture = new AudioWorkletNode(context, 'moon-capture');
        capture.port.onmessage = e => {
            if (socket.readyState !== WebSocket.OPEN) return;
            if (socket.bufferedAmount > 32000) {
                $('error').textContent = 'Mạng chậm, đã dừng để không tích âm thanh cũ. Bật mic để thử lại.';
                stop(); return;
            }
            socket.send(e.data);
        };
        highpass = context.createBiquadFilter();
        highpass.type = 'highpass'; highpass.frequency.value = 150; highpass.Q.value = .707;
        source.connect(highpass); highpass.connect(capture);
        capture.connect(context.destination); // Worklet outputs silence.
        starting = false;
        localStorage.setItem('moonVoiceAutoStart','1');
        return true;
    } catch (err) {
        if (token === generation) {
            $('error').textContent = auto ? `${err.message} Hãy bấm Bật microphone để thử lại.` : err.message;
            await stop();
        }
        return false;
    }
}
function scheduleReconnect() {
    if (localStorage.getItem('moonVoiceAutoStart') === '0') return;
    const delay = Math.min(1000 * 2 ** reconnectAttempts++, 10000);
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(async () => {
        $('state').textContent = 'Đang nối lại Voice…';
        if (!await start(true)) scheduleReconnect();
    }, delay);
}
$('start').onclick = () => start(false);
$('stop').onclick = () => stop(true);
$('clear').onclick = () => { $('log').replaceChildren(); };
$('test-sound').onclick = async () => {
    // User gesture unlocks audio without requiring microphone permission.
    if (!context) context = new AudioContext();
    await context.resume();
    wakeTick();
};
window.addEventListener('moon-voice-control',({detail}) => {
    if (ws?.readyState === WebSocket.OPEN && ['pause','resume'].includes(detail?.command)) {
        pausedReason = detail.command === 'pause' ? (detail.reason || 'brain') : '';
        ws.send(JSON.stringify({command:detail.command}));
        if (detail.command === 'pause') $('state').textContent = detail.reason === 'tts'
            ? 'Moon đang nói — mic tạm nghỉ chống tự nghe' : 'Brain đang xử lý — mic tạm nghỉ';
        else $('state').textContent = 'Đang chờ Moon';
    }
});
window.addEventListener('pagehide', () => stop());

// Browsers require one manual permission grant. On later dashboard loads,
// resume automatically unless the user explicitly pressed Dừng mic.
setTimeout(async () => {
    if (localStorage.getItem('moonVoiceAutoStart') === '0' || !navigator.permissions) return;
    try {
        const permission = await navigator.permissions.query({name:'microphone'});
        if (permission.state === 'granted') start(true);
    } catch (_) { /* Firefox/older browsers may not expose microphone permission. */ }
},500);

})();
