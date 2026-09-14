// Same-origin audio transport. Voice frames never enter MQTT or Brain.
const {WebSocket, WebSocketServer} = require('ws');
const net = require('node:net');
const path = require('node:path');
const fs = require('node:fs');
const {spawn} = require('node:child_process');

function attachVoice(server) {
    const wss = new WebSocketServer({noServer: true, maxPayload: 4096});
    server.on('upgrade', (req, socket, head) => {
        if (req.url !== '/voice/ws') return; // Socket.IO handles its own path.
        if (req.headers.origin !== `http://${req.headers.host}`) {
            socket.end('HTTP/1.1 403 Forbidden\r\n\r\n'); return;
        }
        wss.handleUpgrade(req, socket, head, downstream => {
            let upstream, retryTimer, attempts = 0;
            const fail = () => {
                if (downstream.readyState === WebSocket.OPEN) {
                    downstream.send(JSON.stringify({event: 'error', text: 'Voice service không khởi động được sau 15 giây. Kiểm tra môi trường Python.'}));
                    downstream.close(1011);
                }
            };
            const connectUpstream = () => {
                if (downstream.readyState !== WebSocket.OPEN) return;
                const candidate = new WebSocket('ws://127.0.0.1:8765/ws', {
                    origin: 'http://127.0.0.1:8765', handshakeTimeout: 1500,
                    maxPayload: 1024 * 1024
                });
                upstream = candidate;
                let opened = false;
                candidate.on('open', () => { opened = true; });
                candidate.on('error', () => {});
                candidate.on('message', data => {
                    if (candidate !== upstream || downstream.readyState !== WebSocket.OPEN) return;
                    if (downstream.bufferedAmount > 1024 * 1024) { downstream.close(1013); return; }
                    downstream.send(data.toString());
                });
                candidate.on('close', () => {
                    if (candidate !== upstream || downstream.readyState !== WebSocket.OPEN) return;
                    upstream = null;
                    if (opened) { downstream.close(); return; }
                    if (++attempts >= 30) { fail(); return; }
                    retryTimer = setTimeout(connectUpstream,500);
                });
            };
            downstream.on('message', (data, binary) => {
                if ((binary && data.length !== 960) || (!binary && data.length > 100)) { downstream.close(1003); return; }
                if (!upstream || upstream.readyState !== WebSocket.OPEN || upstream.bufferedAmount > 32000) {
                    downstream.close(1013); return;
                }
                upstream.send(data,{binary});
            });
            downstream.on('close', () => { clearTimeout(retryTimer); upstream?.terminate(); });
            downstream.on('error', () => { clearTimeout(retryTimer); upstream?.terminate(); });
            connectUpstream();
        });
    });
}

function startVoiceService() {
    let child;
    const probe = net.connect(8765, '127.0.0.1');
    probe.setTimeout(1500, () => probe.destroy(new Error('timeout')));
    probe.once('connect', () => probe.end()); // Reuse a running Voice service.
    probe.once('error', () => {
        const root = path.resolve(__dirname, '..');
        const python = [path.join(root, '.voice-venv', 'Scripts', 'python.exe'),
            path.join(root, '.voice-venv', 'bin', 'python')].find(p => fs.existsSync(p)) || 'python';
        child = spawn(python, ['-m', 'server.voice_lab'], {cwd: root, windowsHide: true, stdio: 'inherit'});
        child.on('error', err => console.error('[VOICE] Cannot start:', err.message));
        child.on('exit', code => console.log('[VOICE] Service exited:', code));
    });
    process.once('exit', () => { if (child) child.kill(); });
}

module.exports = {attachVoice, startVoiceService};
