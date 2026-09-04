"""Pure image-composition tests for labels.py - no printer/daemon/BLE
involved, just the PIL geometry of turning text (+ optional border) into a
printable image."""

from PIL import Image

from luckjingle_mcp.drivers import load_font
from luckjingle_mcp.labels import BORDER_FRAME, MARGIN, compose_label

FONT_SIZE = 24
FONT = load_font(None, FONT_SIZE)
LINE_HEIGHT = FONT_SIZE + 6


def test_compose_label_no_border_sizes_to_one_line():
    img = compose_label("hi", width=200, font=FONT, font_size=FONT_SIZE, align="left")

    assert img.mode == "RGB"
    assert img.width == 200
    assert img.height == LINE_HEIGHT + 2 * MARGIN


def test_compose_label_wraps_long_text_onto_multiple_lines():
    long_text = " ".join(["word"] * 40)

    img = compose_label(long_text, width=100, font=FONT, font_size=FONT_SIZE, align="left")

    assert img.height > LINE_HEIGHT + 2 * MARGIN


def test_compose_label_without_border_is_plain_white_at_the_corners():
    img = compose_label("hi", width=100, font=FONT, font_size=FONT_SIZE, align="left")

    assert img.getpixel((0, 0)) == (255, 255, 255)
    assert img.getpixel((99, img.height - 1)) == (255, 255, 255)


def test_compose_label_with_border_frames_a_white_text_panel():
    border = Image.new("RGB", (10, 10), (0, 0, 0))  # solid black border art

    img = compose_label("hi", width=200, font=FONT, font_size=FONT_SIZE, align="center", border=border)

    panel_height = LINE_HEIGHT + 2 * MARGIN
    assert img.height == panel_height + 2 * BORDER_FRAME
    # Inside the frame band (outside the text panel): border art shows through.
    assert img.getpixel((0, 2)) == (0, 0, 0)
    # Inside the text panel, away from the glyphs: stays white.
    assert img.getpixel((img.width // 2, BORDER_FRAME + 2)) == (255, 255, 255)


def test_compose_label_border_transparency_flattens_to_white_not_black():
    transparent_border = Image.new("RGBA", (10, 10), (0, 0, 0, 0))

    img = compose_label(
        "hi", width=200, font=FONT, font_size=FONT_SIZE, align="center", border=transparent_border
    )

    assert img.getpixel((0, 2)) == (255, 255, 255)


def test_compose_label_with_border_does_not_crash_on_a_non_positive_width():
    # A printer profile could (via a hand-edited config, or one predating
    # width validation) carry width <= 0. compose_label should degrade
    # gracefully rather than crash Pillow's Image.resize on a zero/negative
    # dimension.
    border = Image.new("RGB", (10, 10), (0, 0, 0))

    for width in (0, -5, 1):
        img = compose_label(
            "hi", width=width, font=FONT, font_size=FONT_SIZE, align="center", border=border
        )
        assert img.width >= 1
        assert img.height >= 1


def test_compose_label_border_is_tiled_not_stretched_to_one_giant_copy():
    # A short, wide strip - if it were stretched (not tiled) to fill a tall
    # canvas, its distinctive top-row color wouldn't reappear further down.
    strip = Image.new("RGB", (20, 4), (255, 0, 0))
    for x in range(20):
        strip.putpixel((x, 0), (0, 255, 0))  # mark the top row of each tile

    img = compose_label(
        "hi\nhi\nhi\nhi", width=20, font=FONT, font_size=FONT_SIZE, align="left", border=strip
    )

    green_rows = [y for y in range(img.height) if img.getpixel((0, y)) == (0, 255, 0)]
    assert len(green_rows) > 1, "border strip should repeat (tile), not stretch once"
