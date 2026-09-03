import paho.mqtt.client as mqtt
import json
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import settings

client = mqtt.Client()

def connect():
    try:
        client.connect(settings.MQTT_BROKER, settings.MQTT_PORT, 60)
        client.loop_start() # Start background thread for MQTT
        print("🔗 [MQTT BRIDGE] Connected to broker")
    except Exception as e:
        print(f"❌ [MQTT BRIDGE] Connection failed: {e}")

def publish(topic, payload):
    try:
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        client.publish(topic, str(payload))
        # print(f"↗️ [PUBLISH] {topic}: {payload}")
    except Exception as e:
        print(f"❌ [MQTT BRIDGE] Publish failed: {e}")

# Automatically connect when imported
connect()
