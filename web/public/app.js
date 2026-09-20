// ─── Socket.IO setup ──────────────────────────────────────────────────────────
const socket = io();
let liveTalkActive = false;
let liveTalkMode = '';
let liveTalkWaitingWake = false;

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
const aiMoonBubble   = document.getElementById('ai-moon-bubble');
const aiMoonText     = document.getElementById('ai-moon-text');
const aiCursor        = document.getElementById('ai-cursor');
const voiceStateBadge = document.getElementById('voice-state-badge');
const voiceStateLabel = document.getElementById('voice-state-label');

// ─── OLED Face ────────────────────────────────────────────────────────────────
const ALL_EMOTIONS = ['neutral','happy','sad','surprised','angry','love','wink','sleepy','dizzy','cool','cute'];
const ALL_AI_MODES = ['questioning','hearing','ai-thinking','answering','speaking'];
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
 * mode: 'questioning' | 'hearing' | 'ai-thinking' | 'answering' | 'speaking' | 'neutral'
 * text: dùng cho hearing/answering để hiển thị transcript/câu trả lời
 */
function setOledAiMode(mode, text = '') {
    if (mode === 'neutral') {
        drawFace('neutral');
        if (oledTextEl) { oledTextEl.textContent = ''; oledTextEl.scrollTop = 0; }
        if (oledCapEl) oledCapEl.textContent = '';
        return;
    }
    oledFace.classList.remove(...ALL_EMOTIONS, ...ALL_AI_MODES, ...IDLE_BEHAVIORS);
    oledFace.classList.add(mode);

    // Emoji + caption chủ đề: emoji hiện khi nghĩ+nói, caption khi nói
    const showTopic = (mode === 'ai-thinking' || mode === 'speaking');
    if (oledTopicEl) oledTopicEl.style.opacity = showTopic ? '1' : '0';
    if (oledCapEl)   oledCapEl.style.opacity   = (mode === 'speaking') ? '1' : '0';

    // Mode 'hearing': hiển thị text trên OLED — co chữ vừa khung, không cắt đầu/cuối
    if ((mode === 'hearing' || mode === 'answering') && oledTextEl) {
        oledTextEl.textContent = `"${text}"`;
        oledTextEl.style.fontSize = '13px';
        oledTextEl.classList.remove('long-text');
        oledTextEl.scrollTop = 0;
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
    if (!liveTalkActive) { hideThinking(); aiCursor.style.display = 'none'; setVoiceState('standby'); setOledAiMode('neutral'); }
    logToTerminal('Disconnected from Server', 'sys');
});

// ─── Send command ─────────────────────────────────────────────────────────────
function sendCommand(topic, payload) {
    socket.emit('send_cmd', { topic, payload });
    logToTerminal(`TX: ${topic} → ${payload}`, 'cmd');
}

// ─── Clear AI chat history ────────────────────────────────────────────────────
function clearAiHistory() {
    resetAiPanel();
    logToTerminal('AI history cleared', 'sys');
}

// ─── Voice AI State helpers ───────────────────────────────────────────────────
const VOICE_STATE_CONFIG = {
    standby:   { label: 'Standby',    emoji: '🎙️', cls: 'state-standby'   },
    listening: { label: 'Listening',  emoji: '👂', cls: 'state-listening'  },
    transcribing: { label: 'Đang nhận diện', emoji: '🎙️', cls: 'state-listening' },
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
    aiMoonBubble.style.display = 'none';
    aiUserText.textContent = '';
    aiMoonText.textContent = '';
    aiCursor.style.display = 'inline';
}

function showUserQuestion(text) {
    aiIdleHint.style.display = 'none';
    aiUserBubble.style.display = 'block';
    aiUserText.textContent = text;
    aiMoonBubble.style.display = 'none';
    aiMoonText.textContent = '';
    aiCursor.style.display = 'inline';
}

function showThinking(label) {
    aiThinkingBar.style.display = 'flex';
    aiThinkingLabel.textContent = label;
}

function hideThinking() {
    aiThinkingBar.style.display = 'none';
}

function appendMoonChunk(chunk) {
    aiMoonBubble.style.display = 'block';
    aiMoonText.textContent += chunk;
    // Auto scroll
    aiMoonBubble.scrollTop = aiMoonBubble.scrollHeight;
}

function finalizeMoonResponse() {
    aiCursor.style.display = 'none';
    hideThinking();
}

