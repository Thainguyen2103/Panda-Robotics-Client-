// Run with dashboard on :3000. Sends silence only; does not call STT/cloud APIs.
const assert = require('node:assert/strict');
const {WebSocket} = require('../web/node_modules/ws');

const socket = new WebSocket('ws://localhost:3000/voice/ws?mode=continuous', {
    origin: 'http://localhost:3000',
});
let sender;
const timeout = setTimeout(() => {
    console.error('Continuous Voice proxy timeout');
    process.exit(1);
}, 10000);

socket.on('error', error => {
    clearTimeout(timeout);
    console.error(error);
    process.exitCode = 1;
});
socket.on('message', data => {
    const message = JSON.parse(data);
    if (message.event === 'ready') {
        assert.equal(message.mode, 'continuous');
        assert.match(message.engine, /không cần wake word/i);
        let frames = 0;
        sender = setInterval(() => {
            if (socket.readyState !== WebSocket.OPEN) {
                clearInterval(sender);
                return;
            }
            socket.send(Buffer.alloc(960));
            if (++frames === 60) clearInterval(sender);
        }, 30);
    }
    if (message.event === 'calibrated') {
        clearTimeout(timeout);
        socket.close();
        console.log('Continuous Voice proxy: mode, calibration and same-origin transport passed');
    }
    if (message.event === 'error') throw new Error(message.text);
});
