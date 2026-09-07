// ─── Socket.IO setup ──────────────────────────────────────────────────────────
const socket = io();

const visionPanel = new VisionPanel(document);
let lastCameraFrame = 0;
setInterval(() => {
    visionPanel.tick();
    if (lastCameraFrame && Date.now() - lastCameraFrame > 3000) {
        const camera = document.getElementById('cam-image');
        const placeholder = document.getElementById('cam-placeholder');
        if (camera) camera.style.display = 'none';
        if (placeholder) placeholder.style.display = '';
    }
}, 250);

// ─── DOM refs ─────────────────────────────────────────────────────────────────
const terminalLog     = document.getElementById('terminal-log');
const distVal         = document.getElementById('val-dist');
const btnVal          = document.getElementById('val-btn');
const dot             = document.getElementById('connection-dot');
const statusText      = document.getElementById('connection-status');
const voiceText       = document.getElementById('voice-text');
const voiceBox        = document.getElementById('voice-box');
const voiceWaveform   = document.getElementById('voice-waveform');
const oledFace        = document.getElementById('oled-face');
const oledTextEl      = document.getElementById('oled-text');   // text overlay
const oledIconEl      = document.getElementById('oled-icon');   // ? icon
let   oledTopicEl     = document.getElementById('oled-topic');  // emoji chủ đề
let   oledCapEl       = document.getElementById('oled-cap');    // caption chủ đề
// Chống cache HTML cũ: tự tạo phần tử nếu thiếu
if (!oledTopicEl && oledFace) {
    oledTopicEl = document.createElement('div');
    oledTopicEl.id = 'oled-topic';
    oledTopicEl.className = 'oled-topic';
    oledFace.appendChild(oledTopicEl);
}
if (!oledCapEl && oledFace) {
    oledCapEl = document.createElement('div');
    oledCapEl.id = 'oled-cap';
    oledCapEl.className = 'oled-cap';
    oledFace.appendChild(oledCapEl);
}

// AI Chat panel refs
const aiIdleHint      = document.getElementById('ai-idle-hint');
const aiUserBubble    = document.getElementById('ai-user-bubble');
const aiUserText      = document.getElementById('ai-user-text');
const aiThinkingBar   = document.getElementById('ai-thinking-bar');
const aiThinkingLabel = document.getElementById('ai-thinking-label');
const aiPandaBubble   = document.getElementById('ai-panda-bubble');
const aiPandaText     = document.getElementById('ai-panda-text');
const aiCursor        = document.getElementById('ai-cursor');
const voiceStateBadge = document.getElementById('voice-state-badge');
const voiceStateLabel = document.getElementById('voice-state-label');
const micBtn          = document.getElementById('mic-btn');
const micLiveBtn      = document.getElementById('mic-live-btn');

// ─── OLED Face ────────────────────────────────────────────────────────────────
const ALL_EMOTIONS = ['neutral','happy','sad','surprised','angry','love','wink','sleepy','dizzy','cool','cute'];
const ALL_AI_MODES = ['questioning','hearing','ai-thinking','speaking'];
const IDLE_BEHAVIORS = ['idle-look-left','idle-look-right','idle-look-up',
                        'idle-curious','idle-happy','idle-squint','idle-sleepy',
                        'idle-wink','idle-cross','idle-wide','idle-shy','idle-scan',
                        'idle-bounce','idle-roll','idle-grumpy','idle-teary',
                        'idle-heart','idle-dizzy1',
                        // đủ bộ 11 emotion — biểu cảm xuất hiện nhỉnh hơn light-move
                        'idle-surprised','idle-cool','idle-cute','idle-sad',
                        'idle-angry','idle-love','idle-happy','idle-heart'];

// Icon chủ đề (lucide line-art) — cùng ngôn ngữ neon-OLED với ring/dots/bars
const TOPIC_ICON = {
    time: 'clock', weather: 'cloud-rain', math: 'calculator', emotion: 'heart',
    food: 'utensils', music: 'music', place: 'map-pin', nature: 'mountain',
    identity: 'bot', chat: 'message-circle', story: 'book-open',
    sport: 'trophy', animal: 'paw-print', study: 'graduation-cap',
    tech: 'cpu', people: 'users', game: 'gamepad-2',
    science: 'flask-conical', history: 'landmark', geography: 'globe-2',
    space: 'rocket', health: 'heart-pulse', money: 'coins', movie: 'clapperboard',
};

