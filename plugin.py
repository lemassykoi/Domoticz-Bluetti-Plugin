# Domoticz Python Plugin for Bluetti AC500
# Author: lemassykoi
# Version: 0.2.1
#
"""
<plugin key="Bluetti-BLE-AC500" name="Bluetti AC500 via BLE" author="lemassykoi" version="0.2.1" wikilink="https://github.com/lemassykoi/Domoticz-Bluetti-Plugin" externallink="https://www.bluettipower.com/">
    <params>
        <param field="Address" label="Bluetti MAC Address" width="200px" required="true" default="XX:XX:XX:XX:XX:XX"/>
        <param field="Mode1" label="Polling Interval (seconds)" width="75px" required="true" default="20"/>
        <param field="Mode6" label="Debug Level" width="200px">
            <options>
                <option label="0: None (Plugin Log only)" value="0" default="true"/>
                <option label="1: Plugin Debug" value="1"/>
                <option label="2: Plugin + BLE Library Debug" value="2"/>
                <option label="10: All Debug (Verbose)" value="10"/>
            </options>
        </param>
        <param field="Port" label="BLE Adapter (e.g., hci0, default empty for auto)" width="150px" required="false" default=""/>
    </params>
</plugin>
"""
import Domoticz
import threading
import queue
import time
import sys
import os
import struct 
import base64
import logging
from enum import Enum, unique

try:
    from domoticz_bluetti_wrapper import DomoticzBluettiClient
except ImportError as e:
    error_msg = f"Bluetti BLE AC500 Plugin ERROR: Failed to import domoticz_bluetti_wrapper. Error: {e}"
    sys.stderr.write(error_msg + "\n") 
    try:
        Domoticz.Error(error_msg)
    except NameError:
        pass
    raise

# Constants from bluetti_mqtt
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

# Use the working wrapper from external file

