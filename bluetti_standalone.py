#!/usr/bin/env python3
"""
Standalone Bluetti AC500 implementation - no bluetti_mqtt dependency
Compatible with latest bleak version
"""

import asyncio
import logging
import struct
import threading as _threading
from enum import Enum, unique
from bleak import BleakClient
import crcmod.predefined

modbus_crc = crcmod.predefined.mkCrcFun('modbus')

@unique
class OutputMode(Enum):
    STOP = 0
    INVERTER_OUTPUT = 1
    BYPASS_OUTPUT_C = 2
    BYPASS_OUTPUT_D = 3
    LOAD_MATCHING = 4

@unique
class UpsMode(Enum):
    CUSTOMIZED = 1
    PV_PRIORITY = 2
    STANDARD = 3
    TIME_CONTROL = 4

@unique
class AutoSleepMode(Enum):
    THIRTY_SECONDS = 2
    ONE_MINUTE = 3
    FIVE_MINUTES = 4
    NEVER = 5

SERVICE_UUID = "0000ff00-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"
DEVICE_NAME_UUID = "00002a00-0000-1000-8000-00805f9b34fb"

class ModbusCommand:

    def __init__(self, function_code, data):
        self.function_code = function_code
        self.cmd = bytearray(len(data) + 4)
        self.cmd[0] = 1
        self.cmd[1] = function_code
        self.cmd[2:-2] = data
        struct.pack_into('<H', self.cmd, -2, modbus_crc(self.cmd[:-2]))

    def encode(self):
        return bytes(self.cmd)

    def parse_response(self, response):
        if len(response) < 3:
            return b''
        return response[3:-2]

    def is_valid_response(self, response):
        if len(response) < 3:
            return False
        crc = modbus_crc(response[:-2])
        crc_bytes = crc.to_bytes(2, byteorder='little')
        return response[-2:] == crc_bytes

class ReadHoldingRegisters(ModbusCommand):

    def __init__(self, starting_address, quantity):
        self.starting_address = starting_address
        self.quantity = quantity
        super().__init__(3, struct.pack('!HH', starting_address, quantity))

    def __repr__(self):
        return f'ReadHoldingRegisters(starting_address={self.starting_address}, quantity={self.quantity})'

class WriteSingleRegister(ModbusCommand):

    def __init__(self, address, value):
        self.address = address
        self.value = value
        super().__init__(6, struct.pack('!HH', address, value))

    def __repr__(self):
        return f'WriteSingleRegister(address={self.address}, value={self.value})'

