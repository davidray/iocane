# MCP tool layer for printing documents to a printer already configured on
# this machine via CUPS (lp/lpstat) - e.g. a network HP printer set up once
# in System Settings > Printers & Scanners. Unlike luckjingle_mcp, this
# needs no separate daemon process: printing via CUPS is a normal
# subprocess call, with no macOS permission gate to route around.

from mcp.server.mcpserver import MCPServer

from . import cups

mcp = MCPServer("netprint")


@mcp.tool()
def list_printers() -> list[dict]:
    """List printers already configured on this machine (added once via
    System Settings > Printers & Scanners, or `lpadmin`), with their
    current status."""
    return cups.list_printers()


@mcp.tool()
def print_document(path: str, printer: str | None = None, copies: int = 1) -> str:
    """Print a document (PDF, image, plain text, etc) to a printer already
    configured on this machine - no need to open it in another app first.

    path is the file to print. printer names which configured printer to
    use (see list_printers) - leave unset to use the system default
    printer. copies is how many copies to print.
    """
    return cups.print_document(path, printer=printer, copies=copies)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
