# Domoticz Python Plugin for Bluetti AC500 (Standalone Version)
# Author: lemassykoi
# Version: 0.6.0 - Full AGENTS.md conformity
#
"""
<plugin key="Bluetti-AC500" name="Bluetti AC500 Poller via BLE" author="lemassykoi" version="0.6.0" wikilink="https://github.com/lemassykoi/Domoticz-Bluetti-Plugin" externallink="https://www.bluettipower.eu/">
    <description>
        <h2>Bluetti AC500 BLE Plugin</h2><br/>
        Monitor and control Bluetti AC500 power station over Bluetooth Low Energy.
    </description>
    <params>
        <param field="Address" label="Bluetti MAC Address" width="200px" required="true" default="B8:D6:1A:XX:XX:XX"/>
        <param field="Mode1" label="Polling Interval (seconds)" width="75px" required="true" default="20"/>
        <param field="Mode4" label="Room Plan Name" width="200px" required="false" default="Bluetti AC500"/>
        <param field="Mode6" label="Debug" width="150px">
            <options>
                <option label="None" value="0" default="true"/>
                <option label="Plugin Debug" value="2"/>
                <option label="All" value="1"/>
            </options>
        </param>
        <param field="Port" label="BLE Adapter (e.g., hci0, default empty for auto)" width="150px" required="false" default=""/>
    </params>
</plugin>
"""

import Domoticz  # type: ignore
import threading as _threading
import queue as _queue
import time
import json
import sys
import urllib.parse
from enum import Enum, unique

try:
    from bluetti_standalone import create_client
except ImportError as e:
    error_msg = f"Bluetti BLE AC500 Plugin ERROR: Failed to import bluetti_standalone. Error: {e}"
    sys.stderr.write(error_msg + "\n")
    try:
        Domoticz.Error(error_msg)
    except NameError:
        pass
    raise

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

