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
        const say = message => page.evaluate(detail => window.dispatchEvent(
            new CustomEvent('moon-live', {detail})), message);

        // Wakeword chỉ là cổng kích hoạt. Trong lúc chờ OLED giữ trạng thái mặc định.
        await say({event: 'starting', pipeline: 'gemini'});
        await say({event: 'waiting_wake', pipeline: 'gemini'});
        assert.match(await page.locator('#oled-face').getAttribute('class'), /neutral/);
        await say({event: 'wake', pipeline: 'gemini'});
        assert.match(await page.locator('#oled-face').getAttribute('class'), /questioning/);
        await say({event: 'ready', pipeline: 'gemini'});
        assert.match(await page.locator('#oled-face').getAttribute('class'), /neutral/);
        await say({event: 'expression', pipeline: 'gemini', expression: 'happy'});
        assert.match(await page.locator('#oled-face').getAttribute('class'), /happy/);
        await say({event: 'stopped', pipeline: 'gemini'});
        assert.match(await page.locator('#oled-face').getAttribute('class'), /neutral/);

        // Brain Live giữ chữ trong thẻ hội thoại; OLED chỉ hiện trạng thái/biểu cảm.
        await say({event: 'starting', pipeline: 'brain'});
        await say({event: 'brain_question', pipeline: 'brain', text: 'Ronaldo là ai?'});
        assert.equal(await page.locator('#ai-user-text').textContent(), 'Ronaldo là ai?');
        assert.equal(await page.locator('#ai-thinking-bar').isVisible(), true);
        assert.match(await page.locator('#oled-face').getAttribute('class'), /ai-thinking/);
        assert.equal(await page.locator('#oled-text').textContent(), '');

        await page.evaluate(() => {
            const receive = socket.listeners('mqtt_message')[0];
            receive({topic: 'panda/ai/thinking', payload: JSON.stringify({
                stage: 'question_corrected', text: 'Ronaldo là ai?',
                original: 'ronando là ai?', changed: true,
            })});
            receive({topic: 'panda/ai/thinking', payload: JSON.stringify({
                stage: 'answer', text: 'Một cầu thủ.',
            })});
            receive({topic: 'panda/ai/response', payload: JSON.stringify({
                text: 'Một cầu thủ.', done: true,
            })});
        });
        assert.equal(await page.locator('#ai-moon-text').textContent(), 'Một cầu thủ.');
        assert.equal(await page.locator('#oled-text').textContent(), '');
        assert.match(await page.locator('#oled-face').getAttribute('class'), /speaking/);

        await page.evaluate(() => socket.listeners('mqtt_message')[0](
            {topic: 'panda/ai/state', payload: 'standby'}));
        assert.match(await page.locator('#oled-face').getAttribute('class'), /neutral/);
        await say({event: 'stopped', pipeline: 'brain'});
        assert.deepEqual(errors, []);
        console.log('Voice display: wake gate, Live Voice OLED states and Brain chat passed');
    } finally {
        await browser.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
