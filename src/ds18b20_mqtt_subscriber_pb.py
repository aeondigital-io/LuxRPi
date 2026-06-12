#!/usr/bin/env python3
import datetime
import paho.mqtt.client as mqtt

# Import the generated protobuf module
from protos import wrapper_pb2

# Configuration - Match these with your publisher script
BROKER = "localhost" # Or your broker IP
PORT = 1883
TOPIC = "sensors/temperature/#" # The topic you are publishing to with wildcard for all sensors

def process_incoming_payload(payload_bytes):
    """
    Unpacks the MessageWrapper and prints temperature data to stdout.
    """
    try:
        # 1. Parse the raw bytes into the Wrapper object
        wrapper = wrapper_pb2.MessageWrapper()
        wrapper.ParseFromString(payload_bytes)

        # 2. Convert timestamp_ms (integer) to a readable datetime string
        dt = datetime.datetime.fromtimestamp(wrapper.timestamp_ms / 1000.0)
        readable_time = dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

        # 3. Check which part of the 'oneof' payload was received
        if wrapper.HasField('temp_tlm'):
            telemetry = wrapper.temp_tlm
            print(f"[{readable_time}] ID: {telemetry.sensor_id} | Temp: {telemetry.temperature_celsius:.2f}°C")
        else:
            print(f"[{readable_time}] Received unknown or empty payload type.")
            
    except Exception as e:
        print(f"[Error] Failed to parse protobuf message: {e}")

def on_connect(client, userdata, flags, rc, properties=None):
    # Handle older paho-mqtt versions vs newer v2 versions smoothly
    if isinstance(rc, int):
        conn_rc = rc
    else:
        conn_rc = getattr(rc, "value", rc)
        
    if conn_rc == 0:
        print(f"Connected successfully to {BROKER}")
        # Subscribed on connection
        client.subscribe(TOPIC)
        print(f"Subscribed to topic: {TOPIC}")
    else:
        print(f"Connection failed with code {conn_rc}")

def on_message(client, userdata, msg):
    # msg.payload is delivered natively as bytes, perfect for Protobuf
    process_incoming_payload(msg.payload)

def main():
    print("Starting DS18B20 Protobuf Subscriber...")
    
    # Initialize client (with v2 callback API support fallback like the publisher)
    try:
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()
        
    client.on_connect = on_connect
    client.on_message = on_message

    # Connect and loop
    try:
        print(f"Connecting to {BROKER}:{PORT}...")
        client.connect(BROKER, PORT, 60)
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nSubscriber stopped via KeyboardInterrupt.")
    except Exception as e:
        print(f"Connection error: {e}")

if __name__ == "__main__":
    main()