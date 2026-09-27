import os
import re

def replace_in_file(filepath, old, new):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    if old not in content:
        print(f"Warning: '{old}' not found in {filepath}")
    content = content.replace(old, new)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

# 1. Update index.html
html_path = 'web/public/index.html'
html_old = '''                    <h3>LED Face</h3>
                    <div class="led-wrapper">
                        <div id="led-matrix" class="led-matrix"></div>
                    </div>'''
html_new = '''                    <h3>OLED Face</h3>
                    <div class="led-wrapper">
                        <div id="oled-face" class="oled-face neutral">
                            <div class="eye left"><div class="pupil"></div></div>
                            <div class="eye right"><div class="pupil"></div></div>
                        </div>
                    </div>'''
replace_in_file(html_path, html_old, html_new)

# 2. Update style.css
css_path = 'web/public/style.css'
with open(css_path, 'r', encoding='utf-8') as f:
    css_content = f.read()

css_old_regex = r'\.led-matrix \{.*?\n\}\n\n\.led \{.*?\n\}\n\n\.led\.on \{.*?\n\}\n\.led\.pupil \{.*?\n\}'
css_new = '''.oled-face {
    background: #000;
    width: 100%;
    height: 150px;
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 50px;
}
.eye {
    width: 90px;
    height: 70px;
    background-color: #2b2a75;
    position: relative;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.eye.left .pupil {
    width: 40px;
    height: 35px;
    background-color: #fff;
    position: absolute;
    bottom: 0;
    right: 0;
    transition: all 0.3s;
}
.eye.right .pupil {
    width: 40px;
    height: 35px;
    background-color: #fff;
    position: absolute;
    bottom: 0;
    left: 0;
    transition: all 0.3s;
}

/* Các trạng thái cảm xúc */
.oled-face.happy .eye {
    border-radius: 50% 50% 10% 10%;
    height: 50px;
    margin-top: -20px;
    background-color: #00d2ff;
}
.oled-face.happy .pupil { background-color: transparent; }

.oled-face.sad .eye.left { clip-path: polygon(0 40%, 100% 0, 100% 100%, 0 100%); }
.oled-face.sad .eye.right { clip-path: polygon(0 0, 100% 40%, 100% 100%, 0 100%); }
.oled-face.sad .pupil { height: 20px; }

.oled-face.surprised .eye {
    height: 90px;
    width: 70px;
    border-radius: 35px;
    background-color: #ff4757;
}
.oled-face.surprised .pupil {
    width: 30px;
    height: 30px;
    border-radius: 50%;
    left: 20px !important;
    right: 20px !important;
    bottom: 30px;
}'''

# Replace using regex because previous patch changed the exact text
css_content = re.sub(r'\.led-matrix \{.*?(?=\.camera-box \{)', css_new + '\n\n', css_content, flags=re.DOTALL)
with open(css_path, 'w', encoding='utf-8') as f:
    f.write(css_content)

# 3. Update app.js
js_path = 'web/public/app.js'
with open(js_path, 'r', encoding='utf-8') as f:
    js_content = f.read()

js_old_regex = r'// LED Matrix Setup.*?function drawFace\(faceName\) \{.*?\}\n'
js_new = '''const oledFace = document.getElementById('oled-face');

function drawFace(faceName) {
    // Xóa các class cảm xúc cũ
    oledFace.classList.remove('neutral', 'happy', 'sad', 'surprised');
    // Thêm class mới
    oledFace.classList.add(faceName);
}
'''
js_content = re.sub(r'// LED Matrix Setup.*?function drawFace\(faceName\) \{.*?\}\n\}', js_new, js_content, flags=re.DOTALL)
js_content = js_content.replace("drawFace('neutral');", "drawFace('neutral');")

with open(js_path, 'w', encoding='utf-8') as f:
    f.write(js_content)

print("Robot eyes updated successfully!")