class StandaloneBluettiClient:

    def __init__(self, mac_address, logger=None):
        self.mac_address = mac_address
        self.logger = logger or logging.getLogger(__name__)
        self.client = None
        self.is_ready = False
        self._response_event = asyncio.Event()
        self._response_data = None

        self.polling_commands = [
            ReadHoldingRegisters(10, 40),
            ReadHoldingRegisters(70, 21),
            ReadHoldingRegisters(3001, 61),
        ]

        self.pack_polling_commands = [
            ReadHoldingRegisters(91, 37)
        ]

        self.fields = {}

    async def connect(self):
        try:
            self.client = BleakClient(self.mac_address)
            await self.client.connect()

            await self.client.start_notify(
                NOTIFY_UUID,
                self._notification_handler
            )

            self.is_ready = True
            self.logger.info(f"Connected to Bluetti device: {self.mac_address}")

            try:
                name_bytes = await self.client.read_gatt_char(DEVICE_NAME_UUID)
                device_name = name_bytes.decode('ascii')
                self.logger.info(f"Device name: {device_name}")
            except Exception as e:
                self.logger.debug(f"Could not read device name: {e}")

            return True

        except Exception as e:
            self.logger.error(f"Connection failed: {e}")
            self.is_ready = False
            return False

    async def disconnect(self):
        try:
            if self.client and self.client.is_connected:
                try:
                    await self.client.stop_notify(NOTIFY_UUID)
                    self.logger.info("BLE notifications unsubscribed")
                except Exception as e:
                    self.logger.debug(f"Could not stop notifications (may already be stopped): {e}")
                await self.client.disconnect()
            self.is_ready = False
            self.logger.info("Disconnected from Bluetti device")
        except Exception as e:
            self.logger.error(f"Disconnect error: {e}")
            self.is_ready = False

    def _notification_handler(self, sender, data):
        self._response_data = data
        self._response_event.set()

    async def perform_command(self, command):
        if not self.is_ready or not self.client:
            return None

        try:
            self._response_event.clear()
            self._response_data = None

            command_bytes = command.encode()
            await self.client.write_gatt_char(WRITE_UUID, command_bytes)

            try:
                await asyncio.wait_for(self._response_event.wait(), timeout=10.0)
                return self._response_data
            except asyncio.TimeoutError:
                self.logger.warning(f"Timeout waiting for response to {command}")
                return None

        except Exception as e:
            self.logger.error(f"Error performing command {command}: {e}")
            return None

    async def poll_all_data(self):
        if not self.is_ready:
            return {}

        try:
            self.fields.clear()

            for command in self.polling_commands:
                try:
                    response = await self.perform_command(command)
                    if response:
                        payload = command.parse_response(response)
                        if payload:
                            parsed_data = self._parse_data_segment(payload, command.starting_address)
                            self.fields.update(parsed_data)
                except Exception as e:
                    self.logger.error(f"Error polling command {command}: {e}")

            for pack_idx in range(1, 7):
                try:
                    pack_selector = WriteSingleRegister(3006, pack_idx)
                    select_response = await self.perform_command(pack_selector)
                    if select_response:
                        await asyncio.sleep(1.0)

                        for pack_cmd in self.pack_polling_commands:
                            response = await self.perform_command(pack_cmd)
                            if response:
                                payload = pack_cmd.parse_response(response)
                                if payload:
                                    pack_data = self._parse_data_segment(payload, pack_cmd.starting_address)
                                    for key, value in pack_data.items():
                                        if key == 'current_pack_total_voltage':
                                            self.fields[f'pack_{pack_idx}_total_voltage'] = value
                                        elif key == 'current_pack_voltage':
                                            self.fields[f'pack_{pack_idx}_pack_voltage'] = value
                                        elif key == 'current_pack_battery_percent':
                                            self.fields[f'pack_{pack_idx}_battery_percent'] = value
                                        elif key == 'pack_num_max_bms' and key not in self.fields:
                                            self.fields[key] = value

                except Exception as e:
                    self.logger.debug(f"Error polling pack {pack_idx}: {e}")

            return dict(self.fields)

        except Exception as e:
            self.logger.error(f"Poll error: {e}")
            return {}

    async def send_command(self, register, value):
        try:
            if not self.is_ready:
                return False

            command = WriteSingleRegister(register, value)
            response = await self.perform_command(command)
            return response is not None

        except Exception as e:
            self.logger.error(f"Send command error: {e}")
            return False

    def _parse_data_segment(self, payload_bytes, starting_address):
        segment_fields = {}

        try:
            if not payload_bytes or len(payload_bytes) < 2:
                return segment_fields

            num_registers = len(payload_bytes) // 2
            values = struct.unpack(f'>{num_registers}H', payload_bytes)

            if starting_address == 10:
                if num_registers >= 40:
                    device_type_chars = []
                    for i in range(6):
                        val = values[i]
                        if val != 0:
                            device_type_chars.append(chr((val >> 8) & 0xFF))
                            device_type_chars.append(chr(val & 0xFF))
                    segment_fields['device_type'] = ''.join(device_type_chars).strip('\x00')

                    serial_high = (values[7] << 32) | (values[8] << 16) | values[9]
                    serial_low = (values[10] << 16) | values[11]
                    segment_fields['serial_number'] = (serial_high << 16) | serial_low

                    segment_fields['arm_version'] = f"{values[13] >> 8}.{values[13] & 0xFF}"
                    segment_fields['dsp_version'] = f"{values[15] >> 8}.{values[15] & 0xFF}"

                    segment_fields['dc_input_power'] = values[26]
                    segment_fields['ac_input_power'] = values[27]
                    segment_fields['ac_output_power'] = values[28]
                    segment_fields['dc_output_power'] = values[29]
                    segment_fields['power_generation'] = values[31] / 10.0
                    segment_fields['total_battery_percent'] = values[33]
                    segment_fields['ac_output_on'] = bool(values[38])
                    segment_fields['dc_output_on'] = bool(values[39])

            elif starting_address == 70:
                if num_registers >= 21:
                    segment_fields['ac_output_mode'] = values[0]
                    segment_fields['internal_ac_voltage'] = values[1] / 10.0
                    segment_fields['internal_current_one'] = values[2] / 10.0
                    segment_fields['internal_power_one'] = values[3]
                    segment_fields['internal_ac_frequency'] = values[4] / 100.0
                    segment_fields['internal_current_two'] = values[5] / 10.0
                    segment_fields['internal_power_two'] = values[6]
                    segment_fields['ac_input_voltage'] = values[7] / 10.0
                    segment_fields['internal_current_three'] = values[8] / 10.0
                    segment_fields['internal_power_three'] = values[9]
                    segment_fields['ac_input_frequency'] = values[10] / 100.0
                    segment_fields['internal_dc_input_voltage'] = values[16] / 10.0
                    segment_fields['internal_dc_input_power'] = values[17]
                    segment_fields['internal_dc_input_current'] = values[18] / 10.0
                    segment_fields['ac_charging_power'] = values[19]

            elif starting_address == 3001:
                if num_registers >= 6:
                    segment_fields['ups_mode'] = values[0]
                    segment_fields['split_phase_on'] = bool(values[3])
                    segment_fields['pack_num_configured'] = values[5]

                if num_registers >= 11:
                    segment_fields['ac_output_on'] = bool(values[6])
                    segment_fields['dc_output_on'] = bool(values[7])
                    segment_fields['grid_charge_on'] = bool(values[10])

                if num_registers >= 16:
                    segment_fields['time_control_on'] = bool(values[12])
                    segment_fields['battery_range_start'] = values[14]
                    segment_fields['battery_range_end'] = values[15]

                if num_registers >= 36:
                    segment_fields['bluetooth_connected'] = bool(values[35])

                if num_registers >= 56:
                    time_control_data = {}
                    for i in range(18):
                        reg_addr = 3039 + i
                        reg_index = 38 + i
                        time_control_data[f'time_control_reg_{reg_addr}'] = values[reg_index]
                    segment_fields['time_control_programming'] = time_control_data

                if num_registers >= 61:
                    segment_fields['auto_sleep_mode'] = values[60]

            elif starting_address == 91:
                if num_registers >= 9:
                    segment_fields['pack_num_max_bms'] = values[0]
                    segment_fields['current_pack_total_voltage'] = values[1] / 10.0
                    segment_fields['current_pack_voltage'] = values[7] / 100.0
                    segment_fields['current_pack_battery_percent'] = values[8]

        except Exception as e:
            self.logger.error(f"Error parsing segment addr {starting_address}: {e}")

        return segment_fields


