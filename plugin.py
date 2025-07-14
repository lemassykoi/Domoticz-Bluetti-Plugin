# Domoticz Python Plugin for Bluetti AC500
# Author: lemassykoi
# Version: 0.3.0
#
"""
<plugin key="Bluetti-BLE-AC500" name="Bluetti AC500 via BLE" author="lemassykoi" version="0.3.0" wikilink="https://github.com/lemassykoi/Domoticz-Bluetti-Plugin" externallink="https://www.bluettipower.com/">
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
import logging
from enum import Enum, unique

from domoticz_bluetti_wrapper import DomoticzBluettiClient

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
    ("Bluetti AC Output Mode",  13, "Selector Switch", 244, 62, "acoutmode", 18, 0, {"LevelActions": "|||||", "LevelNames": "Off|Stop|Inverter Output|Bypass Output C|Bypass Output D|Load Matching", "LevelOffHidden": "false", "SelectorStyle": "1"}, {}, "ac_output_mode", 0),
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
        
        time.sleep(2)
        
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
        Domoticz.Log("Update thread started.")
        
        try:            
            self.bluetti_client = DomoticzBluettiClient(self.bluetti_mac_address)
            
            if not self.bluetti_client.connect():
                Domoticz.Error("Failed to connect to Bluetti device")
                return
            
            Domoticz.Log("Connected to Bluetti device")
            
            while not self.shutdown_event.is_set():
                try:
                    item = self.command_queue.get_nowait()
                    if item == "POLL_DATA":
                        self._poll_data()
                    elif isinstance(item, dict) and item.get("action") == "SEND_COMMAND":
                        self._send_command(item['details'])
                    self.command_queue.task_done()
                except queue.Empty:
                    pass
                    
                self.shutdown_event.wait(1.0)
                    
        except Exception as e:
            Domoticz.Error(f"Thread handler error: {e}")
        finally:
            if self.bluetti_client:
                self.bluetti_client.disconnect()
            Domoticz.Log("Update thread finished.")
    
    def _poll_data(self):
        try:
            Domoticz.Log("Polling Bluetti data...")
            data = self.bluetti_client.poll_data()
            
            if data:
                self.update_domoticz_devices(data)
                Domoticz.Log(f"Updated {len(data)} fields from Bluetti device")
            else:
                Domoticz.Log("WARNING: No data received from Bluetti device")
                
        except Exception as e:
            Domoticz.Error(f"Polling error: {e}")
    
    def _send_command(self, command_details):
        try:
            register = command_details.get("register")
            value = command_details.get("value")
            
            if register is not None and value is not None:
                Domoticz.Log(f"Sending command: register={register}, value={value}")
                success = self.bluetti_client.send_command(register, value)
                
                if success:
                    Domoticz.Log("Command sent successfully")
                    time.sleep(5)
                    self.command_queue.put("POLL_DATA")
                else:
                    Domoticz.Error("Command failed")
            else:
                Domoticz.Error(f"Invalid command details: {command_details}")
                
        except Exception as e:
            Domoticz.Error(f"Command error: {e}")

    def update_domoticz_devices(self, bluetti_data_fields):
        for json_key, unit in self.device_unit_map.items():
            try:
                if unit not in Devices:
                    continue
                    
                raw_value = bluetti_data_fields.get(json_key)
                if raw_value is None: 
                    continue
                    
                nvalue, svalue = 0, ""
                changed = False
                curr_nval, curr_sval = Devices[unit].nValue, Devices[unit].sValue
                
                if isinstance(raw_value, (int, float)):
                    svalue = str(raw_value)
                else:
                    svalue = str(raw_value)

                if json_key in ["total_battery_percent", "battery_range_start", "battery_range_end"] or json_key.endswith("_battery_percent"):
                    nvalue = int(float(raw_value))
                elif json_key in ["ac_output_on", "dc_output_on", "grid_charge_on", "time_control_on"]:
                    nvalue = 1 if raw_value else 0
                elif json_key == "ups_mode":
                    nvalue = 2
                    svalue = str(int(raw_value.value) * 10)
                elif json_key == "ac_output_mode":
                    nvalue = 2
                    svalue = str((raw_value.value + 1) * 10)
                else:
                    nvalue = 0

                changed = (nvalue != curr_nval or svalue != curr_sval)

                if changed: 
                    Devices[unit].Update(nValue=nvalue, sValue=svalue, TimedOut=0)
                    Domoticz.Log(f"Updated Unit {unit} ({json_key}) to nVal:{nvalue}, sVal:'{svalue}'")
                    
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
                        bluetti_val = int(Level) // 10
                        if 1 <= bluetti_val <= 4:
                            cmd_details = {"register": 3001, "value": bluetti_val}
                    except ValueError: 
                        Domoticz.Error(f"Invalid Level '{Level}' for UPS Mode.")
                elif key == "ac_output_mode":
                    try: 
                        bluetti_val = (int(Level) // 10) - 1 
                        if bluetti_val >= 0:
                            cmd_details = {"register": 3002, "value": bluetti_val}
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
