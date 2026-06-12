#!/usr/bin/env python3
"""
DS18B20 MQTT Publisher Microservice

Queries 1-Wire temperature sensors on a regular interval and publishes
readings to an MQTT topic using serialized Protobuf messages.

Configuration can be set via environment variables.
"""

import os
import sys
import glob
import time
import signal
import logging
import paho.mqtt.client as mqtt

# Import the generated protobuf modules
from protos import telemetry_pb2
from protos import wrapper_pb2

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("ds18b20_mqtt")

# Environment configuration
W1_BASE_PATH = os.environ.get("W1_BASE_PATH", "/sys/bus/w1/devices/")
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "10.0"))

MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_TOPIC_PREFIX = os.environ.get("MQTT_TOPIC_PREFIX", "sensors/temperature")
MQTT_CLIENT_ID = os.environ.get("MQTT_CLIENT_ID", "ds18b20_publisher")
MQTT_USERNAME = os.environ.get("MQTT_USERNAME", None)
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", None)
MQTT_KEEPALIVE = int(os.environ.get("MQTT_KEEPALIVE", "60"))

# Flag to control the main loop
running = True


def handle_signals(signum, frame):
    """Graceful shutdown handler."""
    global running
    logger.info(f"Received shutdown signal ({signum}). Exiting...")
    running = False


# Register signal handlers for graceful exit
signal.signal(signal.SIGINT, handle_signals)
signal.signal(signal.SIGTERM, handle_signals)


def find_sensors() -> list[str]:
    """Return paths to all detected DS18B20/DS18S20 sensor files."""
    sensors = glob.glob(os.path.join(W1_BASE_PATH, "28-*/w1_slave"))
    sensors += glob.glob(os.path.join(W1_BASE_PATH, "10-*/w1_slave"))
    return sensors


def read_raw(sensor_path: str) -> list[str]:
    """Read the raw lines from the sensor's w1_slave file."""
    with open(sensor_path, "r") as f:
        return f.readlines()


def parse_temperature(sensor_path: str) -> float | None:
    """
    Parse temperature (°C) from a w1_slave file.
    Returns None if the CRC check fails or data is malformed.
    """
    lines = read_raw(sensor_path)

    if len(lines) < 2 or "YES" not in lines[0]:
        return None

    temp_str = lines[1].strip()
    t_index = temp_str.find("t=")
    if t_index == -1:
        return None

    try:
        millidegrees = int(temp_str[t_index + 2:])
        return millidegrees / 1000.0
    except ValueError:
        return None


def create_telemetry_payload(sensor_id: str, temperature: float) -> bytes:
    """
    Creates a serialized MessageWrapper containing TemperatureTelemetry.
    """
    # 1. Create the Telemetry message
    telemetry = telemetry_pb2.TemperatureTelemetry()
    telemetry.sensor_id = sensor_id
    telemetry.temperature_celsius = temperature

    # 2. Create the Wrapper message
    wrapper = wrapper_pb2.MessageWrapper()
    wrapper.timestamp_ms = int(time.time() * 1000)
    wrapper.source_service = "ds18b20_sensor"
    
    # 3. Populate the 'oneof' field in the wrapper
    wrapper.temp_tlm.CopyFrom(telemetry)

    # 4. Serialize to bytes for MQTT transmission
    return wrapper.SerializeToString()


def sensor_id(sensor_path: str) -> str:
    """Extract the sensor's unique ID from its path."""
    parts = sensor_path.strip("/").split("/")
    if len(parts) >= 2:
        return parts[-2]
    return "unknown"


def on_connect(client, userdata, flags, rc, properties=None):
    """MQTT connection callback."""
    if isinstance(rc, int):
        conn_rc = rc
    else:
        conn_rc = getattr(rc, "value", rc)

    if conn_rc == 0:
        logger.info("Connected successfully to MQTT Broker.")
    else:
        logger.error(f"Failed to connect to MQTT Broker, return code {conn_rc}")


def on_disconnect(client, userdata, rc, properties=None):
    """MQTT disconnection callback."""
    logger.warning(f"Disconnected from MQTT Broker (reason code: {rc}). Retrying automatically...")


def main():
    logger.info("Starting DS18B20 MQTT Publisher Microservice...")
    logger.info(f"Targeting MQTT Broker: {MQTT_BROKER}:{MQTT_PORT}")
    logger.info(f"Polling Interval: {POLL_INTERVAL} seconds")

    try:
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=MQTT_CLIENT_ID
        )
    except AttributeError:
        client = mqtt.Client(client_id=MQTT_CLIENT_ID)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    if MQTT_USERNAME or MQTT_PASSWORD:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=MQTT_KEEPALIVE)
    except Exception as e:
        logger.error(f"Initial connection to broker failed: {e}. Reconnecting in loop...")

    client.loop_start()

    try:
        while running:
            sensors = find_sensors()
            if not sensors:
                logger.warning(f"No DS18B20 sensors found in {W1_BASE_PATH}")

            for sensor_path in sensors:
                sid = sensor_id(sensor_path)
                try:
                    temp_c = parse_temperature(sensor_path)
                    if temp_c is None:
                        logger.warning(f"[{sid}] CRC check failed or sensor data malformed.")
                        continue

                    # Construct Protobuf payload
                    payload_bytes = create_telemetry_payload(sid, temp_c)
                    topic = f"{MQTT_TOPIC_PREFIX}/{sid}"
                    
                    # Publish data (MQTT handles bytes natively)
                    result = client.publish(topic, payload_bytes, qos=1)
                    
                    if result.rc == mqtt.MQTT_ERR_SUCCESS:
                        logger.info(f"Published to {topic}: [{len(payload_bytes)} bytes protobuf]")
                    else:
                        logger.error(f"Failed to publish to {topic}, rc={result.rc}")

                except FileNotFoundError:
                    logger.error(f"[{sid}] Sensor file not found. Was it disconnected?")
                except Exception as e:
                    logger.error(f"[{sid}] Error reading sensor or publishing: {e}")

            slept = 0.0
            while running and slept < POLL_INTERVAL:
                time.sleep(0.5)
                slept += 0.5

    finally:
        logger.info("Stopping MQTT client loop...")
        client.loop_stop()
        logger.info("Disconnecting from MQTT Broker...")
        client.disconnect()
        logger.info("Microservice stopped cleanly.")


if __name__ == "__main__":
    main()