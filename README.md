# luckjingle-mcp

An MCP server that lets Claude (or any MCP client) design and print things to
cheap Bluetooth thermal label/sticker printers, and manage more than one of
them - print to whichever one you select, or name one explicitly per job.

Printer support is pluggable: each printer family is a small driver (see
["Adding support for a new printer"](#adding-support-for-a-new-printer)
below). Right now there's one driver, `luckprinter`, covering "LuckPrinter
SDK" printers - the ones sold under names like **NHOWIN**, **NDYIN**,
**C&Co 3128**, **DP-L1S**, etc, that all run on the "LuckPrinter SDK" behind
the "Luck Jingle" phone app (159+ rebrand models share this SDK).

These printers don't publish an official protocol or SDK. `luckprinter`
talks to them using a protocol reverse engineered by the community by
decompiling the Android app (see [NOTICE.md](NOTICE.md) for credits/
sources): a standard ESC/POS `GS v 0` raster image command plus a handful of
vendor-specific control commands. If your printer's BLE service exposes
characteristics `ff01`/`ff02` under service `ff00` (check with
`probe_device`, see below) it's likely compatible as-is - but see the
"Adding support for a new printer" section if a test print doesn't work,
since more than one incompatible protocol shares that same GATT layout.

## Other servers in this repo

This repo also has [`netprint-mcp`](netprint_mcp/README.md) - a separate,
much simpler MCP server for printing documents (PDFs, images, etc) to a
regular network printer already set up on this machine, via CUPS. No BLE,
no daemon - see its own README for setup.

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
cd /path/to/iocane   # wherever you cloned this repo
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
open /path/to/iocane/macos_app/LuckJingleDaemon.app
```

(The bundle's launcher script locates its own venv relative to itself, so
this works from whatever path you cloned the repo to. If the daemon doesn't
start and nothing obvious shows up, check
`~/Library/Logs/luckjingle-daemon.log`.)

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
4. Save it: ask Claude to run `add_printer("<name>", "<address>")` - e.g.
   `add_printer("kitchen", "AA:BB:CC:DD:EE:FF")` - or
   `curl -X POST http://127.0.0.1:8765/add_printer -d '{"name": "kitchen", "address": "..."}'`.
   The first printer you add becomes the active one automatically. (If you
   only ever have one printer, `set_printer_address(address)` is a shorter
   equivalent that skips naming it.)

Printer profiles are saved to `~/.config/luckjingle-mcp/config.json` and
reused for future print jobs, so you only need to do this once per printer.

## Managing multiple printers

- `list_printers()` - see every configured printer and which one is active.
- `select_printer("<name>")` - switch which printer `print_text`/
  `print_image` use by default.
- `print_text(..., printer="<name>")` / `print_image(..., printer="<name>")`
  - print to a specific printer for one job, without switching the active
  one.
- `set_printer_options(..., name="<name>")` - tune width/density/font for a
  specific printer instead of the active one.
- `remove_printer("<name>")` - drop a configured printer. If it was active,
  another remaining one (if any) becomes active.

## Register the MCP server with Claude Code

```bash
claude mcp add luckjingle -- /path/to/iocane/.venv/bin/luckjingle-mcp
```

Or add directly to your MCP config (e.g. `~/.claude.json` or `.mcp.json`):

```json
{
  "mcpServers": {
    "luckjingle": {
      "command": "/path/to/iocane/.venv/bin/luckjingle-mcp"
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
  services/characteristics, to verify a candidate device before adding it
- `add_printer(name, address, driver="luckprinter")` - add or update a
  named printer profile; the first one added becomes active
- `list_printers()` - list every configured printer and which is active
- `select_printer(name)` - switch the active printer
- `remove_printer(name)` - remove a configured printer
- `set_printer_address(address)` - shortcut for the single-printer case:
  updates the active printer's address (creating one named `"default"` if
  none exists yet)
- `get_printer_config()` - show the active printer's saved settings
- `set_printer_options(width, density, font_path, name=None)` - tune print
  quality: `width` in dots (384 is standard), `density` 0-2 (light/normal/
  dark, leave unset for the printer's own default); `name` targets a
  specific printer instead of the active one
- `print_text(text, font_size=24, align="left", printer=None)` - print
  wrapped text; `printer` targets a specific printer for this job only
- `print_image(image_path, dither=True, printer=None)` - print an image
  file, resized to the paper width and converted to black & white;
  `printer` targets a specific printer for this job only
- `get_daemon_info()` - checks whether the daemon is reachable and explains
  how to start it if not

To print a custom design (a label with a logo, a QR code, a styled layout,
etc), have Claude generate a PNG with whatever tool/script fits, save it to
disk, then call `print_image` with that path.

## Troubleshooting

- **Any MCP tool call fails with a connection error**: the daemon app isn't
  running - see "macOS Bluetooth permission" above.
- **Connects (printer's LED changes) but nothing physically prints**: the
  printer probably isn't in the `luckprinter` (LuckPrinter SDK) family this
  driver targets, or uses a variant that builds the image command
  differently. Run `probe_device` to confirm the GATT layout matches, and
  check `PROTOCOL.md` in
  [thermal-pocket-printer-basic](https://github.com/ChiaraCannolee/thermal-pocket-printer-basic)
  for the full command reference if you need to adapt
  `luckjingle_mcp/drivers/luckprinter.py`, or write a new driver (see below).
- **Printer turns itself off unexpectedly**: this happened during
  development and turned out to be a bug in an earlier version of this
  driver (an "disable auto-shutdown" command that actually *set the
  auto-shutdown timer to 0*). If you see it again, check nothing is sending
  `10 FF 12 00 00`.
- **Prints too light/dark**: set `density` (0-2) via `set_printer_options`.

## Adding support for a new printer

Support for a printer family is a small "driver" object, not a fork of this
project. If `probe_device` shows a GATT layout this repo doesn't already
handle, or a compatible-looking printer just doesn't print correctly with
the `luckprinter` driver (see NOTICE.md - more than one incompatible
protocol shares that same `ff01`/`ff02` layout, so a matching GATT layout
alone doesn't guarantee compatibility), here's how to add one:

1. **Reverse-engineer the protocol.** These printers don't publish an SDK,
   so this means decompiling the vendor's Android/iOS app (e.g. with
   [JADX](https://github.com/skylot/jadx)) and finding the BLE write calls,
   the same way [NOTICE.md](NOTICE.md)'s sources did for `luckprinter`.
   You're looking for: the GATT write/notify characteristic UUIDs, how the
   printer is woken/enabled, how a print darkness/density setting is sent
   (if supported), how a raster image command is framed, and how a job is
   fed/ended.
2. **Implement `PrinterDriver`.** Read
   [`luckjingle_mcp/drivers/base.py`](luckjingle_mcp/drivers/base.py) for
   the interface, and
   [`luckjingle_mcp/drivers/luckprinter.py`](luckjingle_mcp/drivers/luckprinter.py)
   for a complete worked example - it's under 40 lines. You only supply
   command bytes and GATT characteristics; image resizing, dithering,
   bitmap packing, chunked writes, and text rendering are all shared and
   already handled by `PrinterSession`.
3. **Register it** by adding your driver class to the `DRIVERS` dict in
   [`luckjingle_mcp/drivers/__init__.py`](luckjingle_mcp/drivers/__init__.py),
   keyed by the name people will pass to `add_printer(..., driver="...")`.
4. **Add protocol tests.** See
   [`tests/test_printer_protocol.py`](tests/test_printer_protocol.py) -
   these use a fake transport that just records what was written, so you
   can pin down your driver's exact command bytes without needing the
   hardware present for every test run (you'll obviously still want to
   confirm against real hardware before calling it done).
5. Open a PR. Mention what hardware you tested against - a driver that's
   only ever run against the one printer its author owns is worth having,
   but should say so.

## Development

```bash
.venv/bin/pip install -e ".[test]"
.venv/bin/pytest -v
```

Tests don't need real printer hardware - they use fake transports that
record what would have been sent over BLE/serial, so they run the same on
a laptop with no printer nearby.
