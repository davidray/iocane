# BLE/serial transports for thermal label printers, plus BLE device
# discovery. Protocol-specific command bytes (what to actually send) live
# in luckjingle_mcp/drivers/ - see drivers/base.py for the driver
# interface each printer family implements.

async def scan_devices(timeout: float = 6.0):
    """Scan for nearby BLE devices and return [{"name", "address", "rssi"}],
    sorted by signal strength (strongest/closest first) - the printer is
    almost always the strongest signal since it'll be right next to you."""
    from bleak import BleakScanner

    results = await BleakScanner.discover(timeout=timeout, return_adv=True)
    devices = [
        {
            "name": device.name or "(unknown)",
            "address": device.address,
            "rssi": adv.rssi,
        }
        for device, adv in results.values()
    ]
    devices.sort(key=lambda d: d["rssi"], reverse=True)
    return devices


class BluetoothDevice:
    """Thin wrapper around a bleak BLE connection to the printer. Which
    GATT characteristics to write/notify on is protocol-specific (comes
    from the printer driver), not hardcoded here."""

    def __init__(self, address: str, write_characteristic: str, notify_characteristic: str):
        self.address = address
        self.write_characteristic = write_characteristic
        self.notify_characteristic = notify_characteristic
        self.client = None

    async def open(self):
        import bleak

        self.client = bleak.BleakClient(self.address, timeout=15.0)
        await self.client.connect()
        await self.client.start_notify(self.notify_characteristic, lambda *_: None)

    async def close(self):
        if self.client is not None:
            await self.client.disconnect()

    async def write(self, data: bytes):
        # write-with-response: gives ATT-level flow control so we don't
        # outrun the printer's receive buffer on long images (writes
        # without response were silently dropping data past a certain
        # point, truncating tall prints with no error).
        await self.client.write_gatt_char(self.write_characteristic, data, response=True)


class SerialPortDevice:
    """Alternative transport for printers paired over RFCOMM (Linux)."""

    def __init__(self, path: str):
        self.path = path
        self.device = None

    async def open(self):
        from serial import Serial

        self.device = Serial(self.path)

    async def close(self):
        if self.device is not None:
            self.device.close()

    async def write(self, data: bytes):
        self.device.write(data)
