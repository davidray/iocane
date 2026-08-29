# Bluetooth LE driver for "LuckPrinter SDK" thermal label printers (sold
# under many rebrand names - NHOWIN, C&Co 3128, DP-L1S, PPS1, etc). Protocol
# reverse-engineered from the decompiled Luck Jingle Android app by
# https://github.com/ChiaraCannolee/thermal-pocket-printer-basic (MIT); see
# NOTICE.md for credits. Standard ESC/POS GS v 0 raster image command with a
# handful of vendor-specific control commands layered on top.

import asyncio

from PIL import Image, ImageDraw, ImageFont

from .dither import floyd_steinberg_dither

# GATT characteristics exposed by the printer's custom BLE service.
CHARACTERISTIC_NOTIFY = "0000ff01-0000-1000-8000-00805f9b34fb"
CHARACTERISTIC_WRITE = "0000ff02-0000-1000-8000-00805f9b34fb"

DEFAULT_WIDTH = 384  # dots; standard for 48mm/58mm 203dpi thermal heads
DEFAULT_FEED_DOTS = 80
CHUNK_SIZE = 512
CHUNK_DELAY = 0.01
COMMAND_DELAY = 0.3


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
    """Thin wrapper around a bleak BLE connection to the printer."""

    def __init__(self, address: str):
        self.address = address
        self.client = None

    async def open(self):
        import bleak

        self.client = bleak.BleakClient(self.address, timeout=15.0)
        await self.client.connect()
        await self.client.start_notify(CHARACTERISTIC_NOTIFY, lambda *_: None)

    async def close(self):
        if self.client is not None:
            await self.client.disconnect()

    async def write(self, data: bytes):
        # write-with-response: gives ATT-level flow control so we don't
        # outrun the printer's receive buffer on long images (writes
        # without response were silently dropping data past a certain
        # point, truncating tall prints with no error).
        await self.client.write_gatt_char(CHARACTERISTIC_WRITE, data, response=True)


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


def _image_to_bitmap(img: Image.Image, width_px: int) -> tuple[bytes, int, int]:
    """Convert a grayscale PIL image to 1-bit MSB-first bitmap bytes (dark
    pixel = 1). Returns (bitmap_bytes, width_bytes, height_px)."""
    width_bytes = (width_px + 7) // 8
    height_px = img.height
    pixels = list(img.getdata())

    bitmap = bytearray(width_bytes * height_px)
    for y in range(height_px):
        for xb in range(width_bytes):
            byte_val = 0
            for bit in range(8):
                x = xb * 8 + bit
                if x < width_px and pixels[y * width_px + x] < 128:
                    byte_val |= 128 >> bit
            bitmap[y * width_bytes + xb] = byte_val

    return bytes(bitmap), width_bytes, height_px


def _build_gs_v_0(bitmap_data: bytes, width_bytes: int, height_px: int, mode: int = 0) -> bytes:
    """Build an ESC/POS `GS v 0` raster image command."""
    header = bytes(
        [
            0x1D,
            0x76,
            0x30,
            mode & 0x03,
            width_bytes % 256,
            width_bytes // 256,
            height_px % 256,
            height_px // 256,
        ]
    )
    return header + bitmap_data


class LuckPrinter:
    """High level printer API: connect, print text/images, feed and finish."""

    def __init__(
        self,
        device,
        width: int = DEFAULT_WIDTH,
        density: int | None = None,
        font_path: str | None = None,
    ):
        self.device = device
        self.width = width
        self.density = density
        self.font_path = font_path

    async def initialize(self):
        await self.device.open()

    async def close(self):
        await self.device.close()

    async def _write_command(self, data: bytes, wait: float = COMMAND_DELAY):
        await self.device.write(data)
        await asyncio.sleep(wait)

    async def _write_chunked(self, data: bytes):
        for i in range(0, len(data), CHUNK_SIZE):
            await self.device.write(data[i : i + CHUNK_SIZE])
            await asyncio.sleep(CHUNK_DELAY)

    async def print_end(self, feed_dots: int = DEFAULT_FEED_DOTS):
        """Feed a bit of blank paper and end the print job."""
        await self._write_command(bytes([0x1B, 0x4A, feed_dots & 0xFF]))
        await self._write_command(bytes([0x10, 0xFF, 0xF1, 0x45]), wait=2.0)

    def _default_font(self, font_size: int) -> ImageFont.FreeTypeFont:
        candidates = [
            self.font_path,
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
        for path in candidates:
            if not path:
                continue
            try:
                return ImageFont.truetype(path, font_size)
            except OSError:
                continue
        try:
            return ImageFont.load_default(size=font_size)
        except TypeError:
            return ImageFont.load_default()

    async def print_text(self, text: str, font_size: int = 24, align: str = "left"):
        font = self._default_font(font_size)
        margin = 8
        max_width = self.width - 2 * margin

        lines = []
        for raw_line in text.split("\n"):
            words = raw_line.split(" ")
            current = ""
            for word in words:
                trial = f"{current} {word}".strip()
                if font.getlength(trial) <= max_width or not current:
                    current = trial
                else:
                    lines.append(current)
                    current = word
            lines.append(current)

        line_height = font_size + 6
        img_height = line_height * len(lines) + 2 * margin
        img = Image.new("RGB", (self.width, img_height), "white")
        draw = ImageDraw.Draw(img)
        for i, line in enumerate(lines):
            y = margin + i * line_height
            if align == "center":
                x = (self.width - font.getlength(line)) / 2
            elif align == "right":
                x = self.width - margin - font.getlength(line)
            else:
                x = margin
            draw.text((x, y), line, fill="black", font=font)

        await self.print_image(img, dither=False)

    async def print_image(self, img: Image.Image, dither: bool = True):
        img = img.convert("L")
        if img.width != self.width:
            new_height = max(1, int(img.height * self.width / img.width))
            img = img.resize((self.width, new_height), Image.LANCZOS)
        if dither:
            img = floyd_steinberg_dither(img)

        bitmap_data, width_bytes, height_px = _image_to_bitmap(img, self.width)
        gs_command = _build_gs_v_0(bitmap_data, width_bytes, height_px)

        if self.density is not None:
            density = max(0, min(2, self.density))
            await self._write_command(bytes([0x10, 0xFF, 0x10, 0x00, density]))

        # Enable printer, then wake the print head/motor (12 null bytes).
        # Without waking it, the printer accepts the BLE connection and
        # control commands (LED changes state) but never actually engages
        # the print mechanism.
        await self._write_command(bytes([0x10, 0xFF, 0xF1, 0x03]))
        await self._write_command(bytes(12))

        await self._write_chunked(gs_command)
        await asyncio.sleep(0.5)
