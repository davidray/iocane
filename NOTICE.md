# Notice / Credits

The Bluetooth protocol implementation in `luckjingle_mcp/printer.py` and
`luckjingle_mcp/dither.py` is adapted from reverse-engineering work by:

- **ChiaraCannolee** - https://github.com/ChiaraCannolee/thermal-pocket-printer-basic
  (MIT license). Decompiled the "Luck Jingle" Android app
  (`com.dingdang.newprint`) with JADX and documented the LuckPrinter SDK's
  BLE protocol (`PROTOCOL.md` in that repo) - the standard ESC/POS `GS v 0`
  raster command plus vendor control commands this driver uses.

An earlier version of this driver was based on a different, incompatible
protocol variant documented by:

- Lakr Aream & Lyn Chen - https://github.com/lsongdev/luckjingle-d1-printer
  (CC BY 4.0)
- https://github.com/LynMoe/DingdangD1-PoC
- https://github.com/Lakr233/GGLyn

That variant targeted a printer branded "D1X"; it connected fine to our
"PPS1_6306_BLE" unit (same BLE service/characteristic layout) but used an
incompatible image command format, so nothing printed. Kept here for
context in case anyone with a genuine D1X-family printer needs it instead.

None of these projects are affiliated with this MCP server; this is an
independent adaptation for use as an MCP tool.