// Màu glow riêng từng chủ đề — set inline lên icon + caption
const TOPIC_COLOR = {
    time:'#74b9ff', weather:'#81ecec', math:'#a29bfe', story:'#ffeaa7',
    emotion:'#ff6b81', food:'#fab1a0', music:'#ff7675', sport:'#fdcb6e',
    animal:'#fd79a8', nature:'#55efc4', place:'#00cec9', study:'#81ecec',
    tech:'#0984e3', people:'#ffeaa7', game:'#6c5ce7', science:'#00b894',
    history:'#e17055', geography:'#00cec9', space:'#a29bfe', health:'#ff6b81',
    money:'#ffeaa7', movie:'#fab1a0', identity:'#00d2ff', chat:'#00d2ff',
};

function drawFace(faceName) {
    // Khi set emotion thường → thoát khỏi AI mode
    oledFace.classList.remove(...ALL_EMOTIONS, ...ALL_AI_MODES, ...IDLE_BEHAVIORS);
    const pm = oledFace.className.match(/topic-[\w-]+/);
    if (pm) oledFace.classList.remove(pm[0]);
    oledFace.classList.add(faceName);
    if (oledTextEl) oledTextEl.classList.remove('long-text');
    if (!ALL_AI_MODES.includes(faceName)) {
        if (oledTopicEl) oledTopicEl.style.opacity = '0';
        if (oledCapEl)   oledCapEl.style.opacity   = '0';
        oledFace.classList.remove('has-topic');
    }
}
drawFace('neutral');

/**
 * setOledAiMode(mode, text)
 * mode: 'questioning' | 'hearing' | 'ai-thinking' | 'speaking' | 'neutral'
 * text: chỉ dùng cho mode 'hearing' — hiển thị transcript trên OLED
 */
function setOledAiMode(mode, text = '') {
    oledFace.classList.remove(...ALL_EMOTIONS, ...ALL_AI_MODES, ...IDLE_BEHAVIORS);
    if (mode === 'neutral') {
        oledFace.classList.add('neutral');
        if (oledTopicEl) oledTopicEl.style.opacity = '0';
        return;
    }
    oledFace.classList.add(mode);

    // Emoji + caption chủ đề: emoji hiện khi nghĩ+nói, caption khi nói
    const showTopic = (mode === 'ai-thinking' || mode === 'speaking');
    if (oledTopicEl) oledTopicEl.style.opacity = showTopic ? '1' : '0';
    if (oledCapEl)   oledCapEl.style.opacity   = (mode === 'speaking') ? '1' : '0';

    // Mode 'hearing': hiển thị text trên OLED — co chữ vừa khung, không cắt đầu/cuối
    if (mode === 'hearing' && oledTextEl) {
        oledTextEl.textContent = `"${text}"`;
        const n = text.length;
        oledTextEl.style.fontSize = n <= 18 ? '15px' : n <= 30 ? '12px' : n <= 45 ? '10px' : '9px';
        oledTextEl.classList.toggle('long-text', n > 45);   // chỉ cuộn khi quá dài
    }

    // Mode 'questioning': icon là '?'
    if (mode === 'questioning' && oledIconEl) {
        oledIconEl.textContent = '?';
    }
}


// ─── Connection ───────────────────────────────────────────────────────────────
socket.on('connect', () => {
    dot.className = 'dot online';
    statusText.textContent = 'Online';
    logToTerminal('Connected to Server', 'sys');
});

socket.on('disconnect', () => {
    dot.className = 'dot offline';
    statusText.textContent = 'Offline';
    logToTerminal('Disconnected from Server', 'sys');
});

// ─── Send command ─────────────────────────────────────────────────────────────
function sendCommand(topic, payload) {
    socket.emit('send_cmd', { topic, payload });
    logToTerminal(`TX: ${topic} → ${payload}`, 'cmd');
}

// ─── Clear AI chat history ────────────────────────────────────────────────────
function clearAiHistory() {
    socket.emit('send_cmd', { topic: 'panda/ai/clear_history', payload: '1' });
    resetAiPanel();
    logToTerminal('AI history cleared', 'sys');
}

// ─── Browser Push-to-Talk (MediaStream → Socket.IO → MQTT → Groq) ────────────
// Dùng CHÍNH mic của trình duyệt (cùng thiết bị Google Translate dùng),
// ghi âm webm/opus rồi gửi về backend — bypass mic server bị lỗi.
let mediaRecorder = null;
let micChunks = [];

