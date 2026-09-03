import os
import base64

def replace_in_file(filepath, old, new):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    content = content.replace(old, new)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

# 1. Update config/settings.py
replace_in_file('config/settings.py', 'TOPIC_VOICE_LOG = "panda/log/voice"', 'TOPIC_VOICE_LOG = "panda/log/voice"\nTOPIC_CAMERA = "panda/camera"')

# 2. Update server/vision.py
vision_add_import = "import base64\nimport server.mqtt_bridge as mqtt_bridge\n"
replace_in_file('server/vision.py', 'import sys', vision_add_import + 'import sys')

vision_old_loop = '''        if frame_count % 3 == 0:
            person_detected = False
            
            if model and frame is not None:'''

vision_new_loop = '''        if frame is not None:
            # Stream camera to web dashboard
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
            b64_str = base64.b64encode(buffer).decode('utf-8')
            mqtt_bridge.publish(settings.TOPIC_CAMERA, b64_str)

        if frame_count % 3 == 0:
            person_detected = False
            
            if model and frame is not None:'''
replace_in_file('server/vision.py', vision_old_loop, vision_new_loop)

# 3. Update web/server.js
replace_in_file('web/server.js', "mqttClient.subscribe('panda/log/voice');", "mqttClient.subscribe('panda/log/voice');\n    mqttClient.subscribe('panda/camera');")

# 4. Update index.html
html_old = '''                    <div class="camera-box">
                        <div class="scanline"></div>
                        <div class="cam-content">
                            <span class="cam-no-signal">🔴 NO SIGNAL</span>
                            <span class="cam-mock">[Mock Mode]</span>
                        </div>
                    </div>'''
html_new = '''                    <div class="camera-box" style="padding: 0;">
                        <div class="scanline"></div>
                        <img id="cam-image" src="" alt="Camera Feed" style="width:100%; height:100%; object-fit:cover; display:none; position:absolute; top:0; left:0; z-index:0;" />
                        <div class="cam-content" id="cam-placeholder">
                            <span class="cam-no-signal">🔴 NO SIGNAL</span>
                            <span class="cam-mock">[Waiting for stream...]</span>
                        </div>
                    </div>'''
replace_in_file('web/public/index.html', html_old, html_new)

# 5. Update app.js
appjs_old = "    } else if (topic === 'panda/cmd/face') {"
appjs_new = '''    } else if (topic === 'panda/camera') {
        const camImg = document.getElementById('cam-image');
        const camPlaceholder = document.getElementById('cam-placeholder');
        camImg.src = "data:image/jpeg;base64," + payload;
        camImg.style.display = 'block';
        if (camPlaceholder) camPlaceholder.style.display = 'none';
    } else if (topic === 'panda/cmd/face') {'''
replace_in_file('web/public/app.js', appjs_old, appjs_new)

print('Patch applied successfully')
