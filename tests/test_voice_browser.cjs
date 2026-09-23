// npm install --no-save playwright in a separate test environment, then NODE_PATH
// may point to its node_modules. Uses a fake mic and mocked servers, no cloud audio.
const assert = require('node:assert/strict');
const {chromium} = require('playwright');

(async () => {
    const browser = await chromium.launch({channel: 'msedge', headless: true,
        args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream']});
    try {
        const context = await browser.newContext({permissions: ['microphone']});
        const page = await context.newPage();
        const errors = [], controls = [];
        let wakeConnections = 0, liveConnections = 0, wakeFrames = 0, liveFrames = 0;
        let wakeScheduled = false;
        page.on('pageerror', error => errors.push(error.message));

        await page.addInitScript(() => {
            window.MOON_WAKE_IDLE_TIMEOUT_MS = 1200;
            window.wakeAckTexts = [];
            window.speechSynthesis.speak = utterance => {
                window.wakeAckTexts.push(utterance.text);
                queueMicrotask(() => {
                    utterance.onstart?.();
                    utterance.onend?.();
                });
            };
        });
        await page.route('**/api/live-ack', route => route.fulfill({
            status: 503,
            contentType: 'application/json',
            body: JSON.stringify({error: 'test fallback'}),
        }));

        await page.routeWebSocket('**/transcribe/ws**', socket => {
            wakeConnections++;
            socket.send(JSON.stringify({
                event: 'ready', engine: 'TEST multilingual wake mock', calibrating: false,
            }));
            socket.onMessage(data => {
                if (typeof data === 'string') {
                    controls.push(JSON.parse(data).command);
                    return;
                }
                assert.equal(data.length, 960);
                wakeFrames++;
                if (!wakeScheduled) {
                    wakeScheduled = true;
                    setTimeout(() => socket.send(JSON.stringify({event: 'wake', engine: 'mock'})), 380);
                }
            });
        });
        await page.routeWebSocket('**/live/ws**', socket => {
            liveConnections++;
            const connection = liveConnections;
            let responded = false;
            socket.send(JSON.stringify({
                event: 'ready', model: 'TEST live',
                voice: connection === 1 ? 'Fish Voice' : 'Kore',
                outputMode: connection === 1 ? 'fish' : 'native',
            }));
            socket.onMessage(data => {
                if (typeof data === 'string') controls.push(JSON.parse(data).command);
                else {
                    assert.equal(data.length, 960);
                    liveFrames++;
                    if (connection === 2 && !responded) {
                        responded = true;
                        socket.send(JSON.stringify({event: 'speaking', format: 'pcm'}));
                        socket.send(Buffer.alloc(960));
                        socket.send(JSON.stringify({event: 'turn_complete'}));
                    }
                }
            });
        });

        await page.goto('http://localhost:3000');
        await page.evaluate(() => {
            window.toneCount = 0;
            const create = AudioContext.prototype.createOscillator;
            AudioContext.prototype.createOscillator = function () {
                window.toneCount++;
                return create.call(this);
            };
            window.audioStartDelays = [];
            const createSource = AudioContext.prototype.createBufferSource;
            AudioContext.prototype.createBufferSource = function () {
                const audioContext = this;
                const node = createSource.call(this);
                const start = node.start.bind(node);
                node.start = (when = 0, ...args) => {
                    window.audioStartDelays.push(when - audioContext.currentTime);
                    return start(when, ...args);
                };
                return node;
            };
        });

        await page.locator('#live-activation').selectOption('wakeword');
        await page.locator('#live-start').click();
        await page.waitForFunction(() => document.getElementById('live-state').textContent.includes('Sẵn sàng'));
        await page.waitForFunction(() => document.getElementById('live-state').textContent.includes('Đã thức'));
        await page.waitForFunction(() => window.toneCount >= 2);
        await page.waitForTimeout(150);
        assert.equal(wakeConnections, 1);
        assert.equal(liveConnections, 1);
        assert(wakeFrames > 0);
        assert(liveFrames > 0);
        assert.equal(await page.evaluate(() => window.toneCount), 2);
        assert.deepEqual(await page.evaluate(() => window.wakeAckTexts), ['Moon nghe đây!']);
        await page.waitForFunction(() =>
            document.getElementById('live-state').textContent.includes('Sẵn sàng'));
        assert.equal(wakeConnections, 2,
            'wakeword mode must return to wake listening after inactivity');
        assert.equal(liveConnections, 1,
            'inactivity must close the current Live session instead of opening another one');
        await page.locator('#live-stop').click();
        assert.equal(await page.locator('#live-start').isEnabled(), true);
        assert.equal(await page.locator('#live-stop').isDisabled(), true);

        await page.locator('#live-activation').selectOption('manual');
        await page.locator('#live-mode').selectOption('native');
        await page.locator('#live-start').click();
        await page.waitForFunction(() => document.getElementById('live-state').textContent.includes('Moon đang nghe'));
        await page.waitForFunction(() => window.audioStartDelays.length > 0);
        assert((await page.evaluate(() => window.audioStartDelays.at(-1))) < .2,
            'Fish → Kore must reset the old AudioContext playback timeline');
        assert.equal(wakeConnections, 2, 'manual mode must bypass wakeword service');
        assert.equal(liveConnections, 2);
        await page.locator('#live-stop').click();

        await page.setViewportSize({width: 390, height: 844});
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
        await page.screenshot({path: '.voice-venv/voice-ui.png', fullPage: true});
        assert.match(await page.locator('#terminal-log').innerText(), /WAKE: đã nghe tên Moon/);
        assert(controls.includes('pause'), 'wake socket must pause before Live Talk handoff');
        assert(controls.includes('audio_stream_end'), 'manual Live Talk must close its audio stream cleanly');
        assert.deepEqual(errors, []);
        console.log('Voice browser: wakeword handoff, manual activation and mobile layout passed');
    } finally {
        await browser.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
