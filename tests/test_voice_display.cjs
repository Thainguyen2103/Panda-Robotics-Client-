const assert = require('node:assert/strict');
const {chromium} = require('playwright');
(async () => {
    const browser = await chromium.launch({channel: 'msedge', headless: true});
    try {
        const page = await browser.newPage();
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        await page.goto('http://localhost:3000');
        await page.waitForFunction(() => typeof setOledAiMode === 'function');
        const say = msg => page.evaluate(detail => window.dispatchEvent(new CustomEvent('moon-voice', {detail})), msg);
        const text = 'Tôi muốn học tiếng Việt, dấu hỏi, dấu ngã và ký hiệu <b>nguyên văn</b>. '.repeat(8);
        await say({event: 'question', text});
        await page.evaluate(() => {
            const receive = socket.listeners('mqtt_message')[0];
            receive({topic: 'panda/ai/thinking', payload: JSON.stringify({stage: 'thinking'})});
            receive({topic: 'panda/ai/response', payload: JSON.stringify({text: 'STALE', done: false})});
            receive({topic: 'panda/ai/state', payload: 'speaking'});
            receive({topic: 'panda/cmd/face', payload: 'happy'});
        });
        assert.equal(await page.locator('#ai-user-text').textContent(), text);
        assert.equal(await page.locator('#oled-text').textContent(), `"${text}"`);
        assert.equal(await page.locator('#ai-thinking-bar').isVisible(), false);
        assert.equal(await page.locator('#ai-moon-bubble').isVisible(), false);
        assert.equal(await page.locator('#terminal-log b').count(), 0, 'transcript must not become HTML');
        assert(await page.locator('#terminal-log').textContent().then(t => t.includes('<b>nguyên văn</b>')));
        const layout = await page.locator('#oled-text').evaluate(el => ({
            animation: getComputedStyle(el).animationName,
            overflow: getComputedStyle(el).overflowY,
            canScroll: el.scrollHeight > el.clientHeight
        }));
        assert.deepEqual(layout, {animation: 'none', overflow: 'auto', canScroll: true});
        await page.locator('#oled-face').screenshot({path: '.voice-venv/oled-transcript.png'});
        await page.waitForFunction(() => document.getElementById('oled-face').classList.contains('neutral'), null, {timeout: 8000});
        assert.equal(await page.locator('#ai-user-text').textContent(), text);
        await say({event: 'question', text: 'Câu trước'});
        await say({event: 'wake'});
        await page.waitForTimeout(6100);
        assert.match(await page.locator('#oled-face').getAttribute('class'), /questioning/, 'old timer must not clear new wake');
        await say({event: 'timeout'});
        assert.match(await page.locator('#oled-face').getAttribute('class'), /neutral/);
        await say({event: 'question', text: 'Câu cuối'});
        await say({event: 'stopped'});
        assert.match(await page.locator('#oled-face').getAttribute('class'), /neutral/);
        assert.deepEqual(errors, []);
        console.log('Voice display: stale MQTT isolation, literal long text, hold timer, wake and stop reset passed');
    } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
