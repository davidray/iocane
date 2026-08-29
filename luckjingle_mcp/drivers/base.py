# Shared printer session: image prep (resize, dither, bitmap conversion)
# and chunked wire writes, protocol-agnostic. Each concrete driver only
# supplies command bytes and the BLE characteristics for its printer
# family - see PrinterDriver below, and luckprinter.py for a worked
# example. If you're adding support for a new printer, this is the file
# to read first.

import asyncio
from abc import ABC, abstractmethod

from PIL import Image, ImageDraw, ImageFont

from ..dither import floyd_steinberg_dither
from ..raster import image_to_bitmap

DEFAULT_WIDTH = 384  # dots; standard for 48mm/58mm 203dpi thermal heads


class PrinterDriver(ABC):
    """Everything specific to one printer protocol/hardware family. All of
    these command-building methods return raw bytes (or a list of them);
    PrinterSession takes care of when to send them, chunking, and delays."""

    #: GATT characteristic UUIDs for the printer's custom BLE service.
    write_characteristic: str
    notify_characteristic: str

    #: How large a chunk to write at once, and the delay between chunks/
    #: commands - printers with small receive buffers need small chunks
    #: and pauses between writes, or they silently drop data.
    chunk_size: int = 512
    chunk_delay: float = 0.01
    command_delay: float = 0.3
    #: Extra settle time after the "end of job" command, and after the
    #: image data finishes sending, before the connection can be closed.
    end_wait: float = 2.0
    image_settle_delay: float = 0.5

    @abstractmethod
    def build_density(self, level: int) -> bytes:
        """Command to set print darkness. `level` is already clamped to
        0-2 by the caller. Only sent when a density is configured."""

    @abstractmethod
    def build_wake_commands(self) -> list[bytes]:
        """One or more commands to wake the print head/motor before
        sending an image, sent in order with command_delay between each.
        Return [] if the printer doesn't need one."""

    @abstractmethod
    def build_image(self, bitmap: bytes, width_bytes: int, height_px: int) -> bytes:
        """Command to print a 1bpp MSB-first bitmap of the given size."""

    @abstractmethod
    def build_feed(self, dots: int) -> bytes:
        """Command to feed blank paper."""

    @abstractmethod
    def build_end(self) -> bytes:
        """Command that finalizes/ends the print job."""


class PrinterSession:
    """High-level printer API: connect, print text/images, feed and
    finish. Protocol-agnostic - every printer-specific command comes from
    the driver passed in."""

    def __init__(
        self,
        device,
        driver: PrinterDriver,
        width: int = DEFAULT_WIDTH,
        density: int | None = None,
        font_path: str | None = None,
    ):
        self.device = device
        self.driver = driver
        self.width = width
        self.density = density
        self.font_path = font_path

    async def initialize(self):
        await self.device.open()

    async def close(self):
        await self.device.close()

    async def _write_command(self, data: bytes, wait: float | None = None):
        if not data:
            return
        await self.device.write(data)
        await asyncio.sleep(self.driver.command_delay if wait is None else wait)

    async def _write_chunked(self, data: bytes):
        for i in range(0, len(data), self.driver.chunk_size):
            await self.device.write(data[i : i + self.driver.chunk_size])
            await asyncio.sleep(self.driver.chunk_delay)

    async def print_end(self, feed_dots: int = 80):
        """Feed a bit of blank paper and end the print job."""
        await self._write_command(self.driver.build_feed(feed_dots))
        await self._write_command(self.driver.build_end(), wait=self.driver.end_wait)

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

        bitmap_data, width_bytes, height_px = image_to_bitmap(img, self.width)
        image_command = self.driver.build_image(bitmap_data, width_bytes, height_px)

        if self.density is not None:
            density = max(0, min(2, self.density))
            await self._write_command(self.driver.build_density(density))

        for command in self.driver.build_wake_commands():
            await self._write_command(command)

        await self._write_chunked(image_command)
        await asyncio.sleep(self.driver.image_settle_delay)
