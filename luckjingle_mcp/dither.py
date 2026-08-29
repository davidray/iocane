# Floyd-Steinberg dithering for 1-bit thermal printing.
#
# Ported from https://github.com/ChiaraCannolee/thermal-pocket-printer-basic
# (MIT), which reverse-engineered it from the LuckPrinter Android SDK
# (com.luckprinter.sdk_new) and verified it against real hardware.

from PIL import Image


def floyd_steinberg_dither(img: Image.Image) -> Image.Image:
    """Dither a grayscale image to black/white with Floyd-Steinberg error
    diffusion. Much better tonal reproduction than a flat threshold for
    photos/gradients."""
    img = img.convert("L")
    width, height = img.size
    pixels = [float(v) for v in img.getdata()]

    for y in range(height):
        for x in range(width):
            idx = y * width + x
            old_val = pixels[idx]
            new_val = 255.0 if old_val >= 128 else 0.0
            pixels[idx] = new_val
            error = old_val - new_val

            if x + 1 < width:
                pixels[idx + 1] += error * 7 / 16
            if y + 1 < height:
                if x > 0:
                    pixels[(y + 1) * width + (x - 1)] += error * 3 / 16
                pixels[(y + 1) * width + x] += error * 5 / 16
                if x + 1 < width:
                    pixels[(y + 1) * width + (x + 1)] += error * 1 / 16

    result = Image.new("L", (width, height))
    result.putdata([max(0, min(255, int(v))) for v in pixels])
    return result
