# Domoticz Plugin for Bluetti AC500

This is a Python plugin for Domoticz to monitor and control the Bluetti AC500 power station via Bluetooth Low Energy (BLE).

## Features

*   Monitors key metrics from the Bluetti AC500, including:
    *   Total battery percentage
    *   AC and DC input/output power
    *   Power generation
    *   Device temperatures and voltages
*   Controls the AC and DC output switches.
*   Supports automatic discovery of the Bluetti device.
*   Customizable polling interval.

## Prerequisites

*   Domoticz 2022.1 or later.
*   Python 3.7 or later.
*   `bleak` and `crcmod` libraries installed.
*   A Bluetooth adapter supported by your operating system.

## Installation

1.  Clone this repository into your Domoticz plugins directory:
    ```bash
    cd /path/to/domoticz/plugins
    git clone https://github.com/lemassykoi/Domoticz-Bluetti-Plugin.git
    ```
2.  Install the required Python libraries:
    ```bash
    pip3 install bleak crcmod
    ```

3.  Restart your Domoticz service.

## Configuration

1.  In the Domoticz web interface, go to **Setup -> Hardware**.
2.  Add a new hardware item with the following settings:
    *   **Type**: "Bluetti AC500 via BLE"
    *   **Name**: A descriptive name for your Bluetti device (e.g., "Bluetti AC500")
    *   **Bluetti MAC Address**: The MAC address of your Bluetti AC500.
    *   **Polling Interval**: The update frequency in seconds (e.g., 20).
3.  Click **Add**. The plugin will automatically create the necessary Domoticz devices.

## Usage

Once configured, the plugin will create several devices in Domoticz to display the Bluetti's status and allow control. These devices will be updated automatically at the specified polling interval.

## Troubleshooting

*   **Plugin not starting**: Check the Domoticz log for any error messages. Ensure the `bleak` and `crcmod` libraries are installed and accessible to the Domoticz user.
*   **Device not found**: Verify the Bluetti MAC address is correct and that the device is within Bluetooth range of your Domoticz server.
*   **Intermittent connection**: Bluetooth signals can be affected by distance and obstacles. Try moving the Domoticz server closer to the Bluetti device.

## Author

This plugin was created by **lemassykoi**.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
