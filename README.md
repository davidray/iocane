# luckjingle-mcp

An MCP server that lets Claude (or any MCP client) design and print things to
cheap Bluetooth thermal label/sticker printers - the ones sold under names
like **NHOWIN**, **NDYIN**, **C&Co 3128**, **DP-L1S**, etc, that all run on
the "LuckPrinter SDK" behind the "Luck Jingle" phone app (159+ rebrand
models share this SDK).

These printers don't publish an official protocol or SDK. This server talks
to them using a protocol reverse engineered by the community by decompiling
the Android app (see [NOTICE.md](NOTICE.md) for credits/sources): a standard
ESC/POS `GS v 0` raster image command plus a handful of vendor-specific
control commands. If your printer's BLE service exposes characteristics
`ff01`/`ff02` under service `ff00` (check with `probe_device`, see below)
it's very likely compatible as-is.

## Architecture

This is split into two processes, which is unfortunately necessary on macOS:

- **`luckjingle-daemon`** - owns the actual Bluetooth connection. Must run
  as its own independent app (see "macOS Bluetooth permission" below), not
  as a subprocess of Claude.
- **`luckjingle-mcp`** - the MCP server Claude talks to. It's a thin client
  that forwards tool calls to the daemon over `http://127.0.0.1:8765`.

## Requirements

- Python 3.10+
- macOS, Linux, or Windows with Bluetooth LE support (uses [bleak](https://github.com/hbldh/bleak))

## Install

```bash
cd /Users/dave/code/iocane
python3 -m venv .venv
.venv/bin/pip install -e .
```

## macOS Bluetooth permission (important)

On macOS, any process descending from an app that hasn't declared Bluetooth
usage in its `Info.plist` will hard-crash (not prompt) the instant it
touches CoreBluetooth. Since this MCP server runs as a subprocess of
whatever launched Claude, that includes it. `macos_app/LuckJingleDaemon.app`
works around this: it's a minimal app bundle that declares
`NSBluetoothAlwaysUsageDescription`, so macOS can show a normal permission
prompt for it instead.

**You must start the daemon by opening this app directly - not from inside
Claude/a terminal spawned by Claude:**

```bash
open /Users/dave/code/iocane/macos_app/LuckJingleDaemon.app
```

The first time, macOS will show a Bluetooth permission prompt attributed to
`python3.14` (or similar) - accept it. It's a background app (no dock icon,
no window) that just listens on `127.0.0.1:8765`; leave it running whenever
you want to print. If you want it running automatically, add it to
**System Settings → General → Login Items**.

*Known glitch*: the permission dialog can sometimes get visually stuck (looks
like clicking "Allow" does nothing). If that happens, check whether it
actually took effect before assuming otherwise - macOS's own dialog
rendering can lag behind the real permission state; killing and reopening
the daemon app is usually enough to get a clean prompt.

On Linux/Windows this split isn't necessary, but the daemon/client
architecture works the same way regardless - just run `luckjingle-daemon`
however you'd normally run a background service.

## Find and verify your printer

1. Power on the printer and make sure your phone isn't already connected to
   it via its own app (force-quit the app, or turn the phone's Bluetooth off
   temporarily) - a printer already connected elsewhere won't advertise for
   a new connection.
2. Ask Claude to run `scan_printers` (or start the daemon and
   `curl -X POST http://127.0.0.1:8765/scan -d '{"timeout": 10}'`). Results
   are sorted by signal strength - your printer is usually the strongest
   signal since it's right next to you, but cheap BLE modules often
   advertise a generic factory name (ours showed up as `PPS1_6306_BLE`, not
   any recognizable brand name) rather than the retail brand printed on the
   box.
3. Before trusting a name-based guess, confirm it with `probe_device
   (address)` - a compatible printer's GATT services should include:
   ```
   service 0000ff00-... with characteristics:
     0000ff01-...  (notify)
     0000ff02-...  (write)
   ```
   This UUID pattern is a common generic BLE-serial scheme also used by
   unrelated devices, so a name match alone isn't proof - but the service
   layout combined with a signal-strength match is a strong signal.
4. Save it: ask Claude to run `set_printer_address`, or
   `curl -X POST http://127.0.0.1:8765/set_address -d '{"address": "..."}'`.

The address is saved to `~/.config/luckjingle-mcp/config.json` and reused
for future print jobs, so you only need to do this once.

## Register the MCP server with Claude Code

```bash
claude mcp add luckjingle -- /Users/dave/code/iocane/.venv/bin/luckjingle-mcp
```

Or add directly to your MCP config (e.g. `~/.claude.json` or `.mcp.json`):

```json
{
  "mcpServers": {
    "luckjingle": {
      "command": "/Users/dave/code/iocane/.venv/bin/luckjingle-mcp"
    }
  }
}
```

This just needs to be done once; the daemon app still needs to be started
separately each time you want to print (see above).

## Tools

- `scan_printers(timeout=6.0)` - list nearby BLE devices (name, address,
  signal strength)
- `probe_device(address, timeout=15)` - connect and list GATT
  services/characteristics, to verify a candidate device before saving it
- `set_printer_address(address)` - save the printer to use
- `get_printer_config()` - show saved settings
- `set_printer_options(width, density, font_path)` - tune print quality:
  `width` in dots (384 is standard), `density` 0-2 (light/normal/dark,
  leave unset for the printer's own default)
- `print_text(text, font_size=24, align="left")` - print wrapped text
- `print_image(image_path, dither=True)` - print an image file, resized to
  the paper width and converted to black & white
- `get_daemon_info()` - checks whether the daemon is reachable and explains
  how to start it if not

To print a custom design (a label with a logo, a QR code, a styled layout,
etc), have Claude generate a PNG with whatever tool/script fits, save it to
disk, then call `print_image` with that path.

## Troubleshooting

- **Any MCP tool call fails with a connection error**: the daemon app isn't
  running - see "macOS Bluetooth permission" above.
- **Connects (printer's LED changes) but nothing physically prints**: the
  printer probably isn't in the `LuckPrinter SDK` family this driver
  targets, or uses a variant that builds the image command differently.
  Run `probe_device` to confirm the GATT layout matches, and check
  `PROTOCOL.md` in
  [thermal-pocket-printer-basic](https://github.com/ChiaraCannolee/thermal-pocket-printer-basic)
  for the full command reference if you need to adapt `printer.py` further.
- **Printer turns itself off unexpectedly**: this happened during
  development and turned out to be a bug in an earlier version of this
  driver (an "disable auto-shutdown" command that actually *set the
  auto-shutdown timer to 0*). If you see it again, check nothing is sending
  `10 FF 12 00 00`.
- **Prints too light/dark**: set `density` (0-2) via `set_printer_options`.