BLUETTI_DEVICE_DEFINITIONS = [
    # Name,                        UnitID, TypeName,        Type, Subtype, DevIDSfx, SwTypeCr, ImgCr, OptsSelector, OptsCreation, JSONKey, Used
    ("Bluetti Device Type",           1,  "Text",             243, 19, "devtype",        0, 0, {}, {}, "device_type",           0),
    ("Bluetti Serial Number",         2,  "Text",             243, 19, "serial",         0, 0, {}, {}, "serial_number",         0),
    ("Bluetti ARM Version",           3,  "Text",             243, 19, "arm",            0, 0, {}, {}, "arm_version",           0),
    ("Bluetti DSP Version",           4,  "Text",             243, 19, "dsp",            0, 0, {}, {}, "dsp_version",           0),
    ("Bluetti Total Battery",         5,  "Percentage",       243, 6,  "totalbatt",      0, 0, {}, {}, "total_battery_percent", 1),
    ("Bluetti DC Input Power",        6,  "kWh",              243, 29, "dcinpow",        0, 0, {}, {"EnergyMeterMode": "1"}, "dc_input_power",          0),
    ("Bluetti AC Input Power",        7,  "kWh",              243, 29, "acinpow",        0, 0, {}, {"EnergyMeterMode": "1"}, "ac_input_power",          1),
    ("Bluetti AC Output Power",       8,  "kWh",              243, 29, "acoutpow",       0, 0, {}, {"EnergyMeterMode": "1"}, "ac_output_power",         1),
    ("Bluetti DC Output Power",       9,  "kWh",              243, 29, "dcoutpow",       0, 0, {}, {"EnergyMeterMode": "1"}, "dc_output_power",         0),
    ("Bluetti Power Generation",      10, "kWh",              243, 29, "pwrgen",         4, 0, {}, {"EnergyMeterMode": "1"}, "power_generation",        0),
    ("Bluetti Internal DC Power",     25, "kWh",              243, 29, "intdcpower",     0, 0, {}, {"EnergyMeterMode": "1"}, "internal_dc_input_power", 0),
    ("Bluetti AC Charging Power",     27, "kWh",              243, 29, "acchargepow",    0, 0, {}, {"EnergyMeterMode": "1"}, "ac_charging_power",       0),
    ("Bluetti AC Output State",       11, "Switch",           244, 73, "acoutstate",     0, 9, {}, {}, "ac_output_on",              1),
    ("Bluetti DC Output State",       12, "Switch",           244, 73, "dcoutstate",     0, 9, {}, {}, "dc_output_on",              1),
    ("Bluetti Grid Charge",           28, "Switch",           244, 73, "gridcharge",     0, 9, {}, {}, "grid_charge_on",            1),
    ("Bluetti Time Control",          29, "Switch",           244, 73, "timecontrol",    0, 9, {}, {}, "time_control_on",           1),
    ("Bluetti Battery Range Start",   60, "Percentage",       243, 6,  "battrangestart", 0, 0, {}, {}, "battery_range_start",       0),
    ("Bluetti Battery Range End",     61, "Percentage",       243, 6,  "battrangeend",   0, 0, {}, {}, "battery_range_end",         0),
    ("Bluetti Battery Range Start Control", 63, "Dimmer",     244, 73, "battrangestartctrl", 7, 0, {}, {}, "battery_range_start_control", 1),
    ("Bluetti Battery Range End Control",   64, "Dimmer",     244, 73, "battrangeendctrl",   7, 0, {}, {}, "battery_range_end_control",   1),
    ("Bluetti Time Schedule",         62, "Text",             243, 19, "timeschedule",   0, 0, {}, {}, "time_control_programming",  1),
    ("Bluetti Internal AC Voltage",   14, "Voltage",          243, 8,  "intacvolt",      0, 0, {}, {}, "internal_ac_voltage",       0),
    ("Bluetti Internal AC Frequency", 17, "Custom",           243, 31, "intacfreq",      0, 0, {}, {}, "internal_ac_frequency",     0),
    ("Bluetti AC Input Voltage",      20, "Voltage",          243, 8,  "acinvolt",       0, 0, {}, {}, "ac_input_voltage",          0),
    ("Bluetti Internal Current 3",    21, "Current (Single)", 243, 23, "intcurr3",       0, 0, {}, {}, "internal_current_three",    0),
    ("Bluetti AC Input Frequency",    23, "Custom",           243, 31, "acinfreq",       0, 0, {}, {}, "ac_input_frequency",        0),
    ("Bluetti Internal DC Voltage",   24, "Voltage",          243, 8,  "intdcvolt",      0, 0, {}, {}, "internal_dc_input_voltage", 0),
    ("Bluetti Internal DC Current",   26, "Current (Single)", 243, 23, "intdccurr",      0, 0, {}, {}, "internal_dc_input_current", 0),
    ("Bluetti AC Output Mode",        13, "Selector Switch",  244, 62, "acoutmode",     18, 0, {"LevelActions": "|||||", "LevelNames": "Off|Stop|Inverter Output|Bypass Output C|Bypass Output D|Load Matching", "LevelOffHidden": "false", "SelectorStyle": "1"}, {}, "ac_output_mode", 0),
    ("Bluetti UPS Mode",              30, "Selector Switch",  244, 62, "upsmode",       18, 0, {"LevelActions": "||||", "LevelNames": "Off|Customized|PV Priority|Standard|Time Control", "LevelOffHidden": "false", "SelectorStyle": "1"}, {}, "ups_mode", 1),
]

PACK_DEVICE_UNIT_START_OFFSET = 35
PACK_DEVICE_DEFINITIONS = [
    ("Total Voltage", "Voltage",    243, 8, "packtv",   0, 0, {}, {}, "total_voltage",   0),
    ("Voltage",       "Voltage",    243, 8, "packv",    0, 0, {}, {}, "pack_voltage",    0),
    ("Battery",       "Percentage", 243, 6, "packbatt", 0, 0, {}, {}, "battery_percent", 1),
]

_domoticz_port = None

def get_domoticz_http_port():
    try:
        with open("/proc/self/cmdline", "rb") as f:
            args = [a.decode() for a in f.read().split(b'\x00') if a]
        for i, arg in enumerate(args):
            if arg == "-www" and i + 1 < len(args):
                return int(args[i + 1])
    except Exception:
        pass
    return None


