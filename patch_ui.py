import os
import re

def replace_in_file(filepath, old, new):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    content = content.replace(old, new)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

# 1. Update index.html for Camera scaling
html_path = 'web/public/index.html'
replace_in_file(html_path, 'object-fit:cover', 'object-fit:contain')

# 2. Update style.css for 24x10 matrix and camera ratio
css_path = 'web/public/style.css'
css_cam_old = '''.camera-box {
    background: #000;
    height: 200px;
    border-radius: 8px;'''
css_cam_new = '''.camera-box {
    background: #000;
    aspect-ratio: 4/3;
    width: 100%;
    border-radius: 8px;'''
replace_in_file(css_path, css_cam_old, css_cam_new)

css_led_old = '''.led-matrix {
    display: grid;
    grid-template-columns: repeat(16, 12px);
    grid-template-rows: repeat(8, 12px);
    gap: 4px;
}'''
css_led_new = '''.led-matrix {
    display: grid;
    grid-template-columns: repeat(24, 12px);
    grid-template-rows: repeat(10, 12px);
    gap: 4px;
}'''
replace_in_file(css_path, css_led_old, css_led_new)

css_on_old = '''.led.on {
    background-color: var(--led-on);
    box-shadow: 0 0 8px var(--led-on);
}'''
css_on_new = '''.led.on {
    background-color: var(--led-on);
    box-shadow: 0 0 8px var(--led-on);
}
.led.pupil {
    background-color: #ff4757;
    box-shadow: 0 0 8px #ff4757;
}'''
replace_in_file(css_path, css_on_old, css_on_new)

# 3. Update app.js for 24x10 array with pupils
js_path = 'web/public/app.js'
with open(js_path, 'r', encoding='utf-8') as f:
    js_content = f.read()

# Replace matrix initialization
js_content = re.sub(r'const leds = \[\];.*?const faces =', '''const leds = [];
for (let i = 0; i < 240; i++) {
    const led = document.createElement('div');
    led.className = 'led';
    matrixDiv.appendChild(led);
    leds.push(led);
}

const faces =''', js_content, flags=re.DOTALL)

# Replace faces object
faces_new = '''const faces = {
    neutral: [
        "000000000000000000000000",
        "000000000000000000000000",
        "000111111000001111110000",
        "001111111100011111111000",
        "001112211100011122111000",
        "001112211100011122111000",
        "001111111100011111111000",
        "000111111000001111110000",
        "000000000000000000000000",
        "000000000000000000000000"
    ],
    happy: [
        "000000000000000000000000",
        "000001100000000011000000",
        "000111111000001111110000",
        "001111111100011111111000",
        "011100011100011100011100",
        "011000001100011000001100",
        "110000000110110000000110",
        "100000000010100000000010",
        "000000000000000000000000",
        "000000000000000000000000"
    ],
    sad: [
        "000000000000000000000000",
        "000000000000000000000000",
        "000000000000000000000000",
        "100000000010100000000010",
        "110000000110110000000110",
        "011000001100011000001100",
        "011100011100011100011100",
        "001111111100011111111000",
        "000111111000001111110000",
        "000001100000000011000000"
    ],
    surprised: [
        "000000000000000000000000",
        "000011110000000011110000",
        "000111111000000111111000",
        "001110011100001110011100",
        "001102201100001102201100",
        "001102201100001102201100",
        "001110011100001110011100",
        "000111111000000111111000",
        "000011110000000011110000",
        "000000000000000000000000"
    ]
};

function drawFace(faceName) {
    const pattern = faces[faceName] || faces['neutral'];
    let i = 0;
    for (let row = 0; row < 10; row++) {
        for (let col = 0; col < 24; col++) {
            leds[i].classList.remove('on', 'pupil');
            if (pattern[row][col] === '1') {
                leds[i].classList.add('on');
            } else if (pattern[row][col] === '2') {
                leds[i].classList.add('pupil');
            }
            i++;
        }
    }
}'''

js_content = re.sub(r'const faces = \{.*?\n\}\n\nfunction drawFace.*?\}\n\}', faces_new, js_content, flags=re.DOTALL)

with open(js_path, 'w', encoding='utf-8') as f:
    f.write(js_content)

print("UI update successful!")
