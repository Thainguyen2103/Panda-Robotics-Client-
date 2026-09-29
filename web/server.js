const express = require('express');
const http = require('http');
const socketIo = require('socket.io');
const mqtt = require('mqtt');
const path = require('path');

const app = express();
const server = http.createServer(app);
const io = socketIo(server);
const {attachVoice, startVoiceService} = require('./voice-bridge');
const {attachGeminiLive} = require('./gemini-live-bridge');
const {attachGeminiTranscribe} = require('./gemini-transcribe-bridge');
const {readFishConfig, synthesizeFishWithRetry} = require('./fish-tts');

// Define MQTT settings
const MQTT_BROKER = 'mqtt://localhost:1883';
const mqttClient = mqtt.connect(MQTT_BROKER);
attachVoice(server);
attachGeminiLive(server, mqttClient);
attachGeminiTranscribe(server);
startVoiceService();

// Tạo một lần rồi giữ trong RAM để lời xác nhận wakeword phát gần như tức thì.
// API key chỉ được dùng ở server, không bao giờ gửi xuống trình duyệt.
const fishConfig = readFishConfig();
let wakeAckAudio = null;
let wakeAckPending = null;

async function getWakeAckAudio() {
    if (wakeAckAudio) return wakeAckAudio;
    if (!wakeAckPending) {
        wakeAckPending = synthesizeFishWithRetry('Moon nghe đây!', fishConfig, {
            attempts: 1,
            timeoutMs: 6000,
        }).then(audio => {
            wakeAckAudio = audio;
            return audio;
        }).finally(() => {
            wakeAckPending = null;
        });
    }
    return wakeAckPending;
}

app.get('/api/live-ack', async (_req, res) => {
    try {
        const audio = await getWakeAckAudio();
        res.set('Content-Type', 'audio/mpeg');
        res.set('Cache-Control', 'private, max-age=3600');
        res.send(audio);
    } catch (error) {
        console.warn(`⚠️ [WEB] Không tạo được lời xác nhận Fish: ${error.message}`);
        res.status(503).json({error: 'Fish acknowledgement unavailable'});
    }
});

app.post('/api/preload-model', (req, res) => {
    const postData = JSON.stringify({
        model: 'qwen3.5:2b',
        prompt: '',
        keep_alive: '60m', // Giữ trong RAM 60 phút
        options: {
            num_gpu: 99 // Ép Ollama nạp 100% các lớp của mô hình lên VRAM của Card rời
        }
    });
    const options = {
        hostname: '127.0.0.1',
        port: 11434,
        path: '/api/generate',
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Content-Length': Buffer.byteLength(postData)
        }
    };
    const ollamaReq = http.request(options, (ollamaRes) => {
        ollamaRes.on('data', () => {}); // Consume data
        ollamaRes.on('end', () => res.json({success: true}));
    });
    ollamaReq.on('error', (e) => {
        console.error(`⚠️ [WEB] Preload Error: ${e.message}`);
        res.status(500).json({error: e.message});
    });
    ollamaReq.write(postData);
    ollamaReq.end();
});

// Serve static files
// index.html: KHÔNG cache — để mọi lần tải đều lấy bản mới (chống lỗi file cũ)
app.get(['/', '/index.html'], (req, res) => {
    res.set('Cache-Control', 'no-store, no-cache, must-revalidate');
    res.set('Pragma', 'no-cache');
    res.sendFile(path.join(__dirname, 'public', 'index.html'));
});
app.use(express.static(path.join(__dirname, 'public')));

// MQTT Connection
mqttClient.on('connect', () => {
    console.log('✅ [WEB] Connected to MQTT Broker');
    mqttClient.subscribe('moon/status');
    mqttClient.subscribe('moon/cmd/#');
    mqttClient.subscribe('moon/log/voice');
    mqttClient.subscribe('moon/log/voice_partial');
    mqttClient.subscribe('moon/camera');
    mqttClient.subscribe('moon/user_status');
    mqttClient.subscribe('moon/vision/status');
    mqttClient.subscribe('moon/ai/state');
    mqttClient.subscribe('moon/ai/thinking');
    mqttClient.subscribe('moon/ai/response');
    mqttClient.subscribe('moon/ai/topic');
    mqttClient.subscribe('moon/audio/tts_active');
});

mqttClient.on('message', (topic, message) => {
    const payload = message.toString();
    // Forward MQTT messages to connected WebSocket clients
    io.emit('mqtt_message', { topic, payload });
});

// Socket.io Connection (Web clients)
io.on('connection', (socket) => {
    console.log('🌐 [WEB] A client connected');
    
    // Receive command from Web UI and forward to MQTT
    socket.on('send_cmd', (data) => {
        console.log(`➡️ [WEB -> MQTT] ${data.topic}: ${data.payload}`);
        mqttClient.publish(data.topic, data.payload);
    });

    socket.on('disconnect', () => {
        console.log('🌐 [WEB] A client disconnected');
    });

    // Browser push-to-talk: nhận base64 webm từ dashboard → chuyển sang MQTT cho brain
    socket.on('voice_audio', (b64) => {
        console.log(`🎤 [WEB] Browser audio received (${Math.round(b64.length / 1024)} KB b64) → MQTT`);
        mqttClient.publish('moon/ai/voice_audio', b64);
    });

    // Live-mic: clip PCM đã khử nhiễu từ trình duyệt → MQTT
    socket.on('voice_clip', (b64) => {
        mqttClient.publish('moon/ai/clip', b64);
    });
    socket.on('mic_live', (st) => {
        console.log(`🎙️ [WEB] Live mic: ${st}`);
        mqttClient.publish('moon/ai/mic_live', st);
    });
    socket.on('voice_question', (text) => {
        if (typeof text !== 'string') return;
        text = text.trim().slice(0, 1000);
        if (text) mqttClient.publish('moon/ai/question', text);
    });
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => {
    console.log(`🚀 [WEB] Dashboard running at http://localhost:${PORT}`);
    
    // Tự động nạp model Ollama lên VRAM lúc khởi động Server
    console.log('🤖 [WEB] Đang tự động nạp AI model vào VRAM...');
    const postData = JSON.stringify({
        model: 'qwen3.5:2b',
        prompt: '',
        keep_alive: '60m',
        options: { num_gpu: 99 }
    });
    const options = {
        hostname: '127.0.0.1',
        port: 11434,
        path: '/api/generate',
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Content-Length': Buffer.byteLength(postData)
        }
    };
    const req = http.request(options, (res) => {
        res.on('data', () => {}); 
        res.on('end', () => console.log('✅ [WEB] Nạp model tự động thành công! Robot phản hồi không độ trễ.'));
    });
    req.on('error', (e) => console.log(`⚠️ [WEB] Lỗi nạp model tự động (Có thể Ollama chưa bật): ${e.message}`));
    req.write(postData);
    req.end();
});