function arrayBufferToBase64(buf) {
    const bytes = new Uint8Array(buf);
    let bin = '';
    const CHUNK = 0x8000;
    for (let i = 0; i < bytes.length; i += CHUNK) {
        bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
    }
    return btoa(bin);
}

function setMicUI(recording) {
    if (!micBtn) return;
    micBtn.classList.toggle('recording', recording);
    micBtn.textContent = recording ? '⏹ Dừng & gửi' : '🎤 Nói qua trình duyệt';
}

async function toggleBrowserMic() {
    // Đang thu → dừng và gửi
    if (mediaRecorder && mediaRecorder.state === 'recording') {
        mediaRecorder.stop();
        return;
    }
    if (!navigator.mediaDevices || !window.MediaRecorder) {
        logToTerminal('🎤 Trình duyệt không hỗ trợ MediaRecorder', 'sys');
        return;
    }
    try {
        // Bật DSP kiểu Google Dịch: triệt tiếng loa + khử ồn + tự động gain
        const stream = await navigator.mediaDevices.getUserMedia({
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
            },
        });
        const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
            ? 'audio/webm;codecs=opus' : 'audio/webm';
        mediaRecorder = new MediaRecorder(stream, { mimeType: mime });
        micChunks = [];

        mediaRecorder.ondataavailable = (e) => {
            if (e.data && e.data.size > 0) micChunks.push(e.data);
        };

        mediaRecorder.onstop = async () => {
            stream.getTracks().forEach(t => t.stop());   // tắt đèn mic
            const blob = new Blob(micChunks, { type: 'audio/webm' });
            if (blob.size < 1024) {
                logToTerminal('🎤 Audio quá ngắn — bỏ qua', 'sys');
            } else {
                const b64 = arrayBufferToBase64(await blob.arrayBuffer());
                socket.emit('voice_audio', b64);
                logToTerminal(`🎤 Đã gửi audio browser (${(blob.size / 1024).toFixed(1)} KB)`, 'log-voice');
            }
            setMicUI(false);
        };

        mediaRecorder.start();
        setMicUI(true);
        logToTerminal('🎤 Browser mic đang thu... nhấn nút lần nữa để gửi', 'sys');
    } catch (e) {
        logToTerminal(`🎤 Lỗi mic browser: ${e.name} — ${e.message}`, 'sys');
        setMicUI(false);
    }
}

// ─── LIVE MIC: nghe liên tục hands-free với DSP kiểu Google Dịch ─────────────
// AudioContext 16kHz + chuỗi DSP trình duyệt (AEC+NS+AGC) → VAD năng lượng nhẹ
// trong JS → gửi clip PCM sạch về server → Whisper 3-pass. Mượt như Google Dịch.
let live = { on:false, ctx:null, proc:null, stream:null,
             ambient:0, seen:0, speech:false, speechBlocks:0,
             preroll:[], buf:[], lastSpeech:0, pending:[] };

function setLiveUI(on) {
    if (!micLiveBtn) return;
    micLiveBtn.classList.toggle('recording', on);
    micLiveBtn.textContent = on ? '🎙️ Đang nghe liên tục — nhấn để tắt'
                                : '🎙️ Nghe liên tục qua trình duyệt';
}

function resetLiveVad() {
    Object.assign(live, { ambient:0, seen:0, speech:false, speechBlocks:0,
                          preroll:[], buf:[], lastSpeech:0, pending:[] });
}

async function toggleLiveMic() {
    if (live.on) { stopLiveMic(); return; }
    try {
        live.stream = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation:true, noiseSuppression:true, autoGainControl:true },
        });
        const AC = window.AudioContext || window.webkitAudioContext;
        live.ctx = new AC({ sampleRate: 16000 });
        if (live.ctx.sampleRate !== 16000) {
            live.ctx.close(); live.stream.getTracks().forEach(t => t.stop());
            logToTerminal('🎙️ Trình duyệt không hỗ trợ AudioContext 16kHz', 'sys');
            return;
        }
        const src = live.ctx.createMediaStreamSource(live.stream);
        live.proc = live.ctx.createScriptProcessor(4096, 1, 1);
        live.proc.onaudioprocess = (e) => {
            if (live.on) liveFeed(e.inputBuffer.getChannelData(0));
        };
        src.connect(live.proc);
        live.proc.connect(live.ctx.destination);
        live.on = true;
        resetLiveVad();
        socket.emit('mic_live', '1');
        setLiveUI(true);
        logToTerminal('🎙️ LIVE MIC BẬT — Panda nghe liên tục qua DSP trình duyệt', 'sys');
    } catch (e) {
        logToTerminal(`🎙️ Lỗi live mic: ${e.name} — ${e.message}`, 'sys');
    }
}

