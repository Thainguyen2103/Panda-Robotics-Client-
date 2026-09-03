import paho.mqtt.client as mqtt
import json
import time
import threading
import random
import sys
import os

# Add config to path so we can import it
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import settings

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ [VIRTUAL ROBOT] Connected to MQTT Broker!")
        client.subscribe("panda/cmd/#")
        print("📡 [VIRTUAL ROBOT] Subscribed to panda/cmd/#")
    else:
        print(f"❌ [VIRTUAL ROBOT] Failed to connect, return code {rc}")

def on_message(client, userdata, msg):
    topic = msg.topic
    payload = msg.payload.decode()
    
    if topic == settings.TOPIC_MOVE:
        print(f"🚗 [MOTOR] {payload.upper()}")
    elif topic == settings.TOPIC_FACE:
        faces = {
            "happy": "😊", 
            "sad": "😢", 
            "angry": "😡", 
            "surprised": "😲", 
            "love": "😍", 
            "wink": "😉", 
            "sleepy": "😴", 
            "dizzy": "😵", 
            "cool": "😎", 
            "cute": "🥺", 
            "neutral": "😐"
        }
        print(f"👁️  [OLED] {faces.get(payload, payload)}")
    elif topic == settings.TOPIC_ARM:
        print(f"🦾 [SERVO] {payload}")
    elif topic == settings.TOPIC_TEXT:
        print(f"📺 [TEXT] {payload}")
    elif topic == settings.TOPIC_BUZZ:
        print(f"🔔 [BUZZ] {'BÍP!' if payload == 'on' else 'tắt'}")
    else:
        print(f"❓ [UNKNOWN] {topic}: {payload}")

def send_status(client):
    while True:
        dist = 45  # Safe default distance (cm)
        btn = 0   # Released
        
        status_data = {"dist": dist, "btn": btn}
        client.publish(settings.TOPIC_STATUS, json.dumps(status_data))
        time.sleep(0.5)

if __name__ == "__main__":
    print("🤖 [VIRTUAL ROBOT] Starting...")
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    
    try:
        client.connect(settings.MQTT_BROKER, settings.MQTT_PORT, 60)
    except ConnectionRefusedError:
        print(f"❌ [VIRTUAL ROBOT] Connection refused. Is Mosquitto running on {settings.MQTT_BROKER}:{settings.MQTT_PORT}?")
        sys.exit(1)
        
    status_thread = threading.Thread(target=send_status, args=(client,), daemon=True)
    status_thread.start()
    
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n🛑 [VIRTUAL ROBOT] Shutting down...")
        client.disconnect()
