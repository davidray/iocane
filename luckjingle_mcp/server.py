# MCP tool layer. Deliberately does NOT touch Bluetooth directly: this
# process runs as a stdio child of whatever launched Claude (e.g. the Claude
# desktop app), and macOS attributes CoreBluetooth's privacy permission to
# that top-level "responsible" app rather than to this subprocess. Since
# that app doesn't declare Bluetooth usage, any BLE call made from here
# hard-crashes (TCC abort) instead of prompting. So the actual printer
# connection lives in daemon.py, run as an independent top-level process by
# the user, and this file just forwards requests to it over localhost.

import json
import urllib.error
import urllib.request
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from .config import AUTH_HEADER, get_or_create_token

BASE_URL = "http://127.0.0.1:8765"

# This file lives at <repo_root>/luckjingle_mcp/server.py, and the app
# bundle at <repo_root>/macos_app/LuckJingleDaemon.app - derive the hint
# path from here instead of hardcoding one checkout's absolute path.
_APP_BUNDLE_PATH = Path(__file__).resolve().parent.parent / "macos_app" / "LuckJingleDaemon.app"

APP_BUNDLE_HINT = (
    "Could not reach the LuckJingle print daemon at {url}. It has to run as "
    "its own app - not as a subprocess of Claude - so macOS can grant it "
    "Bluetooth permission directly. Start it with:\n\n"
    "  open '{app_path}'\n\n"
    "The first launch will show a macOS Bluetooth permission prompt for "
    "'LuckJingle Print Daemon' - accept it, then retry."
)

mcp = MCPServer("luckjingle-printer")