function stopLiveMic() {
    live.on = false;
    try {
        if (live.proc) live.proc.disconnect();
        if (live.ctx)  live.ctx.close();
        if (live.stream) live.stream.getTracks().forEach(t => t.stop());
    } catch (e) {}
    socket.emit('mic_live', '0');
    setLiveUI(false);
    logToTerminal('🎙️ Live mic TẮT — trả tai về mic robot', 'sys');
}

function liveFeed(f32) {
    for (let i = 0; i < f32.length; i++) live.pending.push(f32[i]);
    while (live.pending.length >= 480) {          // block 30ms @16k
        liveBlock(live.pending.splice(0, 480));
    }
}

function liveBlock(blk) {
    let sum = 0;
    for (let i = 0; i < blk.length; i++) sum += blk[i] * blk[i];
    const rms = Math.sqrt(sum / blk.length);

    // 0.6s hiệu chuẩn ồn nền (giống server)
    if (live.seen < 20) {
        live.seen++;
        live.ambient = (live.seen === 1) ? rms : live.ambient * 0.7 + rms * 0.3;
        live.preroll.push(blk); if (live.preroll.length > 50) live.preroll.shift();
        return;
    }
    const thr = Math.max(0.02, live.ambient * 2.5);
    const isSpeech = rms >= thr;

    if (isSpeech) {
        if (!live.speech) { live.speech = true; live.buf = live.preroll.slice(); live.preroll = []; }
        live.speechBlocks++;
        live.lastSpeech = Date.now();
        live.buf.push(blk);
    } else {
        live.ambient = live.ambient * 0.9 + rms * 0.1;
        if (live.speech) {
            live.buf.push(blk);
            if (Date.now() - live.lastSpeech >= 1200) emitLiveClip();   // endpointer 1.2s
        } else {
            live.preroll.push(blk); if (live.preroll.length > 50) live.preroll.shift();
        }
    }
    if (live.speech && live.buf.length > 333) emitLiveClip();           // clip ≤ 10s
}

function emitLiveClip() {
    if (live.speechBlocks >= 8) {                                       // ≥ 0.24s giọng
        const all = [].concat(...live.buf);
        const i16 = new Int16Array(all.length);
        for (let i = 0; i < all.length; i++) {
            const v = Math.max(-1, Math.min(1, all[i]));
            i16[i] = v < 0 ? v * 0x8000 : v * 0x7FFF;
        }
        socket.emit('voice_clip', arrayBufferToBase64(i16.buffer));
    }
    live.speech = false; live.speechBlocks = 0; live.buf = []; live.preroll = [];
}

// ─── Voice AI State helpers ───────────────────────────────────────────────────
const VOICE_STATE_CONFIG = {
    standby:   { label: 'Standby',    emoji: '🎙️', cls: 'state-standby'   },
    listening: { label: 'Listening',  emoji: '👂', cls: 'state-listening'  },
    thinking:  { label: 'Thinking',   emoji: '🧠', cls: 'state-thinking'   },
    speaking:  { label: 'Speaking',   emoji: '🔊', cls: 'state-speaking'   },
};

function setVoiceState(state) {
    const cfg = VOICE_STATE_CONFIG[state] || VOICE_STATE_CONFIG['standby'];
    voiceStateBadge.dataset.state = state;
    voiceStateLabel.textContent = cfg.label;
    voiceStateBadge.querySelector('.voice-state-icon').textContent = cfg.emoji;

    // Waveform animation (voice-box cũ đã gỡ khỏi HTML → guard null)
    if (voiceWaveform) voiceWaveform.classList.toggle('active', state === 'listening');
    if (voiceBox)      voiceBox.classList.toggle('listening', state === 'listening');
}

