import paho.mqtt.client as mqtt
import json
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import settings

client = mqtt.Client()


def _json_default(value):
    """Convert NumPy-style scalar values without coupling MQTT to NumPy."""
    item = getattr(value,"item",None)
    if callable(item):
        return item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

def connect():
    try:
        client.connect(settings.MQTT_BROKER, settings.MQTT_PORT, 60)
        client.loop_start() # Start background thread for MQTT
        print("🔗 [MQTT BRIDGE] Connected to broker")
    except Exception as e:
        print(f"❌ [MQTT BRIDGE] Connection failed: {e}")

def publish(topic, payload, retain=False):
    try:
        if isinstance(payload, dict):
            payload = json.dumps(payload,default=_json_default)
        client.publish(topic, str(payload), retain=retain)
        # print(f"↗️ [PUBLISH] {topic}: {payload}")
    except Exception as e:
        print(f"❌ [MQTT BRIDGE] Publish failed: {e}")

# Automatically connect when imported
connect()
