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


def load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


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
