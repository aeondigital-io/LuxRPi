#!/usr/bin/env python3
"""
ADXL345 Accelerometer Reader for Raspberry Pi 5
Uses I2C via the smbus2 library (no heavy dependencies).

Install dependency:
    pip install smbus2

Hardware wiring (Raspberry Pi 5 — 40-pin header):
    ADXL345 VCC  → Pin 1  (3.3V)       ** Use 3.3V only, NOT 5V **
    ADXL345 GND  → Pin 6  (GND)
    ADXL345 SDA  → Pin 3  (GPIO2 / I2C1 SDA)
    ADXL345 SCL  → Pin 5  (GPIO3 / I2C1 SCL)
    ADXL345 SDO  → GND    (sets I2C address to 0x53)
                or 3.3V   (sets I2C address to 0x1D)
    ADXL345 CS   → 3.3V   (selects I2C mode)

Enable I2C on Raspberry Pi:
    sudo raspi-config → Interface Options → I2C → Enable
    OR add 'dtparam=i2c_arm=on' to /boot/firmware/config.txt and reboot

Verify the sensor is detected:
    sudo i2cdetect -y 1
    (should show 0x53 or 0x1D)
"""

import time
import sys
import struct

try:
    import smbus2
except ImportError:
    sys.exit("smbus2 not found. Install it with:  pip install smbus2")


# ── ADXL345 I2C addresses ────────────────────────────────────────────────────
ADDR_LOW  = 0x53   # SDO pin → GND  (default)
ADDR_HIGH = 0x1D   # SDO pin → 3.3V

# ── ADXL345 Register map ─────────────────────────────────────────────────────
REG_DEVID        = 0x00   # Device ID (should read 0xE5)
REG_BW_RATE      = 0x2C   # Data rate and power mode
REG_POWER_CTL    = 0x2D   # Power-saving features control
REG_DATA_FORMAT  = 0x31   # Data format control
REG_DATAX0       = 0x32   # X-axis data 0 (LSB) — 6 bytes follow for X/Y/Z
REG_INT_ENABLE   = 0x2E   # Interrupt enable control

# ── Configuration values ─────────────────────────────────────────────────────
DEVID_EXPECTED   = 0xE5

# BW_RATE: normal power, 100 Hz output data rate
BW_RATE_100HZ    = 0x0A

# DATA_FORMAT: full resolution, ±16g range, right-justified
DATA_FORMAT_FULL = 0b00001011   # FULL_RES=1, range=11 (±16g)

# POWER_CTL: measurement mode on
POWER_CTL_MEAS   = 0x08

# Scale factor in full-resolution mode: 3.9 mg/LSB for all ranges
SCALE_MG_PER_LSB = 3.9e-3   # g per raw LSB
GRAVITY_MS2      = 9.80665   # m/s² per g


