# Domoticz-compatible wrapper for bluetti_mqtt library
# Uses the working bluetti_mqtt async code but provides synchronous interface

import asyncio
import threading
import queue
import time
import logging
from typing import Dict, Any, Optional

try:
    from bluetti_mqtt.bluetooth.client import BluetoothClient
    from bluetti_mqtt.core.devices.ac500 import AC500
    from bluetti_mqtt.core.commands import WriteSingleRegister
except ImportError:
    raise ImportError("bluetti_mqtt library not available. Install it first.")

class DomoticzBluettiWrapper:
    """Synchronous wrapper for bluetti_mqtt async library"""
    
    def __init__(self, mac_address: str, logger=None):
        self.mac_address = mac_address
        self.logger = logger or logging.getLogger(__name__)
        
        # Async components
        self.device = None
        self.ble_client = None
        self.client_task = None
        
        # Threading components
        self.loop = None
        self.loop_thread = None
        self.is_running = False
        self.command_queue = queue.Queue()
        self.result_queue = queue.Queue()
        
        # Connection state
        self.is_connected = False
        self.connection_timeout = 30.0
        
    def start(self):
        """Start the async event loop in a separate thread"""
        if self.is_running:
            return
            
        self.is_running = True
        self.loop_thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.loop_thread.start()
        
        # Wait a moment for the loop to start
        time.sleep(0.5)
    
    def stop(self):
        """Stop the event loop and thread"""
        if not self.is_running:
            return
            
        self.is_running = False
        
        # Send disconnect command
        try:
            self.command_queue.put({"action": "disconnect"}, timeout=1.0)
        except queue.Full:
            pass
            
        # Wait for thread to finish
        if self.loop_thread and self.loop_thread.is_alive():
            self.loop_thread.join(timeout=5.0)
    
    def _run_event_loop(self):
        """Run the async event loop in the thread"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        try:
            self.loop.run_until_complete(self._async_main())
        except Exception as e:
            self.logger.error(f"Event loop error: {e}")
        finally:
            self.loop.close()
    
    async def _async_main(self):
        """Main async loop - handles commands from queue"""
        while self.is_running:
            try:
                # Process commands from queue
                try:
                    command = self.command_queue.get_nowait()
                    action = command.get("action")
                    
                    if action == "connect":
                        result = await self._async_connect()
                        self.result_queue.put(("connect", result))
                        
                    elif action == "disconnect":
                        await self._async_disconnect()
                        self.result_queue.put(("disconnect", True))
                        
                    elif action == "poll":
                        result = await self._async_poll_data()
                        self.result_queue.put(("poll", result))
                        
                    elif action == "command":
                        register = command.get("register")
                        value = command.get("value")
                        result = await self._async_send_command(register, value)
                        self.result_queue.put(("command", result))
                        
                except queue.Empty:
                    pass
                
                # Small delay to prevent busy waiting
                await asyncio.sleep(0.1)
                
            except Exception as e:
                self.logger.error(f"Async main loop error: {e}")
                await asyncio.sleep(1.0)
    
    async def _async_connect(self) -> bool:
        """Connect to the Bluetti device (async)"""
        try:
            # Initialize device and client
            self.device = AC500(self.mac_address, "DomoticzWrapper")
            if not hasattr(self.device, 'fields'):
                self.device.fields = {}
                
            self.ble_client = BluetoothClient(self.mac_address)
            self.client_task = asyncio.create_task(self.ble_client.run())
            
            # Wait for client to be ready
            self.logger.info(f"Connecting to Bluetti: {self.mac_address}")
            wait_start = time.time()
            while not self.ble_client.is_ready:
                if time.time() - wait_start > self.connection_timeout:
                    raise ConnectionError(f"Connection timeout ({self.connection_timeout}s)")
                if self.client_task.done():
                    ex = self.client_task.exception()
                    if ex:
                        raise ex
                    raise ConnectionError("BLE client task ended unexpectedly")
                await asyncio.sleep(0.1)
            
            self.is_connected = True
            self.logger.info("Connected to Bluetti device")
            return True
            
        except Exception as e:
            self.logger.error(f"Connection error: {e}")
            self.is_connected = False
            return False
    
    async def _async_disconnect(self):
        """Disconnect from the Bluetti device (async)"""
        try:
            if self.client_task and not self.client_task.done():
                self.client_task.cancel()
                try:
                    await self.client_task
                except asyncio.CancelledError:
                    pass
                    
            self.ble_client = None
            self.client_task = None
            self.is_connected = False
            self.logger.info("Disconnected from Bluetti device")
            
        except Exception as e:
            self.logger.error(f"Disconnect error: {e}")
    
    async def _async_poll_data(self) -> Dict[str, Any]:
        """Poll data from the device (async) - uses the working code from old_script.py"""
        try:
            if not self.is_connected or not self.ble_client or not self.ble_client.is_ready:
                self.logger.warning("Not connected to device")
                return {}
            
            # Clear previous data
            self.device.fields.clear()
            
            # Poll main commands (same as old_script.py)
            for command in self.device.polling_commands:
                try:
                    self.logger.debug(f"Performing main command: {command} (addr: {command.starting_address})")
                    response_future = await self.ble_client.perform(command)
                    if response_future:
                        actual_bytes = await asyncio.wait_for(response_future, timeout=10.0)
                        if actual_bytes:
                            payload_bytes = command.parse_response(actual_bytes)
                            if payload_bytes:
                                parsed_segment = self._parse_ac500_data_segment(payload_bytes, command.starting_address)
                                self.device.fields.update(parsed_segment)
                            else:
                                self.logger.warning(f"Empty payload for {command}")
                        else:
                            self.logger.warning(f"No actual_bytes for {command}")
                    else:
                        self.logger.warning(f"No future for {command}")
                except Exception as e:
                    self.logger.error(f"Error main command {command}: {e}")
                    if not self.ble_client.is_ready:
                        raise ConnectionError("BLE client not ready during main poll.")
            
            # Poll battery packs (check all 6 possible pack slots)
            if hasattr(self.device, 'pack_polling_commands') and self.device.pack_polling_commands:
                # Always check all 6 pack slots since packs can be in any slot (e.g., packs 2 and 4)
                num_packs_to_iterate = 6
                
                self.logger.debug(f"Querying data for up to {num_packs_to_iterate} battery pack slots...")
                for pack_idx in range(1, num_packs_to_iterate + 1):
                    try:
                        self.logger.debug(f"Selecting battery pack {pack_idx} for polling...")
                        pack_selector_command = WriteSingleRegister(3006, pack_idx)
                        select_future = await self.ble_client.perform(pack_selector_command)
                        if select_future:
                            await asyncio.wait_for(select_future, timeout=5.0)
                            self.logger.debug(f"Pack {pack_idx} selected. Waiting 1s before polling pack data...")
                            await asyncio.sleep(1.0)
                        else:
                            self.logger.warning(f"No future for selecting pack {pack_idx}. Skipping.")
                            continue
                        
                        for pack_cmd in self.device.pack_polling_commands:
                            self.logger.debug(f"Performing command for pack {pack_idx}: {pack_cmd} (addr: {pack_cmd.starting_address})")
                            response_future = await self.ble_client.perform(pack_cmd)
                            if response_future:
                                actual_bytes = await asyncio.wait_for(response_future, timeout=10.0)
                                if actual_bytes:
                                    payload_bytes = pack_cmd.parse_response(actual_bytes)
                                    if payload_bytes:
                                        pack_segment_data = self._parse_ac500_data_segment(payload_bytes, pack_cmd.starting_address)
                                        for key, value in pack_segment_data.items():
                                            if key == 'current_pack_total_voltage':
                                                self.device.fields[f'pack_{pack_idx}_total_voltage'] = value
                                            elif key == 'current_pack_voltage':
                                                self.device.fields[f'pack_{pack_idx}_pack_voltage'] = value
                                            elif key == 'current_pack_battery_percent':
                                                self.device.fields[f'pack_{pack_idx}_battery_percent'] = value
                                            elif key == 'pack_num_max_bms' and ('pack_num_max_bms' not in self.device.fields or self.device.fields['pack_num_max_bms'] == 0):
                                                self.device.fields['pack_num_max_bms'] = value
                                    else:
                                        self.logger.warning(f"Empty payload for pack {pack_idx} cmd {pack_cmd}")
                                else:
                                    self.logger.warning(f"No actual_bytes for pack {pack_idx} cmd {pack_cmd}")
                            else:
                                self.logger.warning(f"No future for pack {pack_idx} cmd {pack_cmd}")
                    except Exception as e:
                        self.logger.error(f"Error polling pack {pack_idx}: {e}")
                        if not self.ble_client.is_ready:
                            raise ConnectionError(f"BLE client not ready during pack {pack_idx} poll.")
            
            return dict(self.device.fields)
            
        except Exception as e:
            self.logger.error(f"Poll error: {e}")
            return {}
    
    async def _async_send_command(self, register: int, value: int) -> bool:
        """Send command to device (async)"""
        try:
            if not self.is_connected or not self.ble_client or not self.ble_client.is_ready:
                self.logger.warning("Not connected to device")
                return False
            
            command = WriteSingleRegister(register, value)
            response_future = await self.ble_client.perform(command)
            
            if response_future:
                await asyncio.wait_for(response_future, timeout=10.0)
                return True
            else:
                return False
                
        except Exception as e:
            self.logger.error(f"Send command error: {e}")
            return False
    
    def _parse_ac500_data_segment(self, payload_bytes: bytes, starting_address: int) -> Dict[str, Any]:
        """Parse AC500 data segment - exact copy from old_script.py"""
        import struct
        segment_fields = {}
        try:
            if not payload_bytes or len(payload_bytes) < 2:
                self.logger.debug(f"Payload too short for parsing: {len(payload_bytes)} bytes at addr {starting_address}")
                return segment_fields
            num_registers = len(payload_bytes) // 2
            values = struct.unpack(f'>{num_registers}H', payload_bytes)
            self.logger.debug(f"Parsing segment addr {starting_address}, values count: {len(values)}")

            if starting_address == 10:  # Core Data
                if num_registers >= 40:
                    segment_fields['device_type'] = ''.join([chr((val >> 8) & 0xFF) + chr(val & 0xFF) for val in values[0:6] if val != 0]).strip('\x00')
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
            elif starting_address == 70:  # Detailed Data
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
                    segment_fields['ac_charging_power'] = values[19]  # Add missing ac_charging_power
            elif starting_address == 3001:  # Control Data
                if num_registers >= 6:
                    segment_fields['ups_mode'] = values[0]  # Register 3001
                    segment_fields['split_phase_on'] = bool(values[3])  # Register 3004
                    segment_fields['pack_num_configured'] = values[5]  # Register 3006
                    
                if num_registers >= 11:  # Registers 3001-3011
                    segment_fields['ac_output_on'] = bool(values[6])  # Register 3007
                    segment_fields['dc_output_on'] = bool(values[7])  # Register 3008
                    segment_fields['grid_charge_on'] = bool(values[10])  # Register 3011
                    
                if num_registers >= 16:  # Registers 3001-3016
                    segment_fields['time_control_on'] = bool(values[12])  # Register 3013
                    segment_fields['battery_range_start'] = values[14]  # Register 3015
                    segment_fields['battery_range_end'] = values[15]  # Register 3016
                    
                if num_registers >= 36:  # Register 3036
                    segment_fields['bluetooth_connected'] = bool(values[35])  # Register 3036
                    
                if num_registers >= 56:  # Registers 3039-3056 (Time Control Programming)
                    # Time control programming - 18 registers from 3039 to 3056
                    time_control_data = {}
                    for i in range(18):  # Registers 3039 to 3056
                        reg_addr = 3039 + i
                        reg_index = 38 + i  # Index in values array (3039 - 3001 = 38)
                        time_control_data[f'time_control_reg_{reg_addr}'] = values[reg_index]
                    
                    segment_fields['time_control_programming'] = time_control_data
                    
                if num_registers >= 61:  # Register 3061
                    segment_fields['auto_sleep_mode'] = values[60]  # Register 3061
            elif starting_address == 91:  # Pack specific data, generic keys for the *current* pack
                if num_registers >= 9:
                    segment_fields['current_pack_total_voltage'] = values[1] / 10.0
                    segment_fields['current_pack_voltage'] = values[7] / 100.0
                    segment_fields['current_pack_battery_percent'] = values[8]
                    if 'pack_num_max_bms' not in segment_fields or segment_fields.get('pack_num_max_bms') == 0:
                        segment_fields['pack_num_max_bms'] = values[0]
        except IndexError:
            self.logger.error(f"IndexError parsing segment addr {starting_address}. Values: {values}")
        except Exception as e:
            self.logger.error(f"Error parsing segment addr {starting_address}: {e}")
        return segment_fields
    
    # Synchronous interface methods
    def connect(self, timeout: float = 30.0) -> bool:
        """Connect to device (blocking)"""
        if not self.is_running:
            return False
            
        self.command_queue.put({"action": "connect"})
        
        # Wait for result
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                action, result = self.result_queue.get_nowait()
                if action == "connect":
                    return result
            except queue.Empty:
                time.sleep(0.1)
        
        return False
    
    def disconnect(self) -> bool:
        """Disconnect from device (blocking)"""
        if not self.is_running:
            return True
            
        self.command_queue.put({"action": "disconnect"})
        
        # Wait for result
        start_time = time.time()
        while time.time() - start_time < 5.0:
            try:
                action, result = self.result_queue.get_nowait()
                if action == "disconnect":
                    return result
            except queue.Empty:
                time.sleep(0.1)
        
        return False
    
    def poll_data(self, timeout: float = 30.0) -> Dict[str, Any]:
        """Poll device data (blocking)"""
        if not self.is_running:
            return {}
            
        self.command_queue.put({"action": "poll"})
        
        # Wait for result
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                action, result = self.result_queue.get_nowait()
                if action == "poll":
                    return result
            except queue.Empty:
                time.sleep(0.1)
        
        return {}
    
    def send_command(self, register: int, value: int, timeout: float = 10.0) -> bool:
        """Send command to device (blocking)"""
        if not self.is_running:
            return False
            
        self.command_queue.put({"action": "command", "register": register, "value": value})
        
        # Wait for result
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                action, result = self.result_queue.get_nowait()
                if action == "command":
                    return result
            except queue.Empty:
                time.sleep(0.1)
        
        return False

# Alias for compatibility
DomoticzBluettiClient = DomoticzBluettiWrapper