// ─── MQTT message handler ─────────────────────────────────────────────────────
socket.on('mqtt_message', (data) => {
    const { topic, payload } = data;
    if (liveTalkMode === 'brain' && topic === 'panda/ai/state') {
        window.dispatchEvent(new CustomEvent('moon-brain-pipeline', {
            detail: {event: 'state', state: payload},
        }));
    }
    // Live Talk có phiên audio/LLM riêng. Trạng thái AI từ Brain cũ không được
    // ghi đè giao diện trong lúc phiên Gemini Live đang hoạt động.
    if (liveTalkWaitingWake && topic.startsWith('panda/ai/')) return;
    if (liveTalkActive && liveTalkMode === 'gemini' && topic.startsWith('panda/ai/')) return;
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
        visionPanel.cameraFrame();
        const camImg         = document.getElementById('cam-image');
        const camPlaceholder = document.getElementById('cam-placeholder');
        camImg.src           = "data:image/jpeg;base64," + payload;
        camImg.style.display = 'block';
        if (camPlaceholder) camPlaceholder.style.display = 'none';

    // ── Face command ──────────────────────────────────────────────────────────
    } else if (topic === 'panda/cmd/face') {
        if (liveTalkWaitingWake || (liveTalkActive && liveTalkMode === 'gemini')) return;
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
        else if (payload === 'thinking') setOledAiMode('ai-thinking');
        else if (payload === 'speaking') {
            hideThinking();
            if (!oledFace.classList.contains('answering')) setOledAiMode('speaking');
        }
        else if (payload === 'standby') {
            hideThinking(); aiCursor.style.display = 'none';
            // Playback đã kết thúc: trả OLED về mặt mặc định ngay, đồng bộ
            // với loa thay vì giữ câu trả lời thêm nhiều giây.
            setOledAiMode('neutral');
        }
        logToTerminal(`AI State: ${payload}`, 'ai-state');

    // ── AI thinking / stages ────────────────────────────────────────────────────────────────
    } else if (topic === 'panda/ai/thinking') {
        try {
            const msg = JSON.parse(payload);
            switch (msg.stage) {
                case 'listening':
                    resetAiPanel();
                    aiIdleHint.style.display = 'none';
                    showThinking('👂 Moon đang lắng nghe...');
                    setOledAiMode('questioning');     // OLED: ? + ring
                    break;
                case 'question':
                    showUserQuestion(msg.text);
                    setOledAiMode(liveTalkActive ? 'questioning' : 'hearing', liveTalkActive ? '' : msg.text);
                    break;
                case 'correcting':
                    showThinking('🧠 Moon đang kiểm tra câu vừa nghe...');
                    break;
                case 'question_corrected':
                    showUserQuestion(msg.text);
                    setOledAiMode(liveTalkActive ? 'questioning' : 'hearing', liveTalkActive ? '' : msg.text);
                    if (liveTalkMode === 'brain') {
                        window.dispatchEvent(new CustomEvent('moon-brain-pipeline', {
                            detail: {
                                event: 'corrected',
                                text: msg.text,
                                original: msg.original || msg.text,
                                changed: Boolean(msg.changed),
                            },
                        }));
                    }
                    if (msg.changed) logToTerminal(`STT FIX: ${msg.original} → ${msg.text}`, 'log-voice');
                    break;
                case 'thinking':
                    showThinking('🧠 Moon đang suy nghĩ...');
                    setOledAiMode('ai-thinking');
                    // OLED giữ transcript đã nghe ('hearing') — dots chỉ trên dashboard
                    break;
                case 'answering':
                    showThinking('✍️ Moon đang soạn câu trả lời...');
                    setOledAiMode('ai-thinking');
                    // OLED vẫn giữ transcript
                    break;
                case 'answer':
                    hideThinking();
                    setOledAiMode(liveTalkActive ? 'speaking' : 'answering', liveTalkActive ? '' : (msg.text || ''));
                    break;
                case 'done':
                    hideThinking();
                    break;
                case 'tts_fallback':
                    showThinking('🔊 Fish Audio chậm — đang dùng giọng dự phòng...');
                    logToTerminal(msg.text || 'Fish Audio chậm — dùng giọng dự phòng', 'sys');
                    if (liveTalkMode === 'brain') {
                        window.dispatchEvent(new CustomEvent('moon-brain-pipeline', {
                            detail: {event: 'tts_fallback', text: msg.text || ''},
                        }));
                    }
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
            if (typeof msg.text !== 'string') return;
            aiIdleHint.style.display = 'none';
            aiMoonBubble.style.display = 'block';
            if (!msg.done) {
                // Chunk mới đến — hiển thị stream
                if (aiMoonText.textContent === '') {
                    // Lần đầu → reset và hiện bubble
                    aiMoonBubble.style.display = 'block';
                    aiCursor.style.display = 'inline';
                }
                // Overwrite với full text (backend gửi accumulated text)
                aiMoonText.textContent = msg.text;
            } else {
                // Done — show full text, ẩn cursor
                aiMoonText.textContent = msg.text;
                finalizeMoonResponse();
                logToTerminal(`AI: ${msg.text.substring(0, 60)}...`, 'ai-response');
                if (liveTalkMode === 'brain') {
                    window.dispatchEvent(new CustomEvent('moon-brain-pipeline', {
                        detail: {event: 'answer_ready'},
                    }));
                }
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
    const stamp = document.createElement('span');
    stamp.className = 'log-time';
    stamp.textContent = time;
    p.append(stamp, document.createTextNode(` ${text}`));

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

// ─── Autonomous idle: Moon "tự chủ" khi rảnh — nhìn quanh, tò mò, nháy mắt... ──
// Mỗi 5–14s, nếu đang neutral, Moon tự diễn một micro-behavior rồi về lại mắt thường.
(function scheduleIdleBehavior() {
    setTimeout(() => {
        if (!liveTalkActive && oledFace.classList.contains('neutral')) {
            const b = IDLE_BEHAVIORS[Math.floor(Math.random() * IDLE_BEHAVIORS.length)];
            oledFace.classList.add(b);
            setTimeout(() => oledFace.classList.remove(b), 900 + Math.random() * 900);
        }
        scheduleIdleBehavior();
    }, 5000 + Math.random() * 9000);
})();

// Live Voice chỉ điều khiển trạng thái và biểu cảm OLED; không hiển thị
// transcript/câu trả lời lên OLED như pipeline Voice cũ.
window.addEventListener('moon-live', ({detail: msg}) => {
    if (msg.event === 'starting') {
        liveTalkActive = true;
        liveTalkMode = msg.pipeline || 'gemini';
        liveTalkWaitingWake = false;
        hideThinking();
        setVoiceState('listening');
        setOledAiMode('neutral');
        if (liveTalkMode === 'brain') socket.emit('mic_live', '1');
        logToTerminal(liveTalkMode === 'brain'
            ? 'LIVE: đang chuẩn bị Brain Pipeline'
            : 'LIVE: đang chuẩn bị Gemini Native Audio', 'ai-state');
    } else if (msg.event === 'waiting_wake') {
        liveTalkActive = true;
        liveTalkWaitingWake = true;
        setVoiceState('standby');
        setOledAiMode('neutral');
        logToTerminal(msg.calibrating
            ? 'LIVE: đang đo tiếng nền trước khi chờ wakeword'
            : 'LIVE: đang chờ tên Moon', 'ai-state');
    } else if (msg.event === 'wake') {
        liveTalkActive = true;
        liveTalkWaitingWake = false;
        setVoiceState('listening');
        setOledAiMode('questioning');
        logToTerminal('WAKE: đã nghe tên Moon — mở Live Talk', 'log-voice');
    } else if (msg.event === 'wake_ack') {
        setVoiceState('speaking');
        drawFace('happy');
        logToTerminal('MOON: Moon nghe đây!', 'ai-response');
    } else if (msg.event === 'brain_question') {
        showUserQuestion(msg.text);
        showThinking('Brain và LLM đang xử lý…');
        setOledAiMode('ai-thinking');
        setVoiceState('thinking');
        logToTerminal(`VOICE CONTINUOUS: ${msg.text}`, 'log-voice');
        socket.emit('voice_question', msg.text);
    } else if (['ready', 'listening', 'user_speaking', 'interrupted'].includes(msg.event)) {
        liveTalkActive = true;
        liveTalkWaitingWake = false;
        setVoiceState('listening');
        if (msg.event === 'ready') setOledAiMode('neutral');
        if (msg.event === 'listening' && msg.activatedBy === 'wakeword') setOledAiMode('neutral');
    } else if (msg.event === 'thinking') {
        setVoiceState('thinking');
    } else if (msg.event === 'speaking') {
        setVoiceState('speaking');
    } else if (msg.event === 'expression') {
        drawFace(ALL_EMOTIONS.includes(msg.expression) ? msg.expression : 'neutral');
        logToTerminal(`LIVE OLED: ${msg.expression}`, 'status');
    } else if (['stopped', 'error'].includes(msg.event)) {
        if (liveTalkMode === 'brain') socket.emit('mic_live', '0');
        liveTalkActive = false;
        liveTalkMode = '';
        liveTalkWaitingWake = false;
        setVoiceState('standby');
        setOledAiMode('neutral');
        logToTerminal(msg.event === 'error' ? `LIVE lỗi: ${msg.text || 'Mất kết nối'}` : 'LIVE: đã kết thúc', 'sys');
    }
});
