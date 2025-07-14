# Ported and adapted from bluetti_mqtt/bluetooth/client.py

import asyncio
import logging
import threading
import time
from typing import Union
from bleak import BleakClient, BleakError
from .commands import DeviceCommand

class BluettiClient:
    WRITE_UUID = '0000ff02-0000-1000-8000-00805f9b34fb'
    NOTIFY_UUID = '0000ff01-0000-1000-8000-00805f9b34fb'

    def __init__(self, address: str, timeout: int = 10):
        self.address = address
        self.timeout = timeout
        self.client = BleakClient(address)
        self.lock = threading.Lock()
        self.notification_queue = asyncio.Queue()
        self.is_connected = False
        self.loop = None
        self.runner = None

    def _notification_handler(self, _sender: int, data: bytearray):
        self.loop.call_soon_threadsafe(self.notification_queue.put_nowait, data)

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    async def _connect(self):
        try:
            await self.client.connect(timeout=self.timeout)
            await self.client.start_notify(self.NOTIFY_UUID, self._notification_handler)
            self.is_connected = True
        except (BleakError, TimeoutError) as e:
            logging.error(f"Failed to connect to {self.address}: {e}")
            self.is_connected = False

    async def _disconnect(self):
        try:
            if self.client.is_connected:
                await self.client.stop_notify(self.NOTIFY_UUID)
                await self.client.disconnect()
        except BleakError as e:
            logging.error(f"Failed to disconnect from {self.address}: {e}")
        finally:
            self.is_connected = False

    async def _perform(self, command: DeviceCommand, timeout: int) -> Union[bytes, None]:
        await self.client.write_gatt_char(self.WRITE_UUID, bytes(command))

        response = bytearray()
        try:
            while True:
                data = await asyncio.wait_for(self.notification_queue.get(), timeout=timeout)
                response.extend(data)
                if len(response) >= command.response_size():
                    if command.is_valid_response(response):
                        return command.parse_response(response)
                    else:
                        logging.warning(f"Invalid response for command {command}: {response.hex()}")
                        return None
        except asyncio.TimeoutError:
            logging.warning(f"Timeout waiting for response to command {command}")
            return None

    def connect(self) -> bool:
        with self.lock:
            if self.is_connected:
                return True

            self.loop = asyncio.new_event_loop()
            self.runner = threading.Thread(target=self._run_loop, daemon=True)
            self.runner.start()

            future = asyncio.run_coroutine_threadsafe(self._connect(), self.loop)
            future.result(self.timeout)
            return self.is_connected

    def disconnect(self):
        with self.lock:
            if not self.is_connected or not self.loop:
                return

            future = asyncio.run_coroutine_threadsafe(self._disconnect(), self.loop)
            future.result(self.timeout)
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.runner.join()
            self.loop = None
            self.runner = None

    def perform(self, command: DeviceCommand, timeout: int = 10) -> Union[bytes, None]:
        with self.lock:
            if not self.is_connected or not self.loop:
                logging.error("Not connected, cannot perform command")
                return None

            future = asyncio.run_coroutine_threadsafe(self._perform(command, timeout), self.loop)
            try:
                return future.result(timeout)
            except (TimeoutError, asyncio.TimeoutError):
                logging.warning(f"Timeout performing command {command}")
                return None
            except Exception as e:
                logging.error(f"Error performing command {command}: {e}")
                self.disconnect()
                return None
