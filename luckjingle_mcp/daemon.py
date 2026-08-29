# Standalone print daemon. This MUST run as its own top-level process (not a
# child of Claude / an MCP stdio server) - see NOTICE.md / README "macOS
# Bluetooth permission" section for why. It owns the actual BLE connection
# and exposes a tiny localhost HTTP API that the MCP server (server.py)
# talks to.

import asyncio
import json
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

from .config import (
    AUTH_HEADER,
    DEFAULT_DRIVER,
    DEFAULT_PRINTER_NAME,
    get_or_create_token,
    get_printer,
    load_config,
    save_config,
)
from .drivers import DEFAULT_WIDTH, PrinterSession, get_driver_class
from .printer import BluetoothDevice, scan_devices

HOST = "127.0.0.1"
PORT = 8765

_loop = asyncio.new_event_loop()

# ThreadingHTTPServer runs every request in its own thread, but the printer
# only supports one BLE connection at a time and the config file isn't safe
# for concurrent read-modify-write. Serialize access to each so overlapping
# requests (e.g. two print jobs, or a config write racing another) can't
# interleave BLE writes (corrupting the print) or silently drop an update.
_printer_lock = asyncio.Lock()
_config_lock = threading.Lock()


def _run_loop():
    asyncio.set_event_loop(_loop)
    _loop.run_forever()


def _run_coro(coro, timeout):
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result(timeout=timeout)


async def _probe_device(address: str, timeout: float) -> list[dict]:
    import bleak

    client = bleak.BleakClient(address, timeout=timeout)
    await client.connect()
    try:
        services = []
        for service in client.services:
            services.append(
                {
                    "uuid": service.uuid,
                    "characteristics": [
                        {"uuid": c.uuid, "properties": c.properties}
                        for c in service.characteristics
                    ],
                }
            )
        return services
    finally:
        await client.disconnect()


def _validate_options(body: dict) -> None:
    """Reject bad width/density up front, at set_options time, rather than
    letting them silently reach printer.py and blow up as an opaque
    exception the next time someone prints (e.g. Pillow's Image.resize
    raising on a non-positive width)."""
    errors = []
    width = body.get("width")
    if width is not None and (not isinstance(width, int) or isinstance(width, bool) or width <= 0):
        errors.append("width must be a positive integer (dots)")
    density = body.get("density")
    if density is not None and (
        not isinstance(density, int) or isinstance(density, bool) or not (0 <= density <= 2)
    ):
        errors.append("density must be an integer between 0 and 2")
    if errors:
        raise ValueError("; ".join(errors))


async def _open_printer(name: str | None = None) -> PrinterSession:
    """Open the named printer, or the active one if name is None. `name` is
    unused externally for now (there's still only ever one configured
    printer from the caller's point of view) - it's here so the multi-
    printer selection work doesn't need to touch this again."""
    cfg = load_config()
    profile = get_printer(cfg, name)
    if not profile or not profile.get("address"):
        raise ValueError(
            "No printer configured. POST /scan to find its address, then "
            "POST /set_address."
        )
    driver_cls = get_driver_class(profile.get("driver", DEFAULT_DRIVER))
    driver = driver_cls()
    device = BluetoothDevice(profile["address"], driver.write_characteristic, driver.notify_characteristic)
    session = PrinterSession(
        device,
        driver,
        width=profile.get("width", DEFAULT_WIDTH),
        density=profile.get("density"),
        font_path=profile.get("font_path"),
    )
    await session.initialize()
    return session


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def log_message(self, fmt, *args):
        pass

    def _authorized(self) -> bool:
        return self.headers.get(AUTH_HEADER) == get_or_create_token()

    def do_GET(self):
        if not self._authorized():
            self._send_json({"error": "unauthorized"}, 401)
            return
        if self.path == "/health":
            self._send_json({"ok": True})
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        if not self._authorized():
            self._send_json({"error": "unauthorized"}, 401)
            return
        try:
            body = self._read_json()
            handler = {
                "/scan": self._scan,
                "/probe": self._probe,
                "/set_address": self._set_address,
                "/get_config": self._get_config,
                "/set_options": self._set_options,
                "/print_text": self._print_text,
                "/print_image": self._print_image,
            }.get(self.path)
            if handler is None:
                self._send_json({"error": "not found"}, 404)
                return
            handler(body)
        except ValueError as e:
            self._send_json({"error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001 - report to caller, don't crash the daemon
            # Log the full traceback locally for debugging, but don't hand it
            # to the caller - it includes local file paths and internals that
            # any process able to reach this local HTTP API shouldn't need.
            print(f"error handling POST {self.path}:", file=sys.stderr)
            traceback.print_exc()
            self._send_json({"error": f"{type(e).__name__}: {e}"}, 500)

    def _scan(self, body):
        timeout = body.get("timeout", 6.0)
        devices = _run_coro(scan_devices(timeout), timeout=timeout + 5)
        self._send_json({"devices": devices})

    def _probe(self, body):
        address = body["address"]
        timeout = body.get("timeout", 15)
        services = _run_coro(_probe_device(address, timeout), timeout=timeout + 10)
        self._send_json({"services": services})

    def _set_address(self, body):
        with _config_lock:
            cfg = load_config()
            name = cfg.get("active_printer") or DEFAULT_PRINTER_NAME
            profile = cfg["printers"].setdefault(name, {"driver": DEFAULT_DRIVER})
            profile["address"] = body["address"]
            cfg["active_printer"] = name
            save_config(cfg)
        self._send_json({"ok": True})

    def _get_config(self, _body):
        with _config_lock:
            profile = get_printer(load_config(), None)
        # Still the flat single-printer shape externally - there's only ever
        # one selectable printer from the caller's point of view for now.
        self._send_json(dict(profile) if profile else {})

    def _set_options(self, body):
        _validate_options(body)
        with _config_lock:
            cfg = load_config()
            name = cfg.get("active_printer") or DEFAULT_PRINTER_NAME
            profile = cfg["printers"].setdefault(name, {"driver": DEFAULT_DRIVER})
            for key in ("width", "density", "font_path"):
                if body.get(key) is not None:
                    profile[key] = body[key]
            cfg["active_printer"] = name
            save_config(cfg)
            result = dict(profile)
        self._send_json(result)

    def _print_text(self, body):
        async def job():
            async with _printer_lock:
                printer = await _open_printer()
                try:
                    await printer.print_text(
                        body["text"],
                        font_size=body.get("font_size", 24),
                        align=body.get("align", "left"),
                    )
                    await printer.print_end()
                finally:
                    await printer.close()

        _run_coro(job(), timeout=60)
        self._send_json({"ok": True})

    def _print_image(self, body):
        path = Path(body["image_path"]).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"No such file: {path}")
        img = Image.open(path)
        dither = body.get("dither", True)

        async def job():
            async with _printer_lock:
                printer = await _open_printer()
                try:
                    await printer.print_image(img, dither=dither)
                    await printer.print_end()
                finally:
                    await printer.close()

        _run_coro(job(), timeout=60)
        self._send_json({"ok": True})


def main():
    threading.Thread(target=_run_loop, daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"LuckJingle print daemon listening on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
