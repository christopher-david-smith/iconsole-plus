import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Optional, Union

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak_retry_connector import establish_connection

from .codec import ProtocolCodec
from .models import TelemetryData

_LOGGER = logging.getLogger(__name__)


class IConsolePlusClient:
    SERVICE_UUID = "49535343-fe7d-4ae5-8fa9-9fafd205e455"
    CHARACTERISTIC_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"

    def __init__(self, device_or_address: Union[str, BLEDevice]):
        if isinstance(device_or_address, BLEDevice):
            self.device = device_or_address
            self.address = device_or_address.address
        else:
            self.device = None
            self.address = device_or_address

        self._client: Optional[BleakClient] = None
        self._write_lock = asyncio.Lock()
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._queue: asyncio.Queue[TelemetryData] = asyncio.Queue()
        self._pending_responses: Dict[int, asyncio.Future[bytes]] = {}

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def connect(self, timeout: float = 10.0):
        if self.is_connected:
            return

        if not self.device:
            _LOGGER.debug("Scanning for device %s", self.address)
            # Try to find the device by address
            self.device = await BleakScanner.find_device_by_address(
                self.address, timeout=timeout
            )

            if not self.device:
                _LOGGER.debug(
                    "Device %s not found by address, attempting name-based scan",
                    self.address,
                )
                # Fallback: name-based scan for "iConsole"
                self.device = await BleakScanner.find_device_by_filter(
                    lambda d, ad: "iConsole" in (d.name or ""), timeout=timeout
                )

            if not self.device:
                raise Exception(
                    f"IConsolePlusClient: Device {self.address} not found after scanning"
                )

        _LOGGER.debug("Connecting to %s", self.address)
        self._client = await establish_connection(
            BleakClient,
            self.device,
            self.device.name or self.address,
            disconnected_callback=self._on_disconnected,
        )

    async def disconnect(self):
        if self._client:
            await self._client.disconnect()
            self._client = None

    def _on_disconnected(self, client: BleakClient):
        _LOGGER.debug("Disconnected from %s", self.address)
        self._client = None
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        # Wake up any waiting iterator
        self._queue.put_nowait(None)
        # Fail any pending responses
        for fut in self._pending_responses.values():
            if not fut.done():
                fut.set_exception(
                    Exception(
                        "IConsolePlusClient: Disconnected from bike during operation"
                    )
                )

    async def _write(self, data: bytes):
        if not self.is_connected:
            raise Exception("IConsolePlusClient: Not connected to the bike")
        async with self._write_lock:
            _LOGGER.debug("Writing GATT: %s", data.hex("-").upper())
            await self._client.write_gatt_char(
                self.CHARACTERISTIC_UUID, data, response=False
            )

    async def _handshake(self):
        _LOGGER.debug("Starting handshake sequence")
        # Strictly follow the 0.5s delay from live_dashboard.py
        await self._write(ProtocolCodec.encode_ping())
        await asyncio.sleep(0.5)
        await self._write(ProtocolCodec.encode_manual_mode())
        await asyncio.sleep(0.5)
        # Setting an initial level settles the console state
        await self._write(ProtocolCodec.encode_set_level(1))
        await asyncio.sleep(0.5)
        await self._write(ProtocolCodec.encode_init_packet())
        await asyncio.sleep(0.5)

    async def _heartbeat_loop(self):
        _LOGGER.debug("Starting heartbeat loop")
        try:
            # Give the console a moment to settle after handshake
            await asyncio.sleep(1.0)
            while True:
                await self._write(ProtocolCodec.encode_heartbeat())
                await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            _LOGGER.debug("Heartbeat loop stopped")
        except Exception as e:
            _LOGGER.error("Heartbeat loop error: %s", e)

    def _notification_handler(self, sender, data: bytes):
        _LOGGER.debug("Received GATT notification: %s", data.hex("-").upper())
        if data.startswith(b"\xf0\xb2"):
            metrics = ProtocolCodec.decode_telemetry(data)
            if metrics:
                self._queue.put_nowait(metrics)
        elif data.startswith(b"\xf0\xb6"):
            # Resistance ACK (F0 B6 01 01 LV CS)
            if 0xB6 in self._pending_responses:
                fut = self._pending_responses.pop(0xB6)
                if not fut.done():
                    fut.set_result(data)

    async def set_resistance(self, level: int, timeout: float = 3.0):
        if not (1 <= level <= 32):
            raise ValueError(
                "IConsolePlusClient: Resistance level must be between 1 and 32"
            )

        fut = asyncio.get_running_loop().create_future()
        self._pending_responses[0xB6] = fut

        try:
            await self._write(ProtocolCodec.encode_set_level(level))
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            if 0xB6 in self._pending_responses:
                self._pending_responses.pop(0xB6)
            # Re-wrap timeout for better message if needed, but let caller decide
            raise
        except Exception:
            if 0xB6 in self._pending_responses:
                self._pending_responses.pop(0xB6)
            raise

    async def start_workout(self):
        """Send the start workout command with wakeup sequence."""
        await self._write(ProtocolCodec.encode_ping())
        await asyncio.sleep(0.5)
        await self._write(ProtocolCodec.encode_start())

    async def reset_workout(self):
        """Reset the workout session and start fresh."""
        await self._write(ProtocolCodec.encode_init_packet())
        await asyncio.sleep(0.5)
        await self._write(ProtocolCodec.encode_start())

    async def stop_workout(self):
        """Send the stop workout command."""
        await self._write(ProtocolCodec.encode_stop())

    @asynccontextmanager
    async def session(self) -> AsyncIterator["IConsolePlusClient"]:
        if not self.is_connected:
            await self.connect()

        # Clear queue of any stale signals from previous connection attempts
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        await self._client.start_notify(
            self.CHARACTERISTIC_UUID, self._notification_handler
        )
        await self._handshake()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        try:
            yield self
        finally:
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
                try:
                    await self._heartbeat_task
                except asyncio.CancelledError:
                    pass

            if self.is_connected:
                try:
                    await self._write(ProtocolCodec.encode_stop())
                    await self._client.stop_notify(self.CHARACTERISTIC_UUID)
                except Exception as e:
                    _LOGGER.debug("Cleanup warning: %s", e)

            # Clear queue
            while not self._queue.empty():
                self._queue.get_nowait()

            # Clear pending
            for fut in self._pending_responses.values():
                if not fut.done():
                    fut.cancel()
            self._pending_responses.clear()

            await self.disconnect()

    def __aiter__(self) -> AsyncIterator[TelemetryData]:
        return self

    async def __anext__(self) -> TelemetryData:
        data = await self._queue.get()
        if data is None:  # Disconnect signal
            raise StopAsyncIteration
        return data
