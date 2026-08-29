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
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
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

    Useful for confirming a candidate address (found via scan_printers)
    is really the printer before saving it - a LuckJingle-protocol printer
    should expose a custom service containing characteristics ending in
    ff01, ff02, and ff03.
    """
    result = _request("POST", "/probe", {"address": address, "timeout": timeout}, timeout=timeout + 15)
    return result["services"]


@mcp.tool()
def set_printer_address(address: str) -> str:
    """Save the Bluetooth address of the printer for future print jobs."""
    _request("POST", "/set_address", {"address": address})
    return f"Saved printer address: {address}"


@mcp.tool()
def get_printer_config() -> dict:
    """Return the currently saved printer configuration (address, paper width, etc)."""
    cfg = _request("POST", "/get_config", {})
    if not cfg:
        return {"configured": False}
    return {"configured": True, **cfg}


@mcp.tool()
def set_printer_options(
    width: int | None = None,
    density: int | None = None,
    font_path: str | None = None,
) -> dict:
    """Tune print quality. width is the paper width in dots (384 is standard
    for common 48mm/58mm thermal labels - only change it if prints come out
    cropped or skewed). density (0=light, 1=normal, 2=dark) adjusts print
    darkness if prints look too light/dark - leave unset to use the
    printer's own default. font_path points to a .ttf/.otf file to use for
    print_text instead of the built-in fallback.
    """
    return _request(
        "POST",
        "/set_options",
        {"width": width, "density": density, "font_path": font_path},
    )


@mcp.tool()
def print_text(text: str, font_size: int = 24, align: str = "left") -> str:
    """Print a block of text on the label printer, wrapped to the paper width.

    align may be "left", "center", or "right".
    """
    _request(
        "POST",
        "/print_text",
        {"text": text, "font_size": font_size, "align": align},
        timeout=60,
    )
    return "Print job sent."


@mcp.tool()
def print_image(image_path: str, dither: bool = True) -> str:
    """Print an image file (PNG/JPG/etc) on the label printer.

    The image is resized to the printer's configured paper width and
    converted to black & white. Leave dither=True for photos/gradients;
    set dither=False for already-black-and-white line art or text to keep
    edges crisp.
    """
    _request(
        "POST",
        "/print_image",
        {"image_path": image_path, "dither": dither},
        timeout=60,
    )
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