# Domoticz Name, Unit ID, Domoticz TypeName, DomoticzType, DomoticzSubtype, DeviceID_Suffix, CreateSwitchType, CreateImage, UpdateOptsWhenCreating, UpdateOptsAlways, JSON Key, Used
BLUETTI_DEVICE_DEFINITIONS = [
    # Name, Unit, TypeName, Type, Subtype, DevIDSfx, SwTypeCr, ImgCr, OptsCr, OptsUpd, JSONKey, Used
    ("Bluetti Device Type", 1, "Text", 243, 19, "devtype", 0, 0, {}, {}, "device_type", 0),
    ("Bluetti Serial Number", 2, "Text", 243, 19, "serial", 0, 0, {}, {}, "serial_number", 0),
    ("Bluetti ARM Version", 3, "Text", 243, 19, "arm", 0, 0, {}, {}, "arm_version", 0),
    ("Bluetti DSP Version", 4, "Text", 243, 19, "dsp", 0, 0, {}, {}, "dsp_version", 0),
    ("Bluetti Total Battery", 5, "Percentage", 243, 6, "totalbatt", 0, 0, {}, {}, "total_battery_percent", 1),
    ("Bluetti DC Input Power",  6, "kWh", 250, 1, "dcinpow", 0, 0, {"DisableLogAutoUpdate": "true", "AddDBLogEntry": "true"}, {"EnergyMeterMode": "1"}, "dc_input_power", 0),
    ("Bluetti AC Input Power",  7, "kWh", 250, 1, "acinpow", 0, 0, {"DisableLogAutoUpdate": "true", "AddDBLogEntry": "true"}, {"EnergyMeterMode": "1"}, "ac_input_power", 1),
    ("Bluetti AC Output Power", 8, "kWh", 250, 1, "acoutpow", 0, 0, {"DisableLogAutoUpdate": "true", "AddDBLogEntry": "true"}, {"EnergyMeterMode": "1"}, "ac_output_power", 1),
    ("Bluetti DC Output Power", 9, "kWh", 250, 1, "dcoutpow", 0, 0, {"DisableLogAutoUpdate": "true", "AddDBLogEntry": "true"}, {"EnergyMeterMode": "1"}, "dc_output_power", 0),
    ("Bluetti Power Generation",10,"kWh", 250, 1, "pwrgen", 0, 0, {"DisableLogAutoUpdate": "true", "AddDBLogEntry": "true"}, {"EnergyMeterMode": "1"}, "power_generation", 0),
    ("Bluetti AC Output State", 11, "Switch", 244, 73, "acoutstate", 0, 9, {}, {}, "ac_output_on", 1),
    ("Bluetti DC Output State", 12, "Switch", 244, 73, "dcoutstate", 0, 9, {}, {}, "dc_output_on", 1),
    ("Bluetti Grid Charge", 28, "Switch", 244, 73, "gridcharge", 0, 9, {}, {}, "grid_charge_on", 1),
    ("Bluetti Time Control", 29, "Switch", 244, 73, "timecontrol", 0, 9, {}, {}, "time_control_on", 1),
    ("Bluetti UPS Mode", 30, "Selector Switch", 244, 62, "upsmode", 18, 0, {"LevelActions": "||||", "LevelNames": "Off|Customized|PV Priority|Standard|Time Control", "LevelOffHidden": "false", "SelectorStyle": "1"}, {}, "ups_mode", 1),
    ("Bluetti Battery Range Start", 60, "Percentage", 243, 6, "battrangestart", 0, 0, {}, {}, "battery_range_start", 0),
    ("Bluetti Battery Range End", 61, "Percentage", 243, 6, "battrangeend", 0, 0, {}, {}, "battery_range_end", 0),
    ("Bluetti Time Schedule", 62, "Text", 243, 19, "timeschedule", 0, 0, {}, {}, "time_control_programming", 1),
    ("Bluetti AC Output Mode",  13, "Selector Switch", 244, 62, "acoutmode", 18, 0, {"LevelActions": "|||||", "LevelNames": "Off|Stop|Inverter Output|Bypass Output C|Bypass Output D|Load Matching", "LevelOffHidden": "false", "SelectorStyle": "1"}, {}, "ac_output_mode", 0),
    ("Bluetti Internal AC Voltage", 14, "Voltage", 243, 8, "intacvolt", 0, 0, {}, {}, "internal_ac_voltage", 0),
    ("Bluetti Internal AC Frequency", 17, "Text", 243, 19, "intacfreq", 0, 0, {}, {}, "internal_ac_frequency", 0),
    ("Bluetti AC Input Voltage", 20, "Voltage", 243, 8, "acinvolt", 0, 0, {}, {}, "ac_input_voltage", 0),
    ("Bluetti Internal Current 3", 21, "Current (Single)", 243, 23, "intcurr3", 0, 0, {}, {}, "internal_current_three", 0),
    ("Bluetti AC Input Frequency", 23, "Text", 243, 19, "acinfreq", 0, 0, {}, {}, "ac_input_frequency", 0),
    ("Bluetti Internal DC Voltage", 24, "Voltage", 243, 8, "intdcvolt", 0, 0, {}, {}, "internal_dc_input_voltage", 0),
    ("Bluetti Internal DC Power",   25, "Usage", 243, 29, "intdcpower", 0, 0, {}, {'EnergyMeterMode':'1', "Switchtype":"0"}, "internal_dc_input_power", 0),
    ("Bluetti Internal DC Current", 26, "Current (Single)", 243, 23, "intdccurr", 0, 0, {}, {}, "internal_dc_input_current", 0),
    ("Bluetti AC Charging Power", 27, "Usage", 243, 29, "acchargepow", 0, 0, {}, {'EnergyMeterMode':'1', "Switchtype":"0"}, "ac_charging_power", 0),
]

PACK_DEVICE_UNIT_START_OFFSET = 30 
PACK_DEVICE_DEFINITIONS = [
    ("Total Voltage", "Voltage", 243, 8, "packtv", 0, 0, {}, {}, "total_voltage", 0),
    ("Voltage", "Voltage", 243, 8, "packv", 0, 0, {}, {}, "pack_voltage", 0),
    ("Battery", "Percentage", 243, 6, "packbatt", 0, 0, {}, {}, "battery_percent", 1),
]

