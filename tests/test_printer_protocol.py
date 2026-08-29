"""Pin down the exact byte sequences LuckPrinter puts on the wire.

There's no real printer hardware available in CI/dev, so these use a fake
transport that just records what was written instead of a real BLE/serial
connection. The point isn't to test the class in the abstract - it's to
snapshot the actual protocol bytes (wake sequence, density command, GS v 0
header, feed/end commands) so a future refactor (e.g. splitting this into a
pluggable driver interface) can be checked against real, previously-working
output instead of trusting the refactor by inspection.
"""

import asyncio

import pytest
from PIL import Image

from luckjingle_mcp.printer import LuckPrinter, _build_gs_v_0, _image_to_bitmap


class FakeDevice:
    """Records every write instead of touching real hardware."""

    def __init__(self):
        self.writes = []

    async def open(self):
        pass

    async def close(self):
        pass

    async def write(self, data: bytes):
        self.writes.append(bytes(data))


@pytest.fixture(autouse=True)
def no_real_delays(monkeypatch):
    # LuckPrinter deliberately sleeps between commands to match the
    # printer's receive rate - real for hardware, pointless for a test.
    async def instant_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)


def run(coro):
    return asyncio.run(coro)


def test_image_to_bitmap_packs_msb_first_dark_pixel_is_1():
    img = Image.new("L", (8, 2))
    # Row 0: left half dark, right half light. Row 1: alternating.
    img.putdata([0, 0, 0, 0, 255, 255, 255, 255, 0, 255, 0, 255, 0, 255, 0, 255])

    bitmap, width_bytes, height_px = _image_to_bitmap(img, 8)

    assert width_bytes == 1
    assert height_px == 2
    assert bitmap == bytes([0b11110000, 0b10101010])


def test_build_gs_v_0_header_layout():
    command = _build_gs_v_0(b"\x01\x02", width_bytes=1, height_px=2, mode=0)

    assert command[:8] == bytes([0x1D, 0x76, 0x30, 0x00, 0x01, 0x00, 0x02, 0x00])
    assert command[8:] == b"\x01\x02"


def test_print_image_command_sequence_with_density():
    device = FakeDevice()
    printer = LuckPrinter(device, width=8, density=1)
    img = Image.new("L", (8, 1), color=255)  # all-white -> all-zero bitmap

    run(printer.print_image(img, dither=False))

    assert device.writes[0] == bytes([0x10, 0xFF, 0x10, 0x00, 0x01])  # set density
    assert device.writes[1] == bytes([0x10, 0xFF, 0xF1, 0x03])  # enable printer
    assert device.writes[2] == bytes(12)  # wake print head/motor

    bitmap, width_bytes, height_px = _image_to_bitmap(img, 8)
    expected_image_command = _build_gs_v_0(bitmap, width_bytes, height_px)
    assert device.writes[3] == expected_image_command
    assert len(device.writes) == 4  # small image fits in a single chunk


def test_print_image_command_sequence_without_density():
    device = FakeDevice()
    printer = LuckPrinter(device, width=8, density=None)
    img = Image.new("L", (8, 1), color=255)

    run(printer.print_image(img, dither=False))

    # No density command at all when density isn't configured.
    assert device.writes[0] == bytes([0x10, 0xFF, 0xF1, 0x03])
    assert device.writes[1] == bytes(12)
    assert len(device.writes) == 3


def test_print_image_chunks_large_payloads():
    device = FakeDevice()
    printer = LuckPrinter(device, width=384)
    img = Image.new("L", (384, 200), color=0)  # all-black -> big bitmap

    run(printer.print_image(img, dither=False))

    bitmap, width_bytes, height_px = _image_to_bitmap(img, 384)
    expected_image_command = _build_gs_v_0(bitmap, width_bytes, height_px)
    # Everything after the fixed 2-command preamble (enable + wake) is the
    # image command, split into CHUNK_SIZE-byte pieces in order.
    reassembled = b"".join(device.writes[2:])
    assert reassembled == expected_image_command
    assert len(device.writes) > 3  # actually exercised chunking


def test_print_end_command_sequence():
    device = FakeDevice()
    printer = LuckPrinter(device, width=384)

    run(printer.print_end(feed_dots=80))

    assert device.writes == [
        bytes([0x1B, 0x4A, 80]),  # feed
        bytes([0x10, 0xFF, 0xF1, 0x45]),  # end of print job
    ]


def test_print_end_feed_dots_is_masked_to_a_byte():
    device = FakeDevice()
    printer = LuckPrinter(device, width=384)

    run(printer.print_end(feed_dots=300))  # out of single-byte range

    assert device.writes[0] == bytes([0x1B, 0x4A, 300 & 0xFF])
