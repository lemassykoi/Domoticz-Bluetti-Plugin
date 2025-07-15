# Bluetti AC500 BLE Control Plugin for Domoticz

A standalone Domoticz plugin to control and monitor Bluetti AC500 power stations via Bluetooth Low Energy (BLE).

## Features

- **Real-time monitoring**: Battery level, power input/output, voltage, frequency
- **Device control**: AC/DC output toggle, UPS mode selection, grid charging
- **Time control**: Battery range settings and time-based charging schedules
- **Battery pack monitoring**: Support for multiple battery packs
- **No external dependencies**: Works with latest bleak version, no bluetti_mqtt required

## Requirements

- Domoticz 2025.x.x with Python plugin support
- Raspberry Pi or Linux system with Bluetooth capability
- Python 3.9+
- Bluetti AC500 power station with BLE enabled

## Installation

1. **Clone/download** this plugin to your Domoticz plugins directory:
   ```bash
   cd /home/pi/domoticz/plugins/
   git clone https://github.com/lemassykoi/Domoticz-Bluetti-Plugin.git Domoticz-Bluetti
   ```

2. **Install Python dependencies**:
   ```bash
   cd Domoticz-Bluetti
   pip install -r requirements.txt
   ```

3. **Restart Domoticz** and find your Bluetti MAC address:
   ```bash
   sudo systemctl restart domoticz
   sudo hcitool lescan | grep -i bluetti
   ```

## Configuration

1. Go to **Setup → Hardware** in Domoticz
2. Add hardware type: **Bluetti AC500 Poller via BLE**
3. Enter your Bluetti's **MAC address** (format: XX:XX:XX:XX:XX:XX)
4. Set **polling interval** (default: 20 seconds)
5. Choose **debug level** if needed

## Devices Created

The plugin automatically creates these devices:

### Power Monitoring
- AC Input/Output Power
- DC Input/Output Power  
- Total Battery Percentage
- Battery Pack status (Pack 2 & 4)

### Controls
- AC/DC Output switches
- UPS Mode selector (Customized/PV Priority/Standard/Time Control)
- Grid Charge toggle
- Time Control toggle

<img width="1028" height="849" alt="image" src="https://github.com/user-attachments/assets/99e49748-2f48-4b0a-9296-1ee9fdbaf03a" />

### Advanced
- Battery Range settings (Start/End percentage)
- Time Control Schedule (decoded display)
- Device info (Type, Serial, Firmware versions)

## Troubleshooting

### Connection Issues
- Ensure Bluetti has Bluetooth enabled from LCD Screen
- Only 1 connection is allowed with Bluetooth. If Bluetooth indicates "Connected" on LCD screen, switch it Off, wait for "Disconnected", then switch it On
- Restart Bluetooth service: `sudo systemctl restart bluetooth`
- Check MAC address is correct: `bluetoothctl devices`

### Plugin Not Starting
- Check Domoticz logs
- Verify Python dependencies are installed
- Run `test_standalone.py`

### No Data Updates
- Check polling interval (minimum 5 seconds)
- Verify Bluetooth connection is stable
- Enable debug logging for more details

## Technical Notes

- Compatible with **bleak 1.0+** (latest version)
- Uses **standalone BLE implementation** (no bluetti_mqtt dependency)
- Handles **automatic reconnection** and error recovery
- Supports **Modbus over BLE** communication protocol

## Version History

- **v0.5.0**: Standalone implementation, latest bleak compatibility
- **v0.4.0**: Fully Customized Sensors
- **v0.3.1**: Added UPS mode, battery range, time control features
- **v0.2.1**: Initial BLE implementation

## Thanks

Inspired from https://github.com/ftrueck/bluetti_mqtt

## License

MIT License - feel free to modify and distribute.

## Support

For issues and questions, please check the Domoticz forum or create an issue in this repository.
