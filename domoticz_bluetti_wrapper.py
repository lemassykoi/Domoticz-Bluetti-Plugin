# Domoticz-compatible wrapper for the self-contained bluetti_lib

import logging
from typing import Dict, Any

from bluetti_lib.client import BluettiClient
from bluetti_lib.device import AC500
from bluetti_lib.commands import WriteSingleRegister

class DomoticzBluettiWrapper:
    """Synchronous wrapper for the self-contained bluetti_lib"""

    def __init__(self, mac_address: str, logger=None):
        self.mac_address = mac_address
        self.logger = logger or logging.getLogger(__name__)
        self.client = BluettiClient(mac_address)
        self.device = AC500(mac_address)
        self.fields = {}

    def connect(self) -> bool:
        return self.client.connect()

    def disconnect(self):
        self.client.disconnect()

    def poll_data(self) -> Dict[str, Any]:
        """Polls data from the device"""
        if not self.client.is_connected:
            self.logger.warning("Not connected to device")
            return {}

        self.fields.clear()
        all_data = {}

        # Poll main commands
        for command in self.device.polling_commands:
            response = self.client.perform(command)
            if response:
                parsed = self.device.struct.parse(command.starting_address, response)
                all_data.update(parsed)

        # Poll battery packs
        if hasattr(self.device, 'pack_polling_commands'):
            num_packs_to_iterate = 6
            for pack_idx in range(1, num_packs_to_iterate + 1):
                # Select pack
                selector_command = WriteSingleRegister(3006, pack_idx)
                self.client.perform(selector_command)

                # Poll pack
                for pack_cmd in self.device.pack_polling_commands:
                    response = self.client.perform(pack_cmd)
                    if response:
                        parsed = self.device.struct.parse(pack_cmd.starting_address, response)
                        # Add pack number to keys
                        for key, value in parsed.items():
                            all_data[f'pack_{pack_idx}_{key}'] = value

        return all_data

    def send_command(self, register: int, value: int) -> bool:
        """Sends a command to the device"""
        if not self.client.is_connected:
            self.logger.warning("Not connected to device")
            return False

        command = WriteSingleRegister(register, value)
        response = self.client.perform(command)
        return response is not None

# Alias for compatibility
DomoticzBluettiClient = DomoticzBluettiWrapper
