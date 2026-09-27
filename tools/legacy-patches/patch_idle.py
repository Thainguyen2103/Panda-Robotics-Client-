import os
import re

css_path = 'web/public/style.css'
with open(css_path, 'r', encoding='utf-8') as f:
    css_content = f.read()

# Them keyframes vao cuoi file
keyframes = '''
/* Hieu ung Idle (Tho va Chop mat) */
@keyframes idle-breathe {
    0%, 100% { transform: translateY(0px); height: 70px; }
    15% { transform: translateY(0px); height: 70px; }
    17% { transform: translateY(2px); height: 5px; } /* Chop mat 1 */
    19% { transform: translateY(0px); height: 70px; }
    50% { transform: translateY(4px); height: 66px; } /* Tho xuong */
    65% { transform: translateY(4px); height: 66px; }
    67% { transform: translateY(2px); height: 5px; } /* Chop mat 2 */
    69% { transform: translateY(4px); height: 66px; }
}

.oled-face.neutral .eye {
    animation: idle-breathe 7s infinite ease-in-out;
}
'''

if "@keyframes idle-breathe" not in css_content:
    with open(css_path, 'a', encoding='utf-8') as f:
        f.write(keyframes)
    print("Idle animation added!")
else:
    print("Animation already exists.")
