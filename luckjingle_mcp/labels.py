# Label composition: turns text (plus an optional decorative border image)
# into a single image ready to hand to PrinterSession.print_image. Pure PIL
# image logic - no printer/BLE/daemon concerns live here, so it's testable
# without a fake transport.

from PIL import Image, ImageDraw, ImageFont

from .drivers import wrap_lines

MARGIN = 8  # padding (dots) between the text and the edge of its white panel
BORDER_FRAME = 40  # dots of border art left visible as a frame around the panel


def _flatten_to_white(img: Image.Image) -> Image.Image:
    """Convert to RGB, compositing any transparency over white instead of
    the black PIL defaults to - border art is usually clipart exported
    with a transparent background, and it should read as "no border art
    here", not "solid black here"."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, "white")
        background.paste(img, mask=img.getchannel("A"))
        return background
    return img.convert("RGB")


def _tile_to_size(img: Image.Image, width: int, height: int) -> Image.Image:
    """Resize `img` to `width` (preserving aspect ratio) and repeat it
    top-to-bottom to fill `height` - most border art is a short strip
    (e.g. a row of icons) meant to repeat, not a single tall frame."""
    if img.width != width:
        new_height = max(1, round(img.height * width / img.width))
        img = img.resize((width, new_height), Image.LANCZOS)
    canvas = Image.new("RGB", (width, height), "white")
    y = 0
    while y < height:
        canvas.paste(img, (0, y))
        y += img.height
    return canvas


def compose_label(
    text: str,
    width: int,
    font: ImageFont.FreeTypeFont,
    font_size: int,
    align: str = "center",
    border: Image.Image | None = None,
) -> Image.Image:
    """Render `text` (wrapped to `width`) as a printable image. If `border`
    is given, it's tiled to frame the text - the text itself always sits on
    a plain white panel so it stays legible regardless of the border's own
    colors or pattern."""
    width = max(1, width)  # a non-positive width would crash the resize/tile below
    # Cap the frame so a narrow canvas can't push panel_width to zero/negative.
    frame = min(BORDER_FRAME, (width - 1) // 2) if border is not None else 0
    panel_width = width - 2 * frame

    lines = wrap_lines(text, font, panel_width - 2 * MARGIN)
    line_height = font_size + 6
    panel_height = line_height * len(lines) + 2 * MARGIN

    if border is None:
        canvas = Image.new("RGB", (width, panel_height), "white")
        panel_x, panel_y = 0, 0
    else:
        canvas = _tile_to_size(_flatten_to_white(border), width, panel_height + 2 * frame)
        panel_x, panel_y = frame, frame
        ImageDraw.Draw(canvas).rectangle(
            [panel_x, panel_y, panel_x + panel_width, panel_y + panel_height], fill="white"
        )

    draw = ImageDraw.Draw(canvas)
    for i, line in enumerate(lines):
        y = panel_y + MARGIN + i * line_height
        line_width = font.getlength(line)
        if align == "center":
            x = panel_x + (panel_width - line_width) / 2
        elif align == "right":
            x = panel_x + panel_width - MARGIN - line_width
        else:
            x = panel_x + MARGIN
        draw.text((x, y), line, fill="black", font=font)

    return canvas
