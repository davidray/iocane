# Generic 1bpp raster image encoding shared by ESC/POS-style thermal
# printer drivers. None of this is specific to any one printer/vendor -
# see luckjingle_mcp/drivers/ for the protocol-specific command bytes that
# wrap around it.

from PIL import Image


def image_to_bitmap(img: Image.Image, width_px: int) -> tuple[bytes, int, int]:
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


def build_gs_v_0(bitmap_data: bytes, width_bytes: int, height_px: int, mode: int = 0) -> bytes:
    """Build a standard ESC/POS `GS v 0` raster image command."""
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
