# Bluetti AC500 BLE Control Plugin for Domoticz

A standalone Domoticz plugin to control and monitor Bluetti AC500 power stations via Bluetooth Low Energy (BLE).

## Features

- **Real-time monitoring**: Battery level, power input/output, voltage, frequency
- **Device control**: AC/DC output toggle, UPS mode selection, grid charging
- **Time control**: Battery range settings and time-based charging schedules
- **Battery pack monitoring**: Support for multiple battery packs
- **Room plan**: Automatically creates a Domoticz room plan and assigns devices
- **Optimistic UI**: Switch and selector commands reflect instantly in the UI
- **No external dependencies**: Standalone BLE implementation, no bluetti_mqtt required

## Requirements

- Domoticz 2025.x or later with Python plugin support
- Raspberry Pi or Linux system with Bluetooth capability
- Python 3.9+
- Bluetti AC500 power station with BLE enabled

## Installation

1. **Clone** this plugin to your Domoticz plugins directory:
   ```bash
   cd /home/pi/domoticz/plugins/
   git clone https://github.com/lemassykoi/Domoticz-Bluetti-Plugin.git
   ```

2. **Install Python dependencies** (as root, required for the Domoticz embedded interpreter):
   ```bash
   cd Domoticz-Bluetti-Plugin
   sudo pip install -r requirements.txt --break-system-packages
   ```

3. **Find your Bluetti MAC address**:
   ```bash
   sudo hcitool lescan | grep -i bluetti
   ```

4. **Restart Domoticz**:
   ```bash
   sudo systemctl restart domoticz
   ```

## Configuration

1. Go to **Setup → Hardware** in Domoticz
2. Add hardware type: **Bluetti AC500 Poller via BLE**
3. Configure the parameters:

| Parameter | Description | Default |
|-----------|-------------|---------|
| MAC Address | Bluetti BLE address (format: `XX:XX:XX:XX:XX:XX`) | — |
| Polling Interval | Seconds between data polls (minimum 5) | `20` |
| Room Plan Name | Domoticz room plan for auto-assignment | `Bluetti AC500` |
| Debug | Logging level: None / Plugin Debug / All | `None` |
| BLE Adapter | Bluetooth adapter (e.g., `hci0`), leave empty for auto | — |

## Devices Created

The plugin automatically creates these devices:

### Power Monitoring
- AC Input/Output Power (kWh)
- DC Input/Output Power (kWh)
- AC Charging Power (kWh)
- Internal DC Power (kWh)
- Power Generation (kWh)
- Total Battery Percentage

### Controls
- AC/DC Output switches
- UPS Mode selector (Customized / PV Priority / Standard / Time Control)
- Grid Charge toggle
- Grid Charge Current selector (3A / 5A / 7A / 10A) ¹
- Time Control toggle
- Battery Range Start/End (display + dimmer control)

> ¹ **Grid Charge Current** writes to register 3019 which is **write-only**. Reading it always returns 1 regardless of the actual setting. Domoticz shows only the value last set via BLE command (optimistic UI update). Changes made on the AC500 touchscreen will **not** be reflected in Domoticz.

### Battery Packs
- Pack 2 & Pack 4: Total Voltage, Voltage, Battery Percentage

### Info & Advanced
- Device Type, Serial Number, ARM/DSP Firmware versions
- Time Control Schedule (decoded display)
- Internal AC/DC Voltage, Current, Frequency

<img width="1028" height="849" alt="image" src="https://github.com/user-attachments/assets/99e49748-2f48-4b0a-9296-1ee9fdbaf03a" />

## Troubleshooting

### Connection Issues
- Ensure Bluetti has Bluetooth enabled from the LCD screen
- Only **one BLE connection** is allowed at a time. If the LCD shows "Connected", toggle Bluetooth Off, wait for "Disconnected", then switch it back On
- Restart Bluetooth service: `sudo systemctl restart bluetooth`
- Check MAC address: `bluetoothctl devices`

### Plugin Not Starting
- Check Domoticz logs for error messages
- Verify Python dependencies: `pip show bleak crcmod`
- Test BLE connectivity: edit the MAC address in `test_standalone.py` and run `python3 test_standalone.py`

### Plugin Restart Issues
- The plugin runs `bluetoothctl disconnect` on stop to ensure clean BLE release
- If reconnection still fails after a plugin-only restart, restart Domoticz: `sudo systemctl restart domoticz`

### No Data Updates
- Check polling interval (minimum 5 seconds recommended)
- Verify Bluetooth connection is stable
- Enable debug logging (Plugin Debug) for detailed diagnostics

## Technical Notes

- Compatible with **bleak 0.21+** (tested with 2.1.x)
- **Standalone BLE implementation** using Modbus over BLE GATT
- Non-blocking architecture: BLE runs in a worker thread, device updates on the main thread
- Automatic reconnection with exponential backoff (up to 10 retries)
- Thread-safe: all `Devices[].Update()` calls happen in `onHeartbeat` on the main thread

## Version History

- **v0.6.1**: Grid charge current selector (register 3019, write-only), auto-update selector options on existing devices
- **v0.6.0**: Full Domoticz plugin standards conformity, room plan management, optimistic UI, clean plugin restart
- **v0.5.0**: Standalone implementation, latest bleak compatibility
- **v0.4.0**: Fully customized sensors
- **v0.3.1**: Added UPS mode, battery range, time control features
- **v0.2.1**: Initial BLE implementation

## Thanks

Inspired from https://github.com/ftrueck/bluetti_mqtt

Register 3019 (grid charge current) identified via [Mike's Electric Stuff](https://electricstuff.co.uk/bluetti.html)

## License

MIT License - see [LICENSE](LICENSE) file.
