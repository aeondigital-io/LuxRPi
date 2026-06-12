import datetime
import time
from protos import telemetry_pb2
from protos import wrapper_pb2

def process_incoming_payload(payload_bytes):
    """
    Unpacks the MessageWrapper and prints temperature data to stdout.
    """
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

# Example usage/test:
if __name__ == "__main__":
    print("Testing un-packing logic...")
    # Manually creating a fake payload for testing purposes
    test_wrapper = wrapper_pb2.MessageWrapper()
    test_wrapper.timestamp_ms = int(time.time() * 1000)
    test_wrapper.source_service = "ds18b20_sensor"
    test_wrapper.temp_tlm.sensor_id = "TEST_SENSOR"
    test_wrapper.temp_tl1.temperature_celsius = 22.7
    
    fake_payload = test_wrapper.SerializeToString()
    process_incoming_payload(fake_payload)