// ─── AI Chat Panel helpers ────────────────────────────────────────────────────
function resetAiPanel() {
    aiIdleHint.style.display = 'flex';
    aiUserBubble.style.display = 'none';
    aiThinkingBar.style.display = 'none';
    aiPandaBubble.style.display = 'none';
    aiUserText.textContent = '';
    aiPandaText.textContent = '';
    aiCursor.style.display = 'inline';
}

function showUserQuestion(text) {
    aiIdleHint.style.display = 'none';
    aiUserBubble.style.display = 'block';
    aiUserText.textContent = text;
    aiPandaBubble.style.display = 'none';
    aiPandaText.textContent = '';
    aiCursor.style.display = 'inline';
}

function showThinking(label) {
    aiThinkingBar.style.display = 'flex';
    aiThinkingLabel.textContent = label;
}

function hideThinking() {
    aiThinkingBar.style.display = 'none';
}

function appendPandaChunk(chunk) {
    aiPandaBubble.style.display = 'block';
    aiPandaText.textContent += chunk;
    // Auto scroll
    aiPandaBubble.scrollTop = aiPandaBubble.scrollHeight;
}

function finalizePandaResponse() {
    aiCursor.style.display = 'none';
    hideThinking();
}

// ─── MQTT message handler ─────────────────────────────────────────────────────
socket.on('mqtt_message', (data) => {
    const { topic, payload } = data;

    // ── Sensor status ─────────────────────────────────────────────────────────
    if (topic === 'panda/status') {
        try {
            const status = JSON.parse(payload);
            distVal.textContent = status.dist + ' cm';
            btnVal.textContent  = status.btn === 1 ? 'PRESSED' : 'RELEASED';
            btnVal.style.color  = status.btn === 1 ? '#ff4757' : 'var(--accent)';
        } catch(e) {}

    // ── Voice transcript (đầy đủ, sau khi Groq xử lý) ───────────────────────
    } else if (topic === 'panda/log/voice') {
        if (voiceText) {
            voiceText.textContent = `"${payload}"`;
            voiceText.classList.add('flash');
            setTimeout(() => voiceText.classList.remove('flash'), 600);
        }
        logToTerminal(`VOICE: ${payload}`, 'log-voice');

    // ── Voice partial (real-time, hiện thị ngay) ─────────────────────────────
    } else if (topic === 'panda/log/voice_partial') {
        if (voiceText) voiceText.textContent = payload;

    // ── Camera feed ───────────────────────────────────────────────────────────
    } else if (topic === 'panda/camera') {
        lastCameraFrame = Date.now();
        const camImg         = document.getElementById('cam-image');
        const camPlaceholder = document.getElementById('cam-placeholder');
        camImg.src           = "data:image/jpeg;base64," + payload;
        camImg.style.display = 'block';
        if (camPlaceholder) camPlaceholder.style.display = 'none';

    // ── Face command ──────────────────────────────────────────────────────────
    } else if (topic === 'panda/cmd/face') {
        drawFace(payload);
        logToTerminal(`RX: ${topic} → ${payload}`, 'status');

    // ── CV user status ────────────────────────────────────────────────────────
    } else if (topic === 'panda/vision/status') {
        try { visionPanel.receive(JSON.parse(payload)); } catch(e) {}

    } else if (topic === 'panda/user_status') {
        // Legacy duplicate of vision/status: do not flood Activity Log every frame.

    // ── Topic emoji + caption cho OLED (JSON: {id, cap}) ───────────────────
    } else if (topic === 'panda/ai/topic') {
        try {
            const t = JSON.parse(payload);
            if (oledTopicEl) {
                // Line-art icon neon thay cho emoji màu — chuẩn chất OLED
                oledTopicEl.innerHTML =
                    '<i data-lucide="' + (TOPIC_ICON[t.id] || 'message-circle') + '"></i>';
                if (window.lucide) lucide.createIcons();
            }
            if (oledCapEl)   oledCapEl.textContent   = t.cap || '';
            // class chủ đề → màu glow + animation riêng trong CSS
            const pm = oledFace.className.match(/topic-[\w-]+/);
            if (pm) oledFace.classList.remove(pm[0]);
            oledFace.classList.add('topic-' + (TOPIC_ICON[t.id] ? t.id : 'chat'));
            oledFace.classList.add('has-topic');
            // màu chủ đề → icon (currentColor) + caption
            const col = TOPIC_COLOR[t.id] || '#00d2ff';
            if (oledTopicEl) oledTopicEl.style.color = col;
            if (oledCapEl) {
                oledCapEl.style.color = col;
                oledCapEl.style.textShadow = '0 0 10px ' + col;
            }
        } catch(e) {}

    // ── Voice AI global state ────────────────────────────────────────────────────────────────
    } else if (topic === 'panda/ai/state') {
        setVoiceState(payload);
        // Đồng bộ OLED face theo AI state
        // (thinking: OLED GIỮ transcript đã nghe — mode 'hearing' — không đổi sang dots)
        if (payload === 'listening')   setOledAiMode('questioning');
        else if (payload === 'speaking') setOledAiMode('speaking');
        else if (payload === 'standby')  setOledAiMode('neutral');
        logToTerminal(`AI State: ${payload}`, 'ai-state');

    // ── AI thinking / stages ────────────────────────────────────────────────────────────────
    } else if (topic === 'panda/ai/thinking') {
        try {
            const msg = JSON.parse(payload);
            switch (msg.stage) {
                case 'listening':
                    resetAiPanel();
                    aiIdleHint.style.display = 'none';
                    showThinking('👂 Panda đang lắng nghe...');
                    setOledAiMode('questioning');     // OLED: ? + ring
                    break;
                case 'question':
                    showUserQuestion(msg.text);
                    setOledAiMode('hearing', msg.text); // OLED: text transcript
                    break;
                case 'thinking':
                    showThinking('🧠 Panda đang suy nghĩ...');
                    // OLED giữ transcript đã nghe ('hearing') — dots chỉ trên dashboard
                    break;
                case 'answering':
                    showThinking('✍️ Panda đang soạn câu trả lời...');
                    // OLED vẫn giữ transcript
                    break;
                case 'done':
                    hideThinking();
                    break;
                case 'idle':
                    resetAiPanel();
                    setOledAiMode('neutral');         // OLED: quay về mắt
                    break;
            }
        } catch(e) {}

    // ── AI response stream ────────────────────────────────────────────────────
    } else if (topic === 'panda/ai/response') {
        try {
            const msg = JSON.parse(payload);
            if (!msg.done) {
                // Chunk mới đến — hiển thị stream
                if (aiPandaText.textContent === '') {
                    // Lần đầu → reset và hiện bubble
                    aiPandaBubble.style.display = 'block';
                    aiCursor.style.display = 'inline';
                }
                // Overwrite với full text (backend gửi accumulated text)
                aiPandaText.textContent = msg.text;
            } else {
                // Done — show full text, ẩn cursor
                aiPandaText.textContent = msg.text;
                finalizePandaResponse();
                logToTerminal(`AI: ${msg.text.substring(0, 60)}...`, 'ai-response');
            }
        } catch(e) {}

    } else {
        logToTerminal(`RX: ${topic} → ${payload}`, 'status');
    }
});