class BasePlugin:
    def __init__(self):
        self.bluetti_mac_address = None
        self.polling_interval = 20
        self.debug_level = 0
        self.bluetti_client = None
        self.update_thread = None
        self.shutdown_event = None
        self.command_queue = queue.Queue()
        self.device_unit_map = {}
        self.next_poll_time = 0
        return

    def onStart(self):
        Domoticz.Log("onStart: Initializing plugin...")
        try: 
            self.debug_level = int(Parameters["Mode6"])
        except ValueError: 
            self.debug_level = 0
        
        if self.debug_level == 0: 
            Domoticz.Debugging(0)
        else: 
            Domoticz.Debugging(int(Parameters["Mode6"]))
            Domoticz.Log(f"Plugin Debug level set to: {self.debug_level}")
            DumpConfigToLog()
            
        # Enable debugging for first run to see what's happening
        if self.debug_level == 0:
            Domoticz.Debugging(1)
            Domoticz.Log("Temporarily enabling debug logging")

        self.bluetti_mac_address = Parameters["Address"].strip()
        if not self.bluetti_mac_address or self.bluetti_mac_address == "XX:XX:XX:XX:XX:XX": 
            Domoticz.Error("MAC Address not configured. Plugin will not start.")
            return
        
        try: 
            self.polling_interval = int(Parameters["Mode1"])
        except ValueError: 
            self.polling_interval = 20
        if self.polling_interval < 5: 
            self.polling_interval = 5
        
        Domoticz.Log(f"onStart: Parameters loaded. MAC:{self.bluetti_mac_address}, Poll:{self.polling_interval}s")
        
        self.create_domoticz_devices()
        
        # Wait a moment for devices to be created in Domoticz
        time.sleep(2)
        
        # Start synchronous thread
        self.shutdown_event = threading.Event()
        self.update_thread = threading.Thread(name="BluettiUpdateThread", target=self.handle_thread)
        self.update_thread.daemon = True
        self.update_thread.start()
        
        Domoticz.Heartbeat(10) 
        Domoticz.Log("onStart: Completed successfully.")

    def create_domoticz_devices(self):
        Domoticz.Log("create_domoticz_devices: Starting device check/creation...")
        plugin_key = Parameters["Key"]
        
        for name, unit_id, type_name, d_type, d_subtype, device_id_suffix, d_switchtype, d_image, create_opts_selector, update_opts_general, json_key, used in BLUETTI_DEVICE_DEFINITIONS:
            full_device_id = f"{plugin_key}_{device_id_suffix}"
            
            if unit_id not in Devices:
                Domoticz.Log(f"create_domoticz_devices: Creating Unit {unit_id} ('{name}') with DeviceID '{full_device_id}'...")
                Domoticz.Device(Name=name, Unit=unit_id, TypeName=type_name, DeviceID=full_device_id, Used=used).Create()
                
                if unit_id in Devices:
                    Devices[unit_id].Update(nValue=0, sValue="0")
                    if create_opts_selector:
                        Devices[unit_id].Update(nValue=0, sValue="0", Options=create_opts_selector)
            
            # Apply update options if specified
            if unit_id in Devices and update_opts_general:
                try:
                    options_changed = False
                    current_dev_options = Devices[unit_id].Options if hasattr(Devices[unit_id], 'Options') else {}
                    effective_options = current_dev_options.copy()
                    
                    for opt_key, opt_value in update_opts_general.items():
                        if str(effective_options.get(opt_key)) != str(opt_value):
                            effective_options[opt_key] = opt_value
                            options_changed = True
                    
                    if options_changed: 
                        Devices[unit_id].Update(nValue=Devices[unit_id].nValue, sValue=Devices[unit_id].sValue, Options=effective_options)
                        
                except Exception as e: 
                    Domoticz.Error(f"Error applying update options to {name} (Unit: {unit_id}): {e}")
            
            self.device_unit_map[json_key] = unit_id
        
        # Battery pack devices - only pack 2 and 4
        for pack_num in [2, 4]: 
            for i, (name_suffix, type_name_pack, d_type_pack, d_subtype_pack, device_id_suffix_pack, d_switchtype_pack, d_image_pack, create_opts_selector_pack, update_opts_general_pack, json_key_suffix, used_pack) in enumerate(PACK_DEVICE_DEFINITIONS):
                unit_id_pack = PACK_DEVICE_UNIT_START_OFFSET + ((pack_num - 1) * len(PACK_DEVICE_DEFINITIONS)) + i + 1
                dev_name_pack = f"Bluetti Pack {pack_num} {name_suffix}"
                json_key_pack = f"pack_{pack_num}_{json_key_suffix}"
                full_device_id_pack = f"{plugin_key}_pack{pack_num}_{device_id_suffix_pack}"
                
                if unit_id_pack not in Devices:
                    Domoticz.Log(f"create_domoticz_devices: Creating Unit {unit_id_pack} ('{dev_name_pack}') with DeviceID '{full_device_id_pack}'...")
                    Domoticz.Device(Name=dev_name_pack, Unit=unit_id_pack, TypeName=type_name_pack, DeviceID=full_device_id_pack, Used=used_pack).Create()
                    
                    if unit_id_pack in Devices: 
                        Devices[unit_id_pack].Update(nValue=0, sValue="0") 
                        if create_opts_selector_pack:
                            Devices[unit_id_pack].Update(nValue=0, sValue="0", Options=create_opts_selector_pack)

                if unit_id_pack in Devices and update_opts_general_pack:
                    try:
                        options_changed_pack = False
                        current_dev_options_pack = Devices[unit_id_pack].Options if hasattr(Devices[unit_id_pack], 'Options') else {}
                        effective_options_pack = current_dev_options_pack.copy()
                        
                        for opt_key_pack, opt_value_pack in update_opts_general_pack.items():
                            if str(effective_options_pack.get(opt_key_pack)) != str(opt_value_pack):
                                effective_options_pack[opt_key_pack] = opt_value_pack
                                options_changed_pack = True
                                
                        if options_changed_pack:
                            Devices[unit_id_pack].Update(nValue=Devices[unit_id_pack].nValue, sValue=Devices[unit_id_pack].sValue, Options=effective_options_pack)
                    except Exception as e: 
                        Domoticz.Error(f"Error applying update options to {dev_name_pack} (Unit: {unit_id_pack}): {e}")
                        
                self.device_unit_map[json_key_pack] = unit_id_pack
        
        Domoticz.Log(f"create_domoticz_devices: Device map populated with {len(self.device_unit_map)} entries.")

    def handle_thread(self):
        """Pure threading handler - no asyncio here"""
        Domoticz.Log("Update thread started.")
        
        try:            
            # Initialize threaded Bluetti client (use default logger)
            self.bluetti_client = DomoticzBluettiClient(self.bluetti_mac_address)
            self.bluetti_client.start()
            
            # Try to connect
            if not self.bluetti_client.connect():
                Domoticz.Error("Failed to connect to Bluetti device")
                return
            
            Domoticz.Log("Connected to Bluetti device")
            
            # Main loop - pure threading, no asyncio
            while not self.shutdown_event.is_set():
                try:
                    # Process commands from queue
                    try:
                        item = self.command_queue.get_nowait()
                        if item == "POLL_DATA":
                            self._poll_data()
                        elif isinstance(item, dict) and item.get("action") == "SEND_COMMAND":
                            self._send_command(item['details'])
                        self.command_queue.task_done()
                    except queue.Empty:
                        pass
                    
                    # Wait before next iteration
                    self.shutdown_event.wait(1.0)
                    
                except Exception as e:
                    Domoticz.Error(f"Thread loop error: {e}")
                    time.sleep(5)
                    
        except Exception as e:
            Domoticz.Error(f"Thread handler error: {e}")
        finally:
            if self.bluetti_client:
                self.bluetti_client.disconnect()
                self.bluetti_client.stop()
            Domoticz.Log("Update thread finished.")
    
    def _poll_data(self):
        """Pure threading data polling"""
        try:
            Domoticz.Log("Polling Bluetti data...")
            
            # Poll data from threaded client
            data = self.bluetti_client.poll_data()
            
            if data:
                self._update_domoticz_devices(data)
                Domoticz.Log(f"Updated {len(data)} fields from Bluetti device")
            else:
                Domoticz.Log("WARNING: No data received from Bluetti device")
                
        except Exception as e:
            Domoticz.Error(f"Polling error: {e}")
    
    def _send_command(self, command_details):
        """Pure threading command sending"""
        try:
            register = command_details.get("register")
            value = command_details.get("value")
            
            if register is not None and value is not None:
                Domoticz.Log(f"Sending command: register={register}, value={value}")
                
                # Send command using threaded client
                success = self.bluetti_client.send_command(register, value)
                
                if success:
                    Domoticz.Log("Command sent successfully")
                    # Wait for device to process command before polling
                    time.sleep(5)
                    # Queue a poll to update status
                    self.command_queue.put("POLL_DATA")
                else:
                    Domoticz.Error("Command failed")
            else:
                Domoticz.Error(f"Invalid command details: {command_details}")
                
        except Exception as e:
            Domoticz.Error(f"Command error: {e}")

    def _decode_time_schedule(self, time_control_data):
        """Decode time control schedule using base256 encoding"""
        try:
            def decode_bluetti_time(value):
                """Decode Bluetti time value using base256 encoding"""
                if value == 0:
                    return "00:00"
                
                # Base 256 encoding: hours*256 + minutes
                hours = value // 256
                minutes = value % 256
                
                if hours <= 23 and minutes <= 59:
                    return f"{hours:02d}:{minutes:02d}"
                
                return f"Raw:{value}"
            
            if not isinstance(time_control_data, dict):
                return "Invalid data"
            
            # Extract all register values in order
            values = []
            for i in range(3039, 3057):
                reg_key = f'time_control_reg_{i}'
                if reg_key in time_control_data:
                    values.append(time_control_data[reg_key])
                else:
                    values.append(0)
            
            # Extract unique time values (large values > 256)
            time_values = []
            seen_times = set()
            for value in values:
                if value > 256 and value not in seen_times:
                    time_values.append(value)
                    seen_times.add(value)
            
            if len(time_values) >= 3:
                # Sort time values to get chronological order
                time_values.sort()
                
                # Build schedule based on actual pattern analysis
                # Pattern appears to be alternating charge/discharge periods
                schedule_parts = []
                times = [decode_bluetti_time(val) for val in time_values[:4]]
                
                if len(times) >= 3:
                    # Create periods based on transitions - alternating charge/discharge
                    schedule_parts.append(f"00:00-{times[0]}:Charge")
                    schedule_parts.append(f"{times[0]}-{times[1]}:Discharge")
                    if len(times) >= 3:
                        schedule_parts.append(f"{times[1]}-{times[2]}:Charge")
                    if len(times) >= 4:
                        schedule_parts.append(f"{times[2]}-{times[3]}:Discharge")
                        schedule_parts.append(f"{times[3]}-23:59:Charge")
                    else:
                        schedule_parts.append(f"{times[2]}-23:59:Discharge")
                
                return " | ".join(schedule_parts)
            else:
                return f"Schedule: {len(time_values)} transitions found"
                
        except Exception as e:
            Domoticz.Debug(f"Error decoding time schedule: {e}")
            return "Decode error"

    def _update_domoticz_devices(self, bluetti_data_fields):
        """Update Domoticz devices with data from Bluetti"""
        Domoticz.Log(f"Processing {len(bluetti_data_fields)} fields for Domoticz update.")
        
        # Debug: Show all available fields
        Domoticz.Debug(f"Available fields: {list(bluetti_data_fields.keys())}")
        
        # Debug: Show power values specifically
        power_fields = ['dc_input_power', 'ac_input_power', 'ac_output_power', 'dc_output_power']
        for field in power_fields:
            if field in bluetti_data_fields:
                Domoticz.Log(f"DEBUG: {field} = {bluetti_data_fields[field]}")
        
        # Debug: Show what's in the Devices dictionary
        Domoticz.Debug(f"Devices dictionary contains units: {list(Devices.keys())}")
        Domoticz.Debug(f"Device map contains {len(self.device_unit_map)} entries")
        
        for json_key, unit in self.device_unit_map.items():
            try:
                if unit not in Devices:
                    Domoticz.Debug(f"Unit {unit} for {json_key} not found in Devices")
                    continue
                    
                raw_value = bluetti_data_fields.get(json_key)
                if raw_value is None: 
                    Domoticz.Debug(f"Field '{json_key}' not in polled data for Unit {unit}.")
                    continue
                    
                nvalue, svalue = 0, ""
                changed = False
                curr_nval, curr_sval = Devices[unit].nValue, Devices[unit].sValue
                
                Domoticz.Debug(f"Processing {json_key}={raw_value} for Unit {unit}, current nVal={curr_nval}, sVal='{curr_sval}'")

                if json_key in ["device_type","serial_number","arm_version","dsp_version"]: 
                    # Clean up device type display - remove null bytes and control characters
                    if json_key == "device_type":
                        # Remove null bytes, control characters, and extract readable part
                        clean_value = ''.join(c for c in str(raw_value) if c.isprintable() and c not in '\x00\x03')
                        if "AC500" in clean_value or "PAC500" in clean_value:
                            svalue = "AC500"  # Display as AC500 for clarity
                        else:
                            svalue = clean_value
                    else:
                        svalue = str(raw_value)
                    nvalue = curr_nval
                    changed = (svalue != curr_sval)
                
                elif json_key.endswith(("_total_voltage","_pack_voltage")) or json_key in ["internal_ac_voltage","ac_input_voltage","internal_dc_input_voltage"]: 
                    svalue = f"{float(raw_value):.1f}"
                    nvalue = 0
                    changed = (svalue != curr_sval)
                
                elif json_key in ["internal_current_one","internal_current_two","internal_current_three","internal_dc_input_current"]: 
                    svalue = f"{float(raw_value):.1f}"
                    nvalue = 0
                    changed = (svalue != curr_sval)
                
                elif json_key in ["total_battery_percent"] or json_key.endswith("_battery_percent"): 
                    svalue = str(int(round(float(raw_value))))
                    nvalue = int(svalue)
                    changed = (nvalue != curr_nval or svalue != curr_sval)
                
                elif json_key in ["internal_ac_frequency","ac_input_frequency"]: 
                    # Display frequency as text with Hz unit
                    svalue = f"{float(raw_value):.1f} Hz"
                    nvalue = curr_nval
                    changed = (svalue != curr_sval)
                
                elif json_key in ["dc_input_power","ac_input_power","ac_output_power","dc_output_power","power_generation","ac_charging_power"]: 
                    # Use simple kWh device format: "power_value;0"
                    power_val = float(raw_value)
                    svalue = f"{power_val:.1f};0"
                    nvalue = 0
                    changed = (svalue != curr_sval)
                
                elif json_key in ["internal_power_one","internal_power_two","internal_power_three","internal_dc_input_power"]: 
                    # Keep internal power sensors as simple power values
                    svalue = f"{float(raw_value):.1f};0"
                    nvalue = 0
                    changed = (svalue.split(';')[0] != (curr_sval.split(';')[0] if ';' in curr_sval else curr_sval))
                
                elif json_key in ["ac_output_on","dc_output_on","grid_charge_on","time_control_on"]: 
                    nvalue = 1 if raw_value else 0
                    svalue = str(nvalue)
                    changed = (nvalue != curr_nval)
                
                elif json_key == "ac_output_mode": 
                    # Decode AC output mode from raw value to selector level using enum
                    # Raw 0->Stop(level 10), 1->Inverter(level 20), 2->Bypass C(level 30), 3->Bypass D(level 40), 4->Load Matching(level 50)
                    # Level 0 is reserved for "Off"
                    mode_names = ["Stop", "Inverter Output", "Bypass Output C", "Bypass Output D", "Load Matching"]
                    
                    # Map raw value to selector level (add 1 to skip "Off" at level 0)
                    raw_int = int(raw_value)
                    if raw_int < len(mode_names):
                        mode_text = mode_names[raw_int]
                        level = (raw_int + 1) * 10  # 0->10, 1->20, 2->30, 3->40, 4->50
                    else:
                        # Handle unknown values
                        mode_text = f"Mode {raw_value}"
                        level = 0
                    
                    nvalue = 2
                    svalue = str(level)
                    changed = (str(level) != curr_sval or curr_nval != 2)
                    
                    # Log the mode for debugging
                    Domoticz.Debug(f"AC Output Mode: raw={raw_value}, decoded='{mode_text}', level={level}")
                
                elif json_key == "ups_mode":
                    # Decode UPS mode from raw value to selector level using UpsMode enum
                    # Raw 1->Customized(level 10), 2->PV Priority(level 20), 3->Standard(level 30), 4->Time Control(level 40)
                    # Level 0 is reserved for "Off"
                    mode_names = ["Customized", "PV Priority", "Standard", "Time Control"]
                    
                    # Map raw value to selector level (add 0 offset since UPS modes start at 1)
                    raw_int = int(raw_value)
                    if 1 <= raw_int <= len(mode_names):
                        mode_text = mode_names[raw_int - 1]  # Convert 1-based to 0-based index
                        level = raw_int * 10  # 1->10, 2->20, 3->30, 4->40
                    else:
                        # Handle unknown values
                        mode_text = f"Mode {raw_value}"
                        level = 0
                    
                    nvalue = 2
                    svalue = str(level)
                    changed = (str(level) != curr_sval or curr_nval != 2)
                    
                    # Log the mode for debugging
                    Domoticz.Debug(f"UPS Mode: raw={raw_value}, decoded='{mode_text}', level={level}")
                
                elif json_key in ["battery_range_start", "battery_range_end"]:
                    # Display battery range as percentage values (now using Percentage device type)
                    if isinstance(raw_value, (int, float)) and 0 <= raw_value <= 100:
                        nvalue = int(raw_value)  # For percentage devices, nValue is the percentage
                        svalue = str(int(raw_value))  # sValue is just the number
                    else:
                        nvalue = 0
                        svalue = f"Raw: {raw_value}"
                    changed = (svalue != curr_sval or nvalue != curr_nval)
                
                elif json_key == "time_control_programming":
                    # Decode time control schedule for display
                    if isinstance(raw_value, dict):
                        schedule_text = self._decode_time_schedule(raw_value)
                        svalue = schedule_text
                        nvalue = curr_nval
                        changed = (svalue != curr_sval)
                    else:
                        svalue = "Schedule unavailable"
                        nvalue = curr_nval
                        changed = (svalue != curr_sval)
                
                else: 
                    Domoticz.Log(f"WARNING: No update logic for '{json_key}'.")
                    continue
                
                if changed: 
                    Devices[unit].Update(nValue=nvalue, sValue=svalue, TimedOut=0)
                    Domoticz.Log(f"Updated Unit {unit} ({json_key}) to nVal:{nvalue}, sVal:'{svalue}'")
                else: 
                    Domoticz.Debug(f"Unit {unit} ({json_key}) value unchanged.")
                    
            except Exception as e: 
                Domoticz.Error(f"Error processing field '{json_key}' for Unit {unit}: {e}")

    def onStop(self):
        Domoticz.Log("onStop called.")
        if self.shutdown_event: 
            self.shutdown_event.set()
            
        if hasattr(self, 'update_thread') and self.update_thread and self.update_thread.is_alive():
            Domoticz.Log("Waiting for update thread to join...")
            self.update_thread.join(timeout=15)
            if self.update_thread.is_alive(): 
                Domoticz.Error("Update thread did not stop.")
        
        Domoticz.Log("Plugin stopped.")

    def onHeartbeat(self):
        Domoticz.Debug("onHeartbeat called")
        if not (hasattr(self, 'update_thread') and self.update_thread and self.update_thread.is_alive()): 
            Domoticz.Error("Update thread not running!")
            return
            
        current_time = time.time()
        if current_time >= self.next_poll_time:
            if self.command_queue: 
                Domoticz.Log("Queueing POLL_DATA request.")
                self.command_queue.put("POLL_DATA")
                self.next_poll_time = current_time + self.polling_interval
            else: 
                Domoticz.Log("WARNING: Command queue not initialized.")
        
    def onConnect(self, Connection, Status, Description):
        Domoticz.Log("onConnect called")

    def onMessage(self, Connection, Data):
        Domoticz.Log("onMessage called")

    def onCommand(self, Unit, Command, Level, Hue):
        Domoticz.Log(f"onCommand called for Unit {Unit}: Command '{Command}' (type: {type(Command)}), Level: {Level}")
        
        cmd_details = None
        for key, unit_num in self.device_unit_map.items():
            if unit_num == Unit:
                if key == "ac_output_on": 
                    cmd_details = {"register": 3007, "value": 1 if str(Command).lower() == "on" else 0}
                elif key == "dc_output_on": 
                    cmd_details = {"register": 3008, "value": 1 if str(Command).lower() == "on" else 0}
                elif key == "grid_charge_on":
                    cmd_details = {"register": 3011, "value": 1 if str(Command).lower() == "on" else 0}
                elif key == "time_control_on":
                    cmd_details = {"register": 3013, "value": 1 if str(Command).lower() == "on" else 0}
                elif key == "ups_mode":
                    try: 
                        # Convert selector level back to raw value for UPS Mode
                        bluetti_val = int(Level) // 10  # 10->1, 20->2, 30->3, 40->4
                        if 1 <= bluetti_val <= 4:  # Ensure valid range (1-4)
                            cmd_details = {"register": 3001, "value": bluetti_val}
                            Domoticz.Log(f"UPS Mode command for Domoticz Level {Level} (Bluetti val {bluetti_val})")
                        else:
                            Domoticz.Error(f"Invalid Level '{Level}' for UPS Mode - must be 10,20,30,40")
                    except ValueError: 
                        Domoticz.Error(f"Invalid Level '{Level}' for UPS Mode.")
                elif key == "ac_output_mode":
                    try: 
                        # Convert selector level back to raw value (subtract 1 to skip "Off" at level 0)
                        bluetti_val = (int(Level) // 10) - 1 
                        if bluetti_val >= 0:  # Ensure valid range
                            cmd_details = {"register": 3002, "value": bluetti_val}
                            Domoticz.Log(f"AC Output Mode command for Domoticz Level {Level} (Bluetti val {bluetti_val})")
                        else:
                            Domoticz.Error(f"Invalid Level '{Level}' for AC Output Mode - cannot map to Off state")
                    except ValueError: 
                        Domoticz.Error(f"Invalid Level '{Level}' for AC Output Mode.")
                        
                if cmd_details: 
                    break
        
        if cmd_details:
            if self.command_queue: 
                self.command_queue.put({"action": "SEND_COMMAND", "details": cmd_details})
                Domoticz.Log(f"Queued command for Unit {Unit}: {cmd_details}")
            else: 
                Domoticz.Error("Command queue not available.")
        else: 
            Domoticz.Log(f"No Bluetti action for Unit {Unit}, Command '{Command}'.")

    def onNotification(self, Name, Subject, Text, Status, Priority, Sound, ImageFile):
        Domoticz.Log("Notification: " + Name + "," + Subject + "," + Text + "," + Status + "," + str(Priority) + "," + Sound + "," + ImageFile)

    def onDisconnect(self, Connection):
        Domoticz.Log("onDisconnect called")

_plugin = BasePlugin()
def onStart(): 
    global _plugin
    _plugin.onStart()
    
def onStop(): 
    global _plugin
    _plugin.onStop()
    
def onConnect(Connection, Status, Description): 
    global _plugin
    _plugin.onConnect(Connection, Status, Description)
    
def onMessage(Connection, Data): 
    global _plugin
    _plugin.onMessage(Connection, Data)
    
def onCommand(Unit, Command, Level, Hue): 
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Hue)
    
def onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile): 
    global _plugin
    _plugin.onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile)
    
def onDisconnect(Connection): 
    global _plugin
    _plugin.onDisconnect(Connection)
    
def onHeartbeat(): 
    global _plugin
    _plugin.onHeartbeat()

# Generic helper functions
def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Debug( "'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Debug("Device count: " + str(len(Devices)))
    for DeviceName in Devices:
        Device = Devices[DeviceName]
        Domoticz.Debug("Device ID:       '" + str(Device.DeviceID) + "'")
        Domoticz.Debug("--->Unit Name:     '" + str(Device.Name) + "'")
        Domoticz.Debug("--->Unit nValue:    " + str(Device.nValue))
        Domoticz.Debug("--->Unit sValue:   '" + str(Device.sValue) + "'")
        Domoticz.Debug("--->Unit LastLevel: " + str(Device.LastLevel))
    return
