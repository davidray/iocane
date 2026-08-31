# Driver for "D1"-family thermal printers (sold e.g. as "叮当同学 D1" /
# "Dingdang D1"; naming strings inside at least one reference implementation
# call it "LuckP_D1", suggesting a close sibling of the "LuckPrinter SDK"
# family `luckprinter.py` targets, not an unrelated vendor). See NOTICE.md
# for the full history and credits.
#
# ** EXPERIMENTAL / UNVERIFIED. ** This driver has never been run against
# real D1-family hardware in this project - see the README's "Adding
# support for a new printer" section if you have one and can test it.
#
# An earlier version of this project's driver targeted this protocol
# family, based on lsongdev/luckjingle-d1-printer and LynMoe/DingdangD1-PoC.
# It connected successfully to this project's own "PPS1_6306_BLE" unit
# (same BLE service/characteristic layout as `luckprinter`) but its image
# command format never produced any output on that hardware - see
# NOTICE.md. Both of those sources build the image data as one continuous,
# non-byte-aligned bitstream behind an unexplained fixed 319-bit header,
# and their own code comments flag the chunk-length math as "a simple
# guess" - worth knowing if you're comparing sources, but not what's
# implemented below.
#
# This driver instead follows Lakr233/GGLyn's implementation (Instructor.swift
# / Instructor+Image.swift), which was reverse-engineered by decompiling the
# vendor app with Ghidra rather than inferring the format from captured
# traffic. It describes a standard, byte-aligned `GS v 0` raster command -
# identical in structure to `luckprinter`'s - which is what this driver
# sends via the same raster.py helpers. Whether this actually resolves the
# "connects but doesn't print" problem noted above is unconfirmed.

from ..raster import build_gs_v_0
from .base import PrinterDriver


class D1XDriver(PrinterDriver):
    # Same GATT characteristics as `luckprinter`. Per NOTICE.md this is a
    # common generic BLE-serial scheme also used by unrelated devices, so
    # sharing it isn't proof these two drivers' command sets are
    # interchangeable - they aren't (see build_wake_commands below).
    write_characteristic = "0000ff02-0000-1000-8000-00805f9b34fb"
    notify_characteristic = "0000ff01-0000-1000-8000-00805f9b34fb"

    def build_density(self, level: int) -> bytes:
        return bytes([0x10, 0xFF, 0x10, 0x00, level])

    def build_wake_commands(self) -> list[bytes]:
        # Per GGLyn's Instructor.swift: enable, then a wake-magic of 1024
        # null bytes - much longer than luckprinter's 12.
        return [bytes([0x10, 0xFF, 0xF1, 0x03]), bytes(1024)]

    def build_image(self, bitmap: bytes, width_bytes: int, height_px: int) -> bytes:
        # Same standard ESC/POS GS v 0 raster command as luckprinter - see
        # the module docstring for why this (and not the two Python
        # proof-of-concepts' bitstream format) is what's implemented here.
        return build_gs_v_0(bitmap, width_bytes, height_px)

    def build_feed(self, dots: int) -> bytes:
        return bytes([0x1B, 0x4A, dots & 0xFF])

    def build_end(self) -> bytes:
        return bytes([0x10, 0xFF, 0xF1, 0x45])