class RoomPlanManager:
    def __init__(self):
        self.conn = None
        self.plan_name = ""
        self.state = "IDLE"
        self.plan_idx = None
        self.plan_device_set = set()
        self.pending_add = []

    def start(self, plan_name, port, created_device_idxs):
        self.plan_name = plan_name
        self.pending_add = [str(x) for x in created_device_idxs if x is not None]
        if not self.pending_add or not self.plan_name or not port:
            return
        self.conn = Domoticz.Connection(
            Name="DomoticzPlanHTTP", Transport="TCP/IP", Protocol="HTTP",
            Address="127.0.0.1", Port=str(port)
        )
        self.state = "GET_PLANS"
        self.conn.Connect()

    def on_connect(self, status, description):
        if status != 0:
            Domoticz.Error(f"PlanHTTP connect failed: {description}")
            self.state = "ERROR"
            return
        self._send_next()

    def on_message(self, data):
        try:
            raw = data.get("Data", b"") if isinstance(data, dict) else data
            obj = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
        except Exception as e:
            Domoticz.Error(f"PlanHTTP invalid JSON: {e}")
            self.state = "ERROR"
            return
        self._handle_response(obj)
        self._send_next()

    def _send_api(self, params):
        qs = urllib.parse.urlencode(params)
        self.conn.Send({"Verb": "GET", "URL": f"/json.htm?{qs}",
                        "Headers": {"Host": "127.0.0.1", "Accept": "application/json",
                                    "Connection": "keep-alive"}})

    def _send_next(self):
        if self.state in ("IDLE", "DONE", "ERROR"):
            return
        if self.state == "GET_PLANS" or self.state == "GET_PLANS_AFTER_CREATE":
            self._send_api({"type": "command", "param": "getplans", "order": "name", "used": "true"})
        elif self.state == "ADD_PLAN":
            self._send_api({"type": "command", "param": "addplan", "name": self.plan_name})
        elif self.state == "GET_PLAN_DEVICES":
            self._send_api({"type": "command", "param": "getplandevices", "idx": int(self.plan_idx)})
        elif self.state == "ADD_DEVICE_NEXT":
            self._add_next_device()

    def _add_next_device(self):
        while self.pending_add:
            dev_idx = self.pending_add.pop(0)
            if dev_idx in self.plan_device_set:
                Domoticz.Debug(f"Device IDX {dev_idx} already in plan - skipping")
                continue
            Domoticz.Log(f"Adding device IDX {dev_idx} to plan IDX {self.plan_idx}...")
            self._send_api({"type": "command", "param": "addplanactivedevice",
                            "activeidx": int(dev_idx), "activetype": 0, "idx": int(self.plan_idx)})
            return
        self.state = "DONE"
        Domoticz.Log(f"Room plan '{self.plan_name}' sync complete.")

    def _handle_response(self, obj):
        if obj.get("status") != "OK" and self.state != "GET_PLAN_DEVICES":
            Domoticz.Error(f"PlanHTTP API error in state {self.state}: {obj}")
            self.state = "ERROR"
            return

        if self.state in ("GET_PLANS", "GET_PLANS_AFTER_CREATE"):
            found = None
            for p in obj.get("result", []) or []:
                if p.get("Name") == self.plan_name:
                    found = p.get("idx")
                    break
            if found:
                Domoticz.Log(f"Found room plan '{self.plan_name}' with IDX: {found}")
                self.plan_idx = found
                self.state = "GET_PLAN_DEVICES"
            elif self.state == "GET_PLANS":
                Domoticz.Log(f"Room plan '{self.plan_name}' not found. Creating it...")
                self.state = "ADD_PLAN"
            else:
                Domoticz.Error(f"Created plan '{self.plan_name}' but failed to find its IDX.")
                self.state = "ERROR"

        elif self.state == "ADD_PLAN":
            Domoticz.Log(f"Room plan '{self.plan_name}' created. Re-fetching IDX...")
            self.state = "GET_PLANS_AFTER_CREATE"

        elif self.state == "GET_PLAN_DEVICES":
            self.plan_device_set = set()
            for d in obj.get("result", []) or []:
                devidx = d.get("devidx")
                if devidx is not None:
                    self.plan_device_set.add(str(devidx))
            self.state = "ADD_DEVICE_NEXT"

        elif self.state == "ADD_DEVICE_NEXT":
            pass


