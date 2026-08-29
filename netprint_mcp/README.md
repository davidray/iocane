# netprint-mcp

An MCP server for printing documents (PDF, images, plain text, etc) to a
printer already configured on this machine - e.g. a network printer (HP or
otherwise) set up once in **System Settings → Printers & Scanners**
(macOS) or via `lpadmin` (Linux). No separate daemon needed: printing
through CUPS is a plain subprocess call, with none of the macOS
Bluetooth-permission restrictions that `luckjingle-mcp` (the other server
in this repo) has to work around.

This doesn't talk IPP directly to a printer's network address - it hands
the job to whatever's already configured locally, the same way printing
from any other app on your machine works. If the printer isn't set up yet,
add it in System Settings first.

## Requirements

- CUPS's command-line tools (`lp`, `lpstat`) - included by default on
  macOS; on Linux, install a `cups-client` package if they're missing.
  (Windows isn't supported - CUPS is Unix-specific.)
- The target printer already added on this machine.

## Install

Same venv as the rest of this repo:

```bash
cd /path/to/iocane
python3 -m venv .venv   # skip if you already set this up for luckjingle-mcp
.venv/bin/pip install -e .
```

## Register the MCP server with Claude Code

```bash
claude mcp add netprint -- /path/to/iocane/.venv/bin/netprint-mcp
```

Or add directly to your MCP config (e.g. `~/.claude.json` or `.mcp.json`):

```json
{
  "mcpServers": {
    "netprint": {
      "command": "/path/to/iocane/.venv/bin/netprint-mcp"
    }
  }
}
```

## Tools

- `list_printers()` - list printers already configured on this machine,
  with their current status (idle, stopped, printing, etc)
- `print_document(path, printer=None, copies=1)` - print a file; `printer`
  defaults to the system default printer if not given

## Troubleshooting

- **"'lpstat' not found"**: CUPS's command-line tools aren't installed -
  see Requirements above.
- **"No such printer"**: the name has to match exactly what
  `list_printers()` (or `lpstat -p`) reports, which may not be identical to
  the display name shown in System Settings.
- **"No printer specified and no default printer is configured"**: either
  pass `printer=` explicitly, or set a default with `lpoptions -d <name>`.
