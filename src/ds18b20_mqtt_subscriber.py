import paho.mqtt.client as mqtt

# Configuration - Match these with your publisher script
BROKER = "localhost" # Or your broker IP
PORT = 1883
TOPIC = "sensors/temperature/#" # The topic you are publishing to with wildcard for all sensors

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"Connected successfully to {BROKER}")
        # Subscribed on connection
        client.subscribe(TOPIC)
        print(f"Subscribed to topic: {TOPIC}")
    else:
        print(f"Connection failed with code {rc}")

def on_message(client, userdata, msg):
    payload = str(msg.payload.decode("utf-8"))
    print(f"Received Temperature: {payload}")

# Initialize client
client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

# Connect and loop
try:
    print(f"Connecting to {BROKER}...")
    client.connect(BROKER, PORT, 60)
    client.loop_forever()
except KeyboardInterrupt:
    print("Subscriber stopped.")