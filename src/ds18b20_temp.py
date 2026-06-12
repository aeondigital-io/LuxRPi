#!/usr/bin/env python3
"""
DS18B20 (Dallas 1-Wire) Temperature Sensor Reader
Requires Linux kernel modules: w1-gpio, w1-therm

Hardware setup (Raspberry Pi / similar SBC):
  - VDD  → 3.3V or 5V
  - GND  → GND
  - DATA → GPIO4 (default) with a 4.7kΩ pull-up resistor to VDD

Enable 1-Wire on Raspberry Pi:
  Add 'dtoverlay=w1-gpio' to /boot/config.txt and reboot,
  OR run: sudo modprobe w1-gpio && sudo modprobe w1-therm
"""

import glob
import time
import sys

# Base path for 1-Wire devices exposed by the Linux kernel
W1_BASE_PATH = "/sys/bus/w1/devices/"
# DS18B20 family code is 28-xxxx; DS18S20 is 10-xxxx
SENSOR_GLOB = W1_BASE_PATH + "28-*/w1_slave"


def find_sensors() -> list[str]:
    """Return paths to all detected DS18B20 sensor files."""
    sensors = glob.glob(SENSOR_GLOB)
    # Also check for DS18S20 (family code 10)
    sensors += glob.glob(W1_BASE_PATH + "10-*/w1_slave")
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

    # Line 1 ends with 'YES' if CRC is valid
    if len(lines) < 2 or "YES" not in lines[0]:
        return None

    # Line 2 contains 't=<millidegrees_C>'
    temp_str = lines[1].strip()
    t_index = temp_str.find("t=")
    if t_index == -1:
        return None

    millidegrees = int(temp_str[t_index + 2:])
    return millidegrees / 1000.0


def celsius_to_fahrenheit(celsius: float) -> float:
    return celsius * 9.0 / 5.0 + 32.0


def sensor_id(sensor_path: str) -> str:
    """Extract the sensor's unique ID from its path."""
    # e.g. /sys/bus/w1/devices/28-0123456789ab/w1_slave → 28-0123456789ab
    parts = sensor_path.split("/")
    return parts[-2]


def main():
    sensors = find_sensors()

    if not sensors:
        print("No DS18B20 sensors found.")
        print("Make sure the w1-gpio and w1-therm kernel modules are loaded:")
        print("  sudo modprobe w1-gpio")
        print("  sudo modprobe w1-therm")
        sys.exit(1)

    print(f"Found {len(sensors)} sensor(s).\n")

    while True:
        for sensor_path in sensors:
            sid = sensor_id(sensor_path)
            try:
                temp_c = parse_temperature(sensor_path)
                if temp_c is None:
                    print(f"[{sid}] CRC check failed — retrying next cycle.")
                else:
                    temp_f = celsius_to_fahrenheit(temp_c)
                    print(f"[{sid}]  {temp_c:.3f} °C  /  {temp_f:.3f} °F")
            except FileNotFoundError:
                print(f"[{sid}] Sensor file not found. Was it disconnected?")
            except Exception as e:
                print(f"[{sid}] Error reading sensor: {e}")

        print()  # blank line between readings
        try:
            time.sleep(2)
        except KeyboardInterrupt:
            print("Stopped.")
            sys.exit(0)


if __name__ == "__main__":
    main()