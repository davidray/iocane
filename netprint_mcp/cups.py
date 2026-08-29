# Thin wrapper around the system's CUPS command-line tools (lp/lpstat) for
# sending documents to a printer already configured on this machine - e.g.
# a network HP printer set up once in System Settings > Printers &
# Scanners (macOS) or via `lpadmin` (Linux).
#
# Unlike luckjingle_mcp, this needs no separate daemon: printing through
# CUPS is a plain subprocess call, with none of the macOS Bluetooth-
# permission restrictions that forced that project's daemon/MCP split.

import re
import subprocess
from pathlib import Path

# Matches the first line of each printer's `lpstat -p` entry, e.g.
# "printer HP_OfficeJet_Pro is idle.  enabled since Mon 01 Jan 2024 ..."
# or "printer HP_OfficeJet_Pro now printing HP_OfficeJet_Pro-12.  ...".
# Deliberately doesn't anchor on "is" specifically - lpstat's phrasing
# varies by state - so the captured status is whatever text CUPS put
# there, not normalized into a fixed set of values.
_PRINTER_LINE_RE = re.compile(r"^printer (\S+) (.+?)\.")


def _run(args: list[str], timeout: float = 15) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        raise RuntimeError(
            f"'{args[0]}' not found. This tool needs CUPS's command-line utilities - "
            "they ship with macOS, and on Linux are usually in a 'cups-client' package."
        ) from e


def list_printers() -> list[dict]:
    """List printers already configured on this machine, with their
    current status as reported by `lpstat -p` (a free-text status string -
    e.g. "is idle", "is stopped", "now printing ...")."""
    result = _run(["lpstat", "-p"])
    printers = []
    for line in result.stdout.splitlines():
        match = _PRINTER_LINE_RE.match(line.strip())
        if match:
            printers.append({"name": match.group(1), "status": match.group(2)})
    return printers


def get_default_printer() -> str | None:
    """The system default printer, or None if none is set."""
    result = _run(["lpstat", "-d"])
    line = result.stdout.strip()
    prefix = "system default destination:"
    if line.lower().startswith(prefix):
        return line[len(prefix) :].strip()
    return None


def print_document(path: str, printer: str | None = None, copies: int = 1) -> str:
    """Send a document to a printer via `lp`. Returns lp's own status line
    (e.g. "request id is HP_OfficeJet_Pro-42 (1 file(s))")."""
    resolved = Path(path).expanduser()
    if not resolved.exists():
        raise FileNotFoundError(f"No such file: {resolved}")

    if not isinstance(copies, int) or isinstance(copies, bool) or copies < 1:
        raise ValueError("copies must be a positive integer")

    target = printer or get_default_printer()
    if target is None:
        raise ValueError(
            "No printer specified and no default printer is configured. "
            "Call list_printers() and pass a printer name explicitly, or "
            "set a default with `lpoptions -d <name>`."
        )

    known = {p["name"] for p in list_printers()}
    if target not in known:
        raise ValueError(f"No such printer: {target!r}. Configured printers: {sorted(known)}")

    args = ["lp", "-d", target]
    if copies != 1:
        args += ["-n", str(copies)]
    args.append(str(resolved))

    result = _run(args, timeout=60)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        raise RuntimeError(message or f"lp exited with status {result.returncode}")
    return result.stdout.strip()