// ─── Terminal Log ─────────────────────────────────────────────────────────────
function logToTerminal(text, type) {
    const p = document.createElement('p');
    const time = new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    p.innerHTML = `<span class="log-time">${time}</span> ${text}`;

    if (type === 'cmd')         p.className = 'log-cmd';
    else if (type === 'status') p.className = 'log-status';
    else if (type === 'log-voice') p.className = 'log-voice';
    else if (type === 'ai-state')  p.className = 'log-ai-state';
    else if (type === 'ai-response') p.className = 'log-ai-response';
    else if (type === 'sys')    p.className = 'log-sys';

    terminalLog.appendChild(p);
    terminalLog.scrollTop = terminalLog.scrollHeight;

    // Keep max 80 lines
    while (terminalLog.children.length > 80) {
        terminalLog.removeChild(terminalLog.firstChild);
    }
}

// ─── Autonomous idle: Panda "tự chủ" khi rảnh — nhìn quanh, tò mò, nháy mắt... ──
// Mỗi 5–14s, nếu đang neutral, Panda tự diễn một micro-behavior rồi về lại mắt thường.
(function scheduleIdleBehavior() {
    setTimeout(() => {
        if (oledFace.classList.contains('neutral')) {
            const b = IDLE_BEHAVIORS[Math.floor(Math.random() * IDLE_BEHAVIORS.length)];
            oledFace.classList.add(b);
            setTimeout(() => oledFace.classList.remove(b), 900 + Math.random() * 900);
        }
        scheduleIdleBehavior();
    }, 5000 + Math.random() * 9000);
})();