class ADXL345:
    """Driver for the ADXL345 3-axis accelerometer over I2C."""

    def __init__(self, bus: int = 1, address: int = ADDR_LOW):
        """
        Args:
            bus:     I2C bus number (1 for all modern Raspberry Pi models)
            address: I2C address — ADDR_LOW (0x53) or ADDR_HIGH (0x1D)
        """
        self.bus     = smbus2.SMBus(bus)
        self.address = address
        self._init_device()

    def _write(self, register: int, value: int) -> None:
        self.bus.write_byte_data(self.address, register, value)

    def _read_byte(self, register: int) -> int:
        return self.bus.read_byte_data(self.address, register)

    def _read_block(self, register: int, length: int) -> bytes:
        # Use read_i2c_block_data for a burst read (faster, atomic)
        return bytes(self.bus.read_i2c_block_data(self.address, register, length))

    def _init_device(self) -> None:
        """Verify device ID, then configure data rate, format, and power."""
        dev_id = self._read_byte(REG_DEVID)
        if dev_id != DEVID_EXPECTED:
            raise RuntimeError(
                f"ADXL345 not found at 0x{self.address:02X}. "
                f"Got device ID 0x{dev_id:02X}, expected 0x{DEVID_EXPECTED:02X}. "
                "Check wiring and I2C address."
            )

        self._write(REG_BW_RATE,     BW_RATE_100HZ)
        self._write(REG_DATA_FORMAT, DATA_FORMAT_FULL)
        self._write(REG_INT_ENABLE,  0x00)           # disable interrupts
        self._write(REG_POWER_CTL,   POWER_CTL_MEAS) # start measuring

    def read_raw(self) -> tuple[int, int, int]:
        """
        Read raw 16-bit signed integers for X, Y, Z axes.
        Returns: (x_raw, y_raw, z_raw)
        """
        data = self._read_block(REG_DATAX0, 6)
        # Six bytes: X_L, X_H, Y_L, Y_H, Z_L, Z_H — little-endian signed 16-bit
        x, y, z = struct.unpack_from("<3h", data)
        return x, y, z

    def read_g(self) -> tuple[float, float, float]:
        """
        Read acceleration in g (gravitational units).
        Returns: (ax_g, ay_g, az_g)
        """
        x, y, z = self.read_raw()
        return (
            x * SCALE_MG_PER_LSB,
            y * SCALE_MG_PER_LSB,
            z * SCALE_MG_PER_LSB,
        )

    def read_ms2(self) -> tuple[float, float, float]:
        """
        Read acceleration in m/s².
        Returns: (ax, ay, az) in m/s²
        """
        ax, ay, az = self.read_g()
        return ax * GRAVITY_MS2, ay * GRAVITY_MS2, az * GRAVITY_MS2

    def close(self) -> None:
        """Release the I2C bus."""
        self.bus.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def print_header() -> None:
    print(f"{'Time (s)':>10}  {'X (g)':>9}  {'Y (g)':>9}  {'Z (g)':>9}  "
          f"{'X (m/s²)':>10}  {'Y (m/s²)':>10}  {'Z (m/s²)':>10}")
    print("-" * 85)


def main():
    # ── Configuration ─────────────────────────────────────────────────────────
    I2C_BUS      = 1          # I2C bus (always 1 on RPi)
    I2C_ADDRESS  = ADDR_HIGH   # Change to ADDR_HIGH if SDO is tied to 3.3V
    SAMPLE_RATE  = 10         # Readings per second
    # ─────────────────────────────────────────────────────────────────────────

    interval = 1.0 / SAMPLE_RATE

    print("ADXL345 Accelerometer — Raspberry Pi 5")
    print(f"I2C bus {I2C_BUS}, address 0x{I2C_ADDRESS:02X}, {SAMPLE_RATE} Hz\n")

    try:
        with ADXL345(bus=I2C_BUS, address=I2C_ADDRESS) as sensor:
            print_header()
            t0 = time.monotonic()

            while True:
                loop_start = time.monotonic()

                ax_g,  ay_g,  az_g  = sensor.read_g()
                ax_ms, ay_ms, az_ms = (v * GRAVITY_MS2 for v in (ax_g, ay_g, az_g))
                elapsed = loop_start - t0

                print(
                    f"{elapsed:>10.2f}  "
                    f"{ax_g:>+9.4f}  {ay_g:>+9.4f}  {az_g:>+9.4f}  "
                    f"{ax_ms:>+10.4f}  {ay_ms:>+10.4f}  {az_ms:>+10.4f}"
                )

                # Precise sleep to maintain sample rate
                elapsed_loop = time.monotonic() - loop_start
                sleep_time = interval - elapsed_loop
                if sleep_time > 0:
                    time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\nStopped.")
    except RuntimeError as e:
        print(f"\nError: {e}")
        sys.exit(1)
    except PermissionError:
        print("\nPermission denied opening I2C bus.")
        print("Add your user to the i2c group:  sudo usermod -aG i2c $USER")
        print("Then log out and back in.")
        sys.exit(1)


if __name__ == "__main__":
    main()