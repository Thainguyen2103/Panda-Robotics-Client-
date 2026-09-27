// Run with dashboard on :3000. Sends only silence, no STT/cloud requests.
const assert = require('node:assert/strict');
const {WebSocket} = require('../web/node_modules/ws');
const socket = new WebSocket('ws://localhost:3000/voice/ws', {origin: 'http://localhost:3000'});
let sender;
const timeout = setTimeout(() => {console.error('Voice proxy timeout'); process.exit(1);}, 10000);
socket.on('error', error => {clearTimeout(timeout); console.error(error); process.exitCode = 1;});
socket.on('message', data => {
    const msg = JSON.parse(data);
    if (msg.event === 'ready') {
        assert.equal(msg.calibrating, true);
        let frames = 0;
        sender = setInterval(() => {
            if (socket.readyState !== WebSocket.OPEN) {clearInterval(sender); return;}
            socket.send(Buffer.alloc(960));
            if (++frames === 60) clearInterval(sender);
        }, 30);
    }
    if (msg.event === 'calibrated') {
        assert(msg.threshold > 0);
        socket.send(JSON.stringify({command:'pause'}));
        socket.send(JSON.stringify({command:'resume'}));
    }
    if (msg.event === 'resumed') {
        clearTimeout(timeout);
        socket.close();
        console.log('Dashboard voice proxy: readiness, audio, calibration and pause/resume passed');
    }
    if (msg.event === 'error') {throw new Error(msg.text);}
});
