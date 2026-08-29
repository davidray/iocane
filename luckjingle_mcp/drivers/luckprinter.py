# Driver for "LuckPrinter SDK" thermal label printers (sold under many
# rebrand names - NHOWIN, C&Co 3128, DP-L1S, PPS1, etc). Protocol
# reverse-engineered from the decompiled Luck Jingle Android app by
# https://github.com/ChiaraCannolee/thermal-pocket-printer-basic (MIT); see
# NOTICE.md for credits. Standard ESC/POS GS v 0 raster image command with a
# handful of vendor-specific control commands layered on top.

from ..raster import build_gs_v_0
from .base import PrinterDriver


class LuckPrinterDriver(PrinterDriver):
    # GATT characteristics exposed by the printer's custom BLE service.
    write_characteristic = "0000ff02-0000-1000-8000-00805f9b34fb"
    notify_characteristic = "0000ff01-0000-1000-8000-00805f9b34fb"

    def build_density(self, level: int) -> bytes:
        return bytes([0x10, 0xFF, 0x10, 0x00, level])

    def build_wake_commands(self) -> list[bytes]:
        # Enable printer, then wake the print head/motor (12 null bytes).
        # Without waking it, the printer accepts the BLE connection and
        # control commands (LED changes state) but never actually engages
        # the print mechanism.
        return [bytes([0x10, 0xFF, 0xF1, 0x03]), bytes(12)]

    def build_image(self, bitmap: bytes, width_bytes: int, height_px: int) -> bytes:
        return build_gs_v_0(bitmap, width_bytes, height_px)

    def build_feed(self, dots: int) -> bytes:
        return bytes([0x1B, 0x4A, dots & 0xFF])

    def build_end(self) -> bytes:
        return bytes([0x10, 0xFF, 0xF1, 0x45])