class SyncBluettiClient:

    def __init__(self, mac_address, logger=None):
        self.mac_address = mac_address
        self.logger = logger or logging.getLogger(__name__)
        self.client = None
        self.loop = None
        self.loop_thread = None
        self.connected = False

    def start(self):
        self.loop = asyncio.new_event_loop()
        self.loop_thread = _threading.Thread(name="BluettiAsyncLoop", target=self.loop.run_forever, daemon=True)
        self.loop_thread.start()

    def stop(self):
        if self.connected and self.loop and not self.loop.is_closed():
            self.disconnect()

        if self.loop and self.loop_thread and self.loop_thread.is_alive():
            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
                self.loop_thread.join(timeout=10)

                if self.loop_thread.is_alive():
                    try:
                        if not self.loop.is_closed():
                            pending = asyncio.all_tasks(self.loop)
                            for task in pending:
                                self.loop.call_soon_threadsafe(task.cancel)
                            self.loop_thread.join(timeout=5)
                    except Exception:
                        pass

                if self.loop_thread.is_alive():
                    self.logger.error(f"Asyncio loop thread '{self.loop_thread.name}' did not terminate - Domoticz may abort")

            except Exception as e:
                self.logger.error(f"Error during loop cleanup: {e}")
            finally:
                self.loop = None
                self.loop_thread = None
                self.connected = False

        self._force_disconnect_bluez()

    def connect(self):
        if not self.loop:
            return False

        async def _connect():
            self.client = StandaloneBluettiClient(self.mac_address, self.logger)
            return await self.client.connect()

        future = asyncio.run_coroutine_threadsafe(_connect(), self.loop)
        try:
            result = future.result(timeout=30)
            self.connected = result
            return result
        except Exception as e:
            self.logger.error(f"Connection failed: {e}")
            return False

    def disconnect(self):
        if not self.loop or not self.client:
            return

        async def _disconnect():
            await self.client.disconnect()

        future = asyncio.run_coroutine_threadsafe(_disconnect(), self.loop)
        try:
            future.result(timeout=10)
            self.connected = False
            self.logger.info("BLE disconnect completed cleanly")
        except Exception as e:
            self.logger.error(f"Graceful BLE disconnect failed: {e}")
            self.connected = False
            self._force_disconnect_bluez()

    def _force_disconnect_bluez(self):
        import subprocess
        try:
            self.logger.warning(f"Forcing BlueZ disconnect for {self.mac_address}")
            result = subprocess.run(
                ["bluetoothctl", "disconnect", self.mac_address],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                self.logger.info(f"BlueZ force disconnect succeeded: {result.stdout.strip()}")
            else:
                self.logger.error(f"BlueZ force disconnect failed: {result.stderr.strip()}")
        except Exception as e:
            self.logger.error(f"BlueZ force disconnect error: {e}")

    def poll_data(self):
        if not self.loop or not self.client:
            return {}

        future = asyncio.run_coroutine_threadsafe(self.client.poll_all_data(), self.loop)
        try:
            return future.result(timeout=30)
        except Exception as e:
            self.logger.error(f"Poll failed: {e}")
            return {}

    def send_command(self, register, value):
        if not self.loop or not self.client:
            return False

        future = asyncio.run_coroutine_threadsafe(self.client.send_command(register, value), self.loop)
        try:
            return future.result(timeout=10)
        except Exception as e:
            self.logger.error(f"Command failed: {e}")
            return False


def create_client(mac_address, logger=None):
    return SyncBluettiClient(mac_address, logger)
