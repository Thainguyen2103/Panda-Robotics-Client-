import os
import re

css_path = 'web/public/style.css'
with open(css_path, 'r', encoding='utf-8') as f:
    css_content = f.read()

css_new = '''.oled-face {
    background: #000;
    width: 256px;
    height: 128px;
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 24px;
    border-radius: 8px;
    border: 2px solid #222;
    box-shadow: 0 0 20px rgba(0, 210, 255, 0.2);
}
.eye {
    width: 50px;
    height: 70px;
    background-color: #00d2ff;
    border-radius: 18px;
    transition: all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
    box-shadow: 0 0 15px rgba(0, 210, 255, 0.6);
}
.eye .pupil { display: none; } /* Vector không dùng tròng đen/trắng */

/* Cảm xúc Happy */
.oled-face.happy .eye {
    height: 45px;
    border-radius: 25px 25px 10px 10px;
    transform: translateY(-10px);
}
.oled-face.happy .eye.left { transform: translateY(-10px) rotate(-10deg); }
.oled-face.happy .eye.right { transform: translateY(-10px) rotate(10deg); }

/* Cảm xúc Sad */
.oled-face.sad .eye {
    height: 50px;
    background-color: #0088aa;
    box-shadow: 0 0 10px rgba(0, 136, 170, 0.6);
}
.oled-face.sad .eye.left {
    transform: rotate(20deg) translateY(15px) translateX(10px);
    border-radius: 10px 20px 15px 25px;
}
.oled-face.sad .eye.right {
    transform: rotate(-20deg) translateY(15px) translateX(-10px);
    border-radius: 20px 10px 25px 15px;
}

/* Cảm xúc Surprised */
.oled-face.surprised .eye {
    height: 85px;
    width: 65px;
    border-radius: 35px;
    background-color: #ffaa00;
    box-shadow: 0 0 20px rgba(255, 170, 0, 0.8);
    transform: translateY(-5px);
}'''

# Replace the previous .oled-face block in CSS
css_content = re.sub(r'\.oled-face \{.*?(?=\.camera-box \{)', css_new + '\n\n', css_content, flags=re.DOTALL)

with open(css_path, 'w', encoding='utf-8') as f:
    f.write(css_content)

print("Vector eyes applied!")
