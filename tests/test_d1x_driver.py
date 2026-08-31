"""Protocol snapshot tests for the experimental D1X driver - see
luckjingle_mcp/drivers/d1x.py's module docstring for how confident (or not)
to be in these bytes. These tests pin what's actually implemented, not
what's necessarily correct for real hardware."""

import asyncio

import pytest
from PIL import Image

from luckjingle_mcp.drivers import PrinterSession
from luckjingle_mcp.drivers.d1x import D1XDriver
from luckjingle_mcp.raster import build_gs_v_0, image_to_bitmap


class FakeDevice:
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
    async def instant_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)


def run(coro):
    return asyncio.run(coro)


def test_d1x_wake_sequence_is_1024_null_bytes_not_12():
    device = FakeDevice()
    session = PrinterSession(device, D1XDriver(), width=8, density=None)
    img = Image.new("L", (8, 1), color=255)

    run(session.print_image(img, dither=False))

    assert device.writes[0] == bytes([0x10, 0xFF, 0xF1, 0x03])  # enable, same as luckprinter
    assert device.writes[1] == bytes(1024)  # the actual D1X-specific difference


def test_d1x_uses_the_same_standard_gs_v_0_image_command_as_luckprinter():
    device = FakeDevice()
    session = PrinterSession(device, D1XDriver(), width=8, density=None)
    img = Image.new("L", (8, 1), color=255)

    run(session.print_image(img, dither=False))

    bitmap, width_bytes, height_px = image_to_bitmap(img, 8)
    expected_image_command = build_gs_v_0(bitmap, width_bytes, height_px)
    reassembled = b"".join(device.writes[2:])
    assert reassembled == expected_image_command


def test_d1x_density_command_matches_luckprinter_format():
    device = FakeDevice()
    session = PrinterSession(device, D1XDriver(), width=8, density=2)
    img = Image.new("L", (8, 1), color=255)

    run(session.print_image(img, dither=False))

    assert device.writes[0] == bytes([0x10, 0xFF, 0x10, 0x00, 0x02])


def test_d1x_end_of_job_command_matches_luckprinter():
    device = FakeDevice()
    session = PrinterSession(device, D1XDriver(), width=384)

    run(session.print_end(feed_dots=80))

    assert device.writes == [
        bytes([0x1B, 0x4A, 80]),
        bytes([0x10, 0xFF, 0xF1, 0x45]),
    ]


def test_d1x_is_registered_and_resolvable_by_name():
    from luckjingle_mcp.drivers import get_driver_class

    assert get_driver_class("d1x") is D1XDriver
