# Ported from bluetti_mqtt/core/utils.py
# Requires the 'crcmod' library

import crcmod.predefined

modbus_crc = crcmod.predefined.mkCrcFun('modbus')