def _request(method: str, path: str, payload: dict | None = None, timeout: float = 30) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={
            "Content-Type": "application/json",
            AUTH_HEADER: get_or_create_token(),
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            result = json.loads(e.read())
        except Exception:
            result = None
        if isinstance(result, dict) and "error" in result:
            raise RuntimeError(result["error"]) from e
        raise RuntimeError(f"Daemon returned HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise ConnectionError(APP_BUNDLE_HINT.format(url=BASE_URL, app_path=_APP_BUNDLE_PATH)) from e
    if isinstance(result, dict) and "error" in result:
        raise RuntimeError(result["error"])
    return result


@mcp.tool()
def scan_printers(timeout: float = 6.0) -> list[dict]:
    """Scan for nearby Bluetooth LE devices to find the printer's address.

    Put the printer in pairing mode (usually: hold its power button, or open
    its companion app once) before scanning, then look for a device name
    that resembles the printer (e.g. containing "D1", "GB", "Q3", "Print",
    or a string of letters/numbers) in the results.

    Requires the LuckJingle print daemon to be running (see get_daemon_info).
    """
    result = _request("POST", "/scan", {"timeout": timeout}, timeout=timeout + 10)
    return result["devices"]


@mcp.tool()
def probe_device(address: str, timeout: float = 15) -> list[dict]:
    """Connect to a BLE device and list its GATT services/characteristics.

    Useful for confirming a candidate address (found via scan_printers) is
    really a supported printer before adding it - a compatible printer
    should expose a custom service containing characteristics ending in
    ff01, ff02, and ff03. Note that this GATT layout alone doesn't tell you
    which driver to use - more than one incompatible protocol variant
    shares it - so still confirm with a real test print after adding it.
    """
    result = _request("POST", "/probe", {"address": address, "timeout": timeout}, timeout=timeout + 15)
    return result["services"]


@mcp.tool()
def set_printer_address(address: str) -> str:
    """Save the Bluetooth address of the printer for future print jobs.

    This is a shortcut for the common single-printer case - it updates
    whichever printer is currently active (creating one named "default" if
    none exists yet). To configure more than one printer, use add_printer
    instead, which lets you name each one.
    """
    _request("POST", "/set_address", {"address": address})
    return f"Saved printer address: {address}"


@mcp.tool()
def get_printer_config() -> dict:
    """Return the active printer's saved configuration (address, driver,
    paper width, etc). Use list_printers to see every configured printer."""
    cfg = _request("POST", "/get_config", {})
    if not cfg:
        return {"configured": False}
    return {"configured": True, **cfg}


@mcp.tool()
def list_printers() -> dict:
    """List every configured printer (name, driver, address, settings) and
    which one is currently active - the one print_text/print_image use when
    no printer is named explicitly."""
    return _request("POST", "/list_printers", {})


@mcp.tool()
def add_printer(name: str, address: str, driver: str = "luckprinter") -> dict:
    """Add (or update, if the name already exists) a named printer profile.
    If this is the first printer configured, it becomes the active one
    automatically - otherwise use select_printer to switch to it.

    driver identifies the printer's protocol family - "luckprinter" (the
    default) covers the LuckPrinter-SDK rebrand family (NHOWIN, PPS1,
    C&Co 3128, DP-L1S, etc) and is the only driver available so far.
    """
    return _request("POST", "/add_printer", {"name": name, "address": address, "driver": driver})


@mcp.tool()
def remove_printer(name: str) -> dict:
    """Remove a configured printer. If it was the active one, another
    remaining configured printer (if any) becomes active."""
    return _request("POST", "/remove_printer", {"name": name})


@mcp.tool()
def select_printer(name: str) -> dict:
    """Set which configured printer print_text/print_image use by default
    when no printer is named explicitly on the call."""
    return _request("POST", "/select_printer", {"name": name})


@mcp.tool()
def set_printer_options(
    width: int | None = None,
    density: int | None = None,
    font_path: str | None = None,
    name: str | None = None,
) -> dict:
    """Tune print quality for a printer. width is the paper width in dots
    (384 is standard for common 48mm/58mm thermal labels - only change it
    if prints come out cropped or skewed). density (0=light, 1=normal,
    2=dark) adjusts print darkness if prints look too light/dark - leave
    unset to use the printer's own default. font_path points to a .ttf/.otf
    file to use for print_text instead of the built-in fallback. name picks
    which configured printer to change settings for - leave unset to use
    the active printer.
    """
    return _request(
        "POST",
        "/set_options",
        {"width": width, "density": density, "font_path": font_path, "name": name},
    )


@mcp.tool()
def print_text(text: str, font_size: int = 24, align: str = "left", printer: str | None = None) -> str:
    """Print a block of text on the label printer, wrapped to the paper width.

    align may be "left", "center", or "right". printer names which
    configured printer to use for this one print job, overriding the
    active printer - leave unset to use the active printer.
    """
    _request(
        "POST",
        "/print_text",
        {"text": text, "font_size": font_size, "align": align, "printer": printer},
        timeout=60,
    )
    return "Print job sent."


@mcp.tool()
def print_image(image_path: str, dither: bool = True, printer: str | None = None) -> str:
    """Print an image file (PNG/JPG/etc) on the label printer.

    The image is resized to the printer's configured paper width and
    converted to black & white. Leave dither=True for photos/gradients;
    set dither=False for already-black-and-white line art or text to keep
    edges crisp. printer names which configured printer to use for this one
    print job, overriding the active printer - leave unset to use the
    active printer.

    For illustrated or photographic content, prefer generating a detailed
    image (e.g. with an image-generation tool, if one is available) over
    hand-drawing flat shapes - richer source detail dithers into far more
    convincing output at this printer's resolution than flat vector art
    does.
    """
    _request(
        "POST",
        "/print_image",
        {"image_path": image_path, "dither": dither, "printer": printer},
        timeout=60,
    )
    return "Print job sent."


@mcp.tool()
def save_border(name: str, image_path: str) -> str:
    """Save an image file as a reusable named "border" - a decorative
    design that print_label/save_label can frame text with (e.g. a strip
    of clipart). The image is copied into managed storage, so image_path
    itself doesn't need to stick around afterwards.

    Saving again under a name that already exists replaces it.
    """
    _request("POST", "/save_border", {"name": name, "image_path": image_path})
    return f"Saved border: {name}"


@mcp.tool()
def list_borders() -> list[str]:
    """List the names of every saved border, for use with print_label's or
    save_label's `border` argument."""
    return _request("POST", "/list_borders", {})["borders"]


@mcp.tool()
def remove_border(name: str) -> str:
    """Delete a saved border. Any saved label that referenced it will fail
    to print until given a different border or none."""
    _request("POST", "/remove_border", {"name": name})
    return f"Removed border: {name}"


@mcp.tool()
def print_label(
    text: str,
    font_size: int = 24,
    align: str = "center",
    border: str | None = None,
    dither: bool | None = None,
    save_as: str | None = None,
    printer: str | None = None,
) -> str:
    """Compose and print a text label, optionally framed by a saved border
    (see save_border/list_borders) - e.g. "Flux Capacitor" framed by a
    "dancing kittens" border.

    dither controls whether the composed image is dithered before
    printing - leave unset to dither automatically only when a border is
    present (borders usually have more tonal detail than plain text does);
    set explicitly to override that for a particular border's art.

    Pass save_as to also save this exact label (text, font_size, align,
    border, dither) under that name for print_saved_label to print again
    later without re-specifying everything. printer targets a specific
    printer for this one job, overriding the active printer.
    """
    result = _request(
        "POST",
        "/print_label",
        {
            "text": text,
            "font_size": font_size,
            "align": align,
            "border": border,
            "dither": dither,
            "save_as": save_as,
            "printer": printer,
        },
        timeout=60,
    )
    if result.get("saved_as"):
        return f"Print job sent. Saved as label {result['saved_as']!r}."
    return "Print job sent."


@mcp.tool()
def save_label(
    name: str,
    text: str,
    font_size: int = 24,
    align: str = "center",
    border: str | None = None,
    dither: bool | None = None,
) -> str:
    """Save a label (text, font size, alignment, optional border) under a
    name, without printing it - use print_saved_label to print it later.
    Saving again under a name that already exists replaces it. To save and
    print in one step, use print_label(..., save_as=name) instead. See
    print_label for what dither controls.
    """
    _request(
        "POST",
        "/save_label",
        {
            "name": name,
            "text": text,
            "font_size": font_size,
            "align": align,
            "border": border,
            "dither": dither,
        },
    )
    return f"Saved label: {name}"


@mcp.tool()
def list_labels() -> list[dict]:
    """List every saved label (name, text, font_size, align, border)."""
    return _request("POST", "/list_labels", {})["labels"]


@mcp.tool()
def remove_label(name: str) -> str:
    """Delete a saved label."""
    _request("POST", "/remove_label", {"name": name})
    return f"Removed label: {name}"


@mcp.tool()
def print_saved_label(name: str, printer: str | None = None) -> str:
    """Reprint a label previously saved with save_label or
    print_label(..., save_as=...). printer targets a specific printer for
    this one job, overriding the active printer.
    """
    _request("POST", "/print_saved_label", {"name": name, "printer": printer}, timeout=60)
    return "Print job sent."


@mcp.tool()
def get_daemon_info() -> str:
    """Explain how to start the required LuckJingle print daemon, and
    whether it is currently reachable."""
    try:
        _request("GET", "/health", timeout=3)
        return "Daemon is running and reachable at " + BASE_URL
    except ConnectionError as e:
        return str(e)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
