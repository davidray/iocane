# Notice / Credits

The Bluetooth protocol implementation in
`luckjingle_mcp/drivers/luckprinter.py` and `luckjingle_mcp/dither.py` (the
`luckprinter` driver) is adapted from reverse-engineering work by:

- **ChiaraCannolee** - https://github.com/ChiaraCannolee/thermal-pocket-printer-basic
  (MIT license). Decompiled the "Luck Jingle" Android app
  (`com.dingdang.newprint`) with JADX and documented the LuckPrinter SDK's
  BLE protocol (`PROTOCOL.md` in that repo) - the standard ESC/POS `GS v 0`
  raster command plus vendor control commands this driver uses.

## D1X driver (experimental, unverified)

`luckjingle_mcp/drivers/d1x.py` (the `d1x` driver) targets a different,
incompatible protocol variant for printers branded "D1X" / "Dingdang D1",
documented by:

- Lakr Aream & Lyn Chen - https://github.com/lsongdev/luckjingle-d1-printer
  (CC BY 4.0)
- https://github.com/LynMoe/DingdangD1-PoC
- https://github.com/Lakr233/GGLyn

An earlier version of this project's driver was based on this same
protocol family: it connected fine to this project's own "PPS1_6306_BLE"
unit (same BLE service/characteristic layout as `luckprinter`) but used an
image command format that never produced any output on that hardware, so
it was dropped. The `d1x` driver added back later specifically follows
GGLyn's implementation rather than the other two sources - GGLyn's was
reverse-engineered by decompiling the vendor app with Ghidra and describes
a standard, byte-aligned `GS v 0` command identical in structure to
`luckprinter`'s, whereas the other two sources' own code comments describe
their image-framing math as guesswork. Whether GGLyn's version actually
fixes the "connects but doesn't print" problem is **unconfirmed** - this
driver has not been tested against real D1X-family hardware. See
`luckjingle_mcp/drivers/d1x.py`'s module docstring for the full reasoning,
and the README's "Adding support for a new printer" section if you have
real hardware and can help verify it.

None of these projects are affiliated with this MCP server; this is an
independent adaptation for use as an MCP tool.
