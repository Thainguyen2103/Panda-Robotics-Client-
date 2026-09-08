// npm install --no-save playwright in a separate test environment, then NODE_PATH
// may point to its node_modules. Uses a fake mic and mocked server, no cloud audio.
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
(async () => {
    const browser = await chromium.launch({channel: 'msedge', headless: true,
        args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream']});
    try {
        const context = await browser.newContext({permissions: ['microphone']});
        const page = await context.newPage();
        const errors = [];
        page.on('pageerror', e => errors.push(e.message));
        let frames = 0;
        await page.routeWebSocket('**/ws', socket => {
            socket.send(JSON.stringify({event: 'ready', engine: 'TEST mock'}));
            socket.onMessage(data => {
                assert.equal(data.length, 960);
                if (++frames === 4) {
                    for (const msg of [{event: 'wake', engine: 'mock'},
                        {event: 'transcript', text: 'Moon, Tôi muốn học tiếng Anh.', latency_ms: 50, duration_ms: 1500},
                        {event: 'question', text: 'Tôi muốn học tiếng Anh.'}]) socket.send(JSON.stringify(msg));
                }
            });
        });
        await page.goto('http://localhost:8765');
        await page.evaluate(() => {
            window.toneCount = 0;
            const create = AudioContext.prototype.createOscillator;
            AudioContext.prototype.createOscillator = function () {
                window.toneCount++;
                return create.call(this);
            };
        });
        await page.locator('#test-sound').click();
        assert.equal(await page.evaluate(() => window.toneCount), 1);
        await page.locator('#start').click();
        await page.waitForFunction(() => document.getElementById('question').textContent === 'Tôi muốn học tiếng Anh.');
        assert.match(await page.locator('#log').innerText(), /Moon, Tôi muốn học tiếng Anh/);
        assert.equal(await page.evaluate(() => window.toneCount), 2, 'wake event must play the cue');
        await page.locator('#stop').click();
        assert.equal(await page.locator('#start').isEnabled(), true);
        assert.equal(await page.locator('#stop').isDisabled(), true);
        await page.locator('#start').click();
        await page.waitForFunction(() => document.getElementById('state').textContent === 'Đang chờ Moon');
        await page.locator('#stop').click();
        await page.setViewportSize({width: 390, height: 844});
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
        await page.screenshot({path: '.voice-venv/voice-ui.png', fullPage: true});
        assert.deepEqual(errors, []);
        assert(frames >= 4);
        console.log('Voice browser: fake mic PCM stream, transcript, restart, mobile layout passed');
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
