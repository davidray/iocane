# Standalone print daemon. This MUST run as its own top-level process (not a
# child of Claude / an MCP stdio server) - see NOTICE.md / README "macOS
# Bluetooth permission" section for why. It owns the actual BLE connection
# and exposes a tiny localhost HTTP API that the MCP server (server.py)
# talks to.

import asyncio
import json
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

from .config import AUTH_HEADER, get_or_create_token, load_config, load_public_config, save_config
from .printer import BluetoothDevice, LuckPrinter, scan_devices

HOST = "127.0.0.1"
PORT = 8765

_loop = asyncio.new_event_loop()


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


async def _open_printer() -> LuckPrinter:
    cfg = load_config()
    address = cfg.get("address")
    if not address:
        raise ValueError(
            "No printer configured. POST /scan to find its address, then "
            "POST /set_address."
        )
    device = BluetoothDevice(address)
    printer = LuckPrinter(
        device,
        width=cfg.get("width", 384),
        density=cfg.get("density"),
        font_path=cfg.get("font_path"),
    )
    await printer.initialize()
    return printer


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
        except Exception as e:  # noqa: BLE001 - report to caller, don't crash the daemon
            self._send_json(
                {"error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()},
                500,
            )

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
        cfg = load_config()
        cfg["address"] = body["address"]
        save_config(cfg)
        self._send_json({"ok": True})

    def _get_config(self, _body):
        self._send_json(load_public_config())

    def _set_options(self, body):
        cfg = load_config()
        for key in ("width", "density", "font_path"):
            if body.get(key) is not None:
                cfg[key] = body[key]
        save_config(cfg)
        self._send_json(load_public_config())

    def _print_text(self, body):
        async def job():
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
