const express = require('express');
const http = require('http');
const socketIo = require('socket.io');
const mqtt = require('mqtt');
const path = require('path');

const app = express();
const server = http.createServer(app);
const io = socketIo(server);

// Define MQTT settings
const MQTT_BROKER = 'mqtt://localhost:1883';
const mqttClient = mqtt.connect(MQTT_BROKER);

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
    mqttClient.subscribe('panda/status');
    mqttClient.subscribe('panda/cmd/#');
    mqttClient.subscribe('panda/log/voice');
    mqttClient.subscribe('panda/log/voice_partial');
    mqttClient.subscribe('panda/camera');
    mqttClient.subscribe('panda/user_status');
    mqttClient.subscribe('panda/ai/state');
    mqttClient.subscribe('panda/ai/thinking');
    mqttClient.subscribe('panda/ai/response');
    mqttClient.subscribe('panda/ai/topic');
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
        mqttClient.publish('panda/ai/voice_audio', b64);
    });

    // Live-mic: clip PCM đã khử nhiễu từ trình duyệt → MQTT
    socket.on('voice_clip', (b64) => {
        mqttClient.publish('panda/ai/clip', b64);
    });
    socket.on('mic_live', (st) => {
        console.log(`🎙️ [WEB] Live mic: ${st}`);
        mqttClient.publish('panda/ai/mic_live', st);
    });
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => {
    console.log(`🚀 [WEB] Dashboard running at http://localhost:${PORT}`);
});
