import json
import os
import secrets
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "luckjingle-mcp" / "config.json"

# Shared secret the MCP server and daemon use to authenticate requests to
# each other over the localhost HTTP API. Kept in the same config file since
# both processes already read/write it. Required on every request so a page
# in the user's browser can't drive the daemon's API via a same-origin-exempt
# "simple" cross-origin request (e.g. a text/plain fetch with a JSON body
# needs no CORS preflight): requiring a custom header forces the browser to
# preflight, and since the daemon sends no CORS headers, the preflight - and
# thus the real request - gets blocked.
TOKEN_KEY = "_auth_token"
AUTH_HEADER = "X-Luckjingle-Token"

# Config schema: "printers" is a dict of name -> {driver, address, width,
# density, font_path}, with "active_printer" naming the one print calls use
# when no printer is named explicitly. "labels" is a dict of name -> {text,
# font_size, align, border}, saved by save_label/print_label(save_as=...)
# for later reprinting. "borders" is a dict of name -> {file}, where file
# names a PNG under borders_dir() holding a saved decorative image used to
# frame a label's text. Schema version 1 was a single flat printer block
# (address/width/density/font_path at the top level, no "driver" field -
# implicitly the only driver that ever existed, "luckprinter"). Version 2
# introduced multi-printer support ("printers"/"active_printer"). Version 3
# added "labels"/"borders".
SCHEMA_VERSION = 3
DEFAULT_DRIVER = "luckprinter"
DEFAULT_PRINTER_NAME = "default"


def _migrate(cfg: dict) -> tuple[dict, bool]:
    """Upgrade a v1/v2 (or empty/fresh) config to the current schema.
    Returns (config, changed) - changed is False if cfg was already
    current, so callers can skip an unnecessary rewrite."""
    if (
        cfg.get("_schema_version") == SCHEMA_VERSION
        and "printers" in cfg
        and "labels" in cfg
        and "borders" in cfg
    ):
        return cfg, False

    printers = cfg.get("printers")
    if printers is None:
        printers = {}
        if cfg.get("address"):
            printers[DEFAULT_PRINTER_NAME] = {
                "driver": DEFAULT_DRIVER,
                "address": cfg["address"],
                "width": cfg.get("width", 384),
                "density": cfg.get("density"),
                "font_path": cfg.get("font_path"),
            }

    active = cfg.get("active_printer")
    if active not in printers:
        active = next(iter(printers), None)

    migrated = {
        "_schema_version": SCHEMA_VERSION,
        "printers": printers,
        "active_printer": active,
        "labels": cfg.get("labels", {}),
        "borders": cfg.get("borders", {}),
    }
    if TOKEN_KEY in cfg:
        migrated[TOKEN_KEY] = cfg[TOKEN_KEY]
    return migrated, True


def load_config() -> dict:
    if CONFIG_PATH.exists():
        cfg = json.loads(CONFIG_PATH.read_text())
    else:
        cfg = {}
    cfg, changed = _migrate(cfg)
    if changed:
        save_config(cfg)
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    # Config now carries an auth token; keep it readable only by the owner.
    os.chmod(CONFIG_PATH, 0o600)


def load_public_config() -> dict:
    """load_config() with the auth token stripped, for anything that echoes
    config back to the MCP client/tool caller."""
    cfg = dict(load_config())
    cfg.pop(TOKEN_KEY, None)
    return cfg


def get_or_create_token() -> str:
    """Shared secret used to authenticate requests between server.py and
    daemon.py. Whichever process runs first generates and persists it."""
    cfg = load_config()
    token = cfg.get(TOKEN_KEY)
    if not token:
        token = secrets.token_hex(32)
        cfg[TOKEN_KEY] = token
        save_config(cfg)
    return token


def borders_dir() -> Path:
    """Directory where saved border images (PNG files named by config's
    "borders" entries) live, next to the config file itself. A function
    rather than a constant so it stays correct if CONFIG_PATH is changed
    (e.g. tests monkeypatching it) after this module is imported."""
    return CONFIG_PATH.parent / "borders"


def get_printer(cfg: dict, name: str | None) -> dict | None:
    """Look up a printer profile by name, or the active printer if name is
    None. Returns None if there's no such printer / no active printer set."""
    if name is None:
        name = cfg.get("active_printer")
    if name is None:
        return None
    return cfg.get("printers", {}).get(name)