class BasePlugin:
    def __init__(self):
        self.bluetti_mac_address = None
        self.polling_interval = 20
        self.bluetti_client = None
        self.update_thread = None
        self.shutdown_event = None
        self.command_queue = _queue.Queue()
        self.message_queue = _queue.Queue()
        self.device_unit_map = {}
        self.next_poll_time = 0
        self.planMgr = RoomPlanManager()
        return

    def onStart(self):
        Domoticz.Log("onStart: Initializing Standalone Plugin...")
        if Parameters["Mode6"] != "0":
            Domoticz.Debugging(int(Parameters["Mode6"]))
            DumpConfigToLog()

        global _domoticz_port
        domoticz_http_port = get_domoticz_http_port()
        if domoticz_http_port is not None:
            Domoticz.Log(f"Domoticz detected HTTP Port: {domoticz_http_port}")
            _domoticz_port = domoticz_http_port
        else:
            Domoticz.Error("Failed to detect Domoticz HTTP Port")

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

        Domoticz.Log(f"onStart: Parameters loaded. MAC: {self.bluetti_mac_address}, Poll:{self.polling_interval}s")

        created_device_idxs = self.create_domoticz_devices()

        self.shutdown_event = _threading.Event()
        self.update_thread = _threading.Thread(name="BluettiUpdateThread", target=self.handle_thread)
        self.update_thread.start()

        Domoticz.Heartbeat(10)

        room_plan_name = Parameters.get("Mode4", "Bluetti AC500").strip() or "Bluetti AC500"
        if _domoticz_port and created_device_idxs:
            self.planMgr.start(room_plan_name, _domoticz_port, created_device_idxs)

        Domoticz.Log("onStart: Standalone plugin started successfully.")

    def create_domoticz_devices(self):
        Domoticz.Log("create_domoticz_devices: Starting device check/creation...")
        plugin_key = Parameters["Key"]
        created_device_idxs = []

        for name, unit_id, type_name, d_type, d_subtype, device_id_suffix, d_switchtype, d_image, create_opts_selector, update_opts_general, json_key, used in BLUETTI_DEVICE_DEFINITIONS:
            full_device_id = f"{plugin_key}_{device_id_suffix}"

            if unit_id not in Devices:
                Domoticz.Log(f"Creating Unit {unit_id} ('{name}')...")
                Domoticz.Device(
                    Name       = str(name),
                    Unit       = int(unit_id),
                    TypeName   = str(type_name),
                    Switchtype = int(d_switchtype),
                    Image      = int(d_image),
                    Options    = dict(update_opts_general),
                    DeviceID   = full_device_id,
                    Used       = int(used)
                ).Create()

                if unit_id in Devices:
                    created_device_idxs.append(Devices[unit_id].ID)

                if unit_id in Devices and update_opts_general:
                    try:
                        current_dev_options = Devices[unit_id].Options if hasattr(Devices[unit_id], 'Options') else {}
                        effective_options = current_dev_options.copy()

                        options_changed = False
                        for opt_key, opt_value in update_opts_general.items():
                            if str(effective_options.get(opt_key)) != str(opt_value):
                                effective_options[opt_key] = opt_value
                                options_changed = True

                        if options_changed:
                            Devices[unit_id].Update(nValue=Devices[unit_id].nValue, sValue="0;0", Options=effective_options)

                    except Exception as e:
                        Domoticz.Error(f"Error applying update options to {name}: {e}")

                elif unit_id in Devices and create_opts_selector:
                    try:
                        Devices[unit_id].Update(nValue=0, sValue="0", Options=create_opts_selector)
                    except Exception as e:
                        Domoticz.Error(f"Error applying selector options to {name}: {e}")

                elif unit_id in Devices and type_name == 'Custom':
                    try:
                        Devices[unit_id].Update(nValue=0, sValue="50.0", Options={'Custom': '1;Hertz'})
                    except Exception as e:
                        Domoticz.Error(f"Error applying custom options to {name}: {e}")
            else:
                Domoticz.Log(f"Found existing Unit {unit_id} ('{name}')...")

            self.device_unit_map[json_key] = unit_id

        for pack_num in [2, 4]:
            for i, (name_suffix, type_name_pack, d_type_pack, d_subtype_pack, device_id_suffix_pack, d_switchtype_pack, d_image_pack, create_opts_selector_pack, update_opts_general_pack, json_key_suffix, used_pack) in enumerate(PACK_DEVICE_DEFINITIONS):
                unit_id_pack = PACK_DEVICE_UNIT_START_OFFSET + ((pack_num - 1) * len(PACK_DEVICE_DEFINITIONS)) + i + 1
                dev_name_pack = f"Bluetti Pack {pack_num} {name_suffix}"
                json_key_pack = f"pack_{pack_num}_{json_key_suffix}"
                full_device_id_pack = f"{plugin_key}_pack{pack_num}_{device_id_suffix_pack}"

                if unit_id_pack not in Devices:
                    Domoticz.Log(f"Creating Unit {unit_id_pack} ('{dev_name_pack}')...")
                    Domoticz.Device(Name=dev_name_pack, Unit=unit_id_pack, TypeName=type_name_pack, DeviceID=full_device_id_pack, Used=used_pack).Create()
                    if unit_id_pack in Devices:
                        created_device_idxs.append(Devices[unit_id_pack].ID)
                else:
                    Domoticz.Log(f"Found existing Unit {unit_id_pack} ('{dev_name_pack}')...")

                self.device_unit_map[json_key_pack] = unit_id_pack

        Domoticz.Log(f"Device map populated with {len(self.device_unit_map)} entries.")
        return created_device_idxs

    def handle_thread(self):
        Domoticz.Log("Update thread started with standalone client.")

        connected = False
        retry_count = 0
        max_retries = 10
        retry_delay = 5

        try:
            Domoticz.Log("Initializing standalone Bluetti client...")
            self.bluetti_client = create_client(self.bluetti_mac_address)

            Domoticz.Log("Starting standalone client...")
            self.bluetti_client.start()
            self.shutdown_event.wait(1.0)

            while not self.shutdown_event.is_set():
                try:
                    if not connected:
                        Domoticz.Log(f"Attempting to connect to Bluetti device... (attempt {retry_count + 1}/{max_retries})")
                        connection_start = time.time()

                        if self.bluetti_client.connect():
                            connection_duration = time.time() - connection_start
                            Domoticz.Log(f"Connected to Bluetti device successfully (took {connection_duration:.1f}s)")
                            connected = True
                            retry_count = 0
                        else:
                            connection_duration = time.time() - connection_start
                            retry_count += 1
                            if retry_count <= max_retries:
                                Domoticz.Error(f"Failed to connect to Bluetti device (took {connection_duration:.1f}s). Retry {retry_count}/{max_retries} in {retry_delay}s...")
                                self.shutdown_event.wait(retry_delay)
                            else:
                                Domoticz.Error(f"Failed to connect after {max_retries} attempts. Will retry on next heartbeat cycle.")
                                retry_count = 0
                                self.shutdown_event.wait(30)
                            continue

                    if connected:
                        try:
                            item = self.command_queue.get_nowait()
                            if item == "POLL_DATA":
                                self._poll_data()
                            elif isinstance(item, dict) and item.get("action") == "SEND_COMMAND":
                                if not self._send_command(item['details']):
                                    connected = False
                                    self.message_queue.put({"Type": "Log", "Text": "Command failed, connection may be lost..."})
                            self.command_queue.task_done()
                        except _queue.Empty:
                            pass

                    self.shutdown_event.wait(1.0)

                except Exception as e:
                    Domoticz.Error(f"Thread loop error: {e}")
                    connected = False
                    self.shutdown_event.wait(5)

        except Exception as e:
            Domoticz.Error(f"Thread handler error: {e}")
        finally:
            try:
                if self.bluetti_client:
                    Domoticz.Log("Disconnecting standalone client...")
                    self.bluetti_client.stop()
                    Domoticz.Log("Standalone client stopped")
            except Exception as e:
                Domoticz.Error(f"Error stopping client in thread: {e}")
            finally:
                self.bluetti_client = None
                Domoticz.Log("Update thread finished.")

    def _poll_data(self):
        try:
            Domoticz.Debug("Polling Bluetti data...")
            data = self.bluetti_client.poll_data()

            if data:
                self.message_queue.put(data)
                Domoticz.Debug(f"Queued {len(data)} fields for Domoticz update")
                return True
            else:
                Domoticz.Error("No data received from Bluetti device")
                return False

        except Exception as e:
            Domoticz.Error(f"Polling error: {e}")
            return False

    def _send_command(self, command_details):
        try:
            register = command_details.get("register")
            value = command_details.get("value")

            if register is not None and value is not None:
                Domoticz.Debug(f"Sending command: register={register}, value={value}")
                success = self.bluetti_client.send_command(register, value)

                if success:
                    Domoticz.Log(f"Command sent: register={register}, value={value}")
                    self.shutdown_event.wait(5)
                    self.command_queue.put("POLL_DATA")
                    return True
                else:
                    Domoticz.Error("Command failed")
                    return False
            else:
                Domoticz.Error(f"Invalid command details: {command_details}")
                return False

        except Exception as e:
            Domoticz.Error(f"Command error: {e}")
            return False

    def _decode_time_schedule(self, time_control_data):
        try:
            def decode_bluetti_time(value):
                if value == 0:
                    return "00:00"
                hours = value // 256
                minutes = value % 256
                if hours <= 23 and minutes <= 59:
                    return f"{hours:02d}:{minutes:02d}"
                return f"Raw:{value}"

            if not isinstance(time_control_data, dict):
                return "Invalid data"

            values = []
            for i in range(3039, 3057):
                reg_key = f'time_control_reg_{i}'
                if reg_key in time_control_data:
                    values.append(time_control_data[reg_key])
                else:
                    values.append(0)

            time_values = []
            seen_times = set()
            for value in values:
                if value > 256 and value not in seen_times:
                    time_values.append(value)
                    seen_times.add(value)

            if len(time_values) >= 3:
                time_values.sort()
                schedule_parts = []
                times = [decode_bluetti_time(val) for val in time_values[:4]]

                if len(times) >= 3:
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
        Domoticz.Log(f"Processing {len(bluetti_data_fields)} fields for Domoticz update.")

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

                Domoticz.Debug(f"Processing {json_key}={raw_value} for Unit {unit}, current nVal={curr_nval}, sVal='{curr_sval}'")

                if json_key in ["device_type","serial_number","arm_version","dsp_version"]:
                    if json_key == "device_type":
                        clean_value = ''.join(c for c in str(raw_value) if c.isprintable() and c not in '\x00\x03')
                        if "AC500" in clean_value or "PAC500" in clean_value:
                            svalue = "AC500"
                        else:
                            svalue = clean_value
                    else:
                        svalue = str(raw_value)
                    nvalue = curr_nval
                    changed = (svalue != curr_sval)

                elif json_key.endswith(("_total_voltage","_pack_voltage")) or json_key in ["internal_ac_voltage","ac_input_voltage","internal_dc_input_voltage"]:
                    svalue = f"{float(raw_value)}"
                    nvalue = 0
                    changed = (svalue != curr_sval)

                elif json_key in ["internal_current_one","internal_current_two","internal_current_three","internal_dc_input_current"]:
                    svalue = f"{float(raw_value)}"
                    nvalue = 0
                    changed = (svalue != curr_sval)

                elif json_key in ["total_battery_percent"] or json_key.endswith("_battery_percent"):
                    svalue = str(int(round(float(raw_value))))
                    nvalue = int(svalue)
                    changed = (nvalue != curr_nval or svalue != curr_sval)

                elif json_key in ["internal_ac_frequency","ac_input_frequency"]:
                    svalue = f"{float(raw_value)}"
                    nvalue = curr_nval
                    changed = (svalue != curr_sval)

                elif json_key in ["dc_input_power","ac_input_power","ac_output_power","dc_output_power","power_generation","ac_charging_power"]:
                    power_val = int(raw_value)
                    svalue = f"{power_val};0"
                    nvalue = 0
                    changed = (svalue != curr_sval)

                elif json_key in ["internal_power_one","internal_power_two","internal_power_three","internal_dc_input_power"]:
                    svalue = f"{float(raw_value)};0"
                    nvalue = 0
                    changed = (svalue.split(';')[0] != (curr_sval.split(';')[0] if ';' in curr_sval else curr_sval))

                elif json_key in ["ac_output_on","dc_output_on","grid_charge_on","time_control_on"]:
                    nvalue = 1 if raw_value else 0
                    svalue = str(nvalue)
                    changed = (nvalue != curr_nval)

                elif json_key == "ac_output_mode":
                    mode_names = ["Stop", "Inverter Output", "Bypass Output C", "Bypass Output D", "Load Matching"]
                    raw_int = int(raw_value)
                    if raw_int < len(mode_names):
                        mode_text = mode_names[raw_int]
                        level = (raw_int + 1) * 10
                    else:
                        mode_text = f"Mode {raw_value}"
                        level = 0

                    nvalue = 2
                    svalue = str(level)
                    changed = (str(level) != curr_sval or curr_nval != 2)
                    Domoticz.Debug(f"AC Output Mode: raw={raw_value}, decoded='{mode_text}', level={level}")

                elif json_key == "ups_mode":
                    mode_names = ["Customized", "PV Priority", "Standard", "Time Control"]
                    raw_int = int(raw_value)
                    if 1 <= raw_int <= len(mode_names):
                        mode_text = mode_names[raw_int - 1]
                        level = raw_int * 10
                    else:
                        mode_text = f"Mode {raw_value}"
                        level = 0

                    nvalue = 2
                    svalue = str(level)
                    changed = (str(level) != curr_sval or curr_nval != 2)
                    Domoticz.Debug(f"UPS Mode: raw={raw_value}, decoded='{mode_text}', level={level}")

                elif json_key in ["battery_range_start", "battery_range_end"]:
                    if isinstance(raw_value, (int, float)) and 0 <= raw_value <= 100:
                        nvalue = int(raw_value)
                        svalue = str(int(raw_value))

                        control_key = f"{json_key}_control"
                        if control_key in self.device_unit_map:
                            control_unit = self.device_unit_map[control_key]
                            if control_unit in Devices:
                                Devices[control_unit].Update(nValue=2, sValue=str(int(raw_value)), TimedOut=0)
                                Domoticz.Debug(f"Updated control Unit {control_unit} ({control_key}) to {int(raw_value)}%")
                    else:
                        nvalue = 0
                        svalue = f"Raw: {raw_value}"
                    changed = (svalue != curr_sval or nvalue != curr_nval)

                elif json_key == "time_control_programming":
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
                    Devices[unit].Update(nValue=nvalue, sValue=str(svalue), TimedOut=0)
                    Domoticz.Debug(f"Updated Unit {unit} ({json_key}) to nVal:{nvalue}, sVal:'{svalue}'")

            except Exception as e:
                Domoticz.Error(f"Error processing field '{json_key}' for Unit {unit}: {e}")

    def onStop(self):
        Domoticz.Log("onStop: Stopping standalone plugin...")

        if self.shutdown_event:
            self.shutdown_event.set()

        if self.update_thread and self.update_thread.is_alive():
            self.update_thread.join(timeout=30.0)
            if self.update_thread.is_alive():
                Domoticz.Error("BluettiUpdateThread did not stop in time")
            else:
                Domoticz.Log("All threads stopped successfully")

        self.bluetti_client = None
        self.shutdown_event = None
        self.update_thread = None
        self.command_queue = None
        self.message_queue = None
        Domoticz.Log("Plugin stopped.")

    def onHeartbeat(self):
        Domoticz.Debug("onHeartbeat called")

        while not self.message_queue.empty():
            try:
                msg = self.message_queue.get_nowait()
                self._update_domoticz_devices(msg)
                self.message_queue.task_done()
            except _queue.Empty:
                break

        if not (self.update_thread and self.update_thread.is_alive()):
            Domoticz.Debug("Update thread not running (this is normal during connection retry cycles)")
            return

        current_time = time.time()
        if current_time >= self.next_poll_time:
            if self.command_queue:
                Domoticz.Debug("Queueing POLL_DATA request.")
                self.command_queue.put("POLL_DATA")
                self.next_poll_time = current_time + self.polling_interval
            else:
                Domoticz.Error("Command queue not initialized.")

    def onCommand(self, Unit, Command, Level, Hue):
        Domoticz.Log(f"onCommand called for Unit {Unit}: Command '{Command}', Level: {Level}")

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
                        else:
                            Domoticz.Error(f"Invalid Level '{Level}' for UPS Mode")
                    except ValueError:
                        Domoticz.Error(f"Invalid Level '{Level}' for UPS Mode.")
                elif key == "battery_range_start_control":
                    try:
                        battery_val = int(Level)
                        if 0 <= battery_val <= 100:
                            cmd_details = {"register": 3015, "value": battery_val}
                        else:
                            Domoticz.Error(f"Invalid Level '{Level}' for Battery Range Start (must be 0-100)")
                    except ValueError:
                        Domoticz.Error(f"Invalid Level '{Level}' for Battery Range Start.")
                elif key == "battery_range_end_control":
                    try:
                        battery_val = int(Level)
                        if 0 <= battery_val <= 100:
                            cmd_details = {"register": 3016, "value": battery_val}
                        else:
                            Domoticz.Error(f"Invalid Level '{Level}' for Battery Range End (must be 0-100)")
                    except ValueError:
                        Domoticz.Error(f"Invalid Level '{Level}' for Battery Range End.")

                if cmd_details:
                    break

        if cmd_details:
            if self.command_queue:
                self.command_queue.put({"action": "SEND_COMMAND", "details": cmd_details})
                Domoticz.Log(f"Queued command for Unit {Unit}: {cmd_details}")
                self._optimistic_update(Unit, key, Command, Level)
            else:
                Domoticz.Error("Command queue not available.")
        else:
            Domoticz.Log(f"No Bluetti action for Unit {Unit}, Command '{Command}'.")

    def _optimistic_update(self, unit, key, command, level):
        if unit not in Devices:
            return
        if key in ["ac_output_on", "dc_output_on", "grid_charge_on", "time_control_on"]:
            nval = 1 if str(command).lower() == "on" else 0
            Devices[unit].Update(nValue=nval, sValue=str(nval), TimedOut=0)
        elif key == "ups_mode":
            Devices[unit].Update(nValue=2, sValue=str(int(level)), TimedOut=0)
        elif key in ["battery_range_start_control", "battery_range_end_control"]:
            Devices[unit].Update(nValue=2, sValue=str(int(level)), TimedOut=0)

    def onConnect(self, Connection, Status, Description):
        if Connection.Name == "DomoticzPlanHTTP":
            self.planMgr.on_connect(Status, Description)
            return

    def onMessage(self, Connection, Data):
        if Connection.Name == "DomoticzPlanHTTP":
            self.planMgr.on_message(Data)
            return

global _plugin
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

def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()

def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            if x == "Password":
                Domoticz.Debug(f"'{x}':'***HIDDEN***'")
            else:
                Domoticz.Debug(f"'{x}':'{Parameters[x]}'")
    Domoticz.Debug(f"Device count: {len(Devices)}")
    for x in Devices:
        Domoticz.Debug(f"Device: {x} - {Devices[x]}")
        Domoticz.Debug(f"Device ID:       '{Devices[x].ID}'")
        Domoticz.Debug(f"Device Name:     '{Devices[x].Name}'")
        Domoticz.Debug(f"Device nValue:    {Devices[x].nValue}")
        Domoticz.Debug(f"Device sValue:   '{Devices[x].sValue}'")
        Domoticz.Debug(f"Device LastLevel: {Devices[x].LastLevel}")
