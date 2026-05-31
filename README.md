# iconsole-plus

A Python library for interacting with iConsole+ exercise equipment (bikes, ellipticals) via Bluetooth Low Energy (BLE).

This library handles the specific iConsole+ protocol, including the required initialization handshake and heartbeat loop to keep the connection alive.

## Installation

```bash
uv add iconsole-plus
# or
pip install iconsole-plus
```

## Usage

The library provides an asynchronous client that manages the BLE connection and session state.

```python
import asyncio
from iconsole_plus.client import IConsolePlusClient

async def main():
    # Can be a MAC address or a bleak BLEDevice object
    address = "XX:XX:XX:XX:XX:XX"
    client = IConsolePlusClient(address)

    # The session context manager handles connect, handshake, 
    # heartbeat, and cleanup (stop/disconnect)
    async with client.session() as bike:
        print(f"Connected to {bike.address}")
        
        # Set resistance level (1-32)
        await bike.set_resistance(10)

        # The client is an async iterator that yields TelemetryData
        async for data in bike:
            print(f"Time: {data.duration_seconds}s")
            print(f"Speed: {data.speed_kmh} km/h")
            print(f"Cadence: {data.cadence_rpm} RPM")
            print(f"Power: {data.power_watts} W")
            print(f"Heart Rate: {data.heart_rate_bpm} BPM")
            
            if not data.is_running:
                print("Workout stopped")
                break

if __name__ == "__main__":
    asyncio.run(main())
```

## Features

- **Automatic Session Management**: Uses an async context manager to handle connection, handshake, and heartbeat.
- **Telemetry Streaming**: Real-time access to speed, power, distance, heart rate, cadence, and calories.
- **Resistance Control**: Easily set resistance levels from 1 to 32.
- **Robust Connection**: Built on `bleak` and `bleak-retry-connector` for reliable BLE communication.
- **Device Scanning**: Supports connecting via MAC address or `BLEDevice` objects.

## License

GNU General Public License v2.0
