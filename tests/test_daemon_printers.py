"""Exercise daemon.py's printer CRUD/selection handlers directly, without
going over a real socket - these are plain synchronous methods on Handler,
so a bare instance with a stubbed _send_json is enough to call them."""

import pytest

from luckjingle_mcp import config as config_module
from luckjingle_mcp import daemon as daemon_module


@pytest.fixture(autouse=True)
def temp_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "config.json")
    daemon_module._printer_locks.clear()


class FakeHandler:
    def __init__(self):
        self.response = None
        self.status = None

    def _send_json(self, obj, status=200):
        self.response = obj
        self.status = status


def call(method_name: str, body: dict):
    handler = FakeHandler()
    getattr(daemon_module.Handler, method_name)(handler, body)
    return handler.response, handler.status


def test_add_printer_first_one_becomes_active():
    resp, status = call("_add_printer", {"name": "kitchen", "address": "AA:BB:CC"})

    assert status == 200
    assert resp == {"ok": True, "active_printer": "kitchen"}
    cfg = config_module.load_config()
    assert cfg["printers"]["kitchen"] == {"driver": "luckprinter", "address": "AA:BB:CC"}


def test_add_printer_second_one_does_not_change_active():
    call("_add_printer", {"name": "kitchen", "address": "AA:BB:CC"})

    resp, _ = call("_add_printer", {"name": "office", "address": "DD:EE:FF"})

    assert resp == {"ok": True, "active_printer": "kitchen"}


def test_add_printer_upserts_an_existing_name():
    call("_add_printer", {"name": "kitchen", "address": "AA:BB:CC"})

    call("_add_printer", {"name": "kitchen", "address": "NEW:ADDRESS"})

    cfg = config_module.load_config()
    assert cfg["printers"]["kitchen"]["address"] == "NEW:ADDRESS"
    assert len(cfg["printers"]) == 1


def test_add_printer_rejects_unknown_driver():
    with pytest.raises(ValueError, match="nonexistent"):
        call("_add_printer", {"name": "x", "address": "AA", "driver": "nonexistent"})


def test_select_printer_switches_active():
    call("_add_printer", {"name": "kitchen", "address": "AA"})
    call("_add_printer", {"name": "office", "address": "BB"})

    resp, _ = call("_select_printer", {"name": "office"})

    assert resp == {"ok": True, "active_printer": "office"}
    assert config_module.load_config()["active_printer"] == "office"


def test_select_printer_unknown_name_raises():
    with pytest.raises(ValueError, match="nonexistent"):
        call("_select_printer", {"name": "nonexistent"})


def test_remove_printer_falls_back_to_another_remaining_printer():
    call("_add_printer", {"name": "kitchen", "address": "AA"})
    call("_add_printer", {"name": "office", "address": "BB"})
    call("_select_printer", {"name": "kitchen"})

    resp, _ = call("_remove_printer", {"name": "kitchen"})

    assert resp == {"ok": True, "active_printer": "office"}
    assert "kitchen" not in config_module.load_config()["printers"]


def test_remove_printer_that_is_not_active_leaves_active_unchanged():
    call("_add_printer", {"name": "kitchen", "address": "AA"})
    call("_add_printer", {"name": "office", "address": "BB"})

    resp, _ = call("_remove_printer", {"name": "office"})

    assert resp == {"ok": True, "active_printer": "kitchen"}


def test_remove_last_printer_leaves_no_active_printer():
    call("_add_printer", {"name": "kitchen", "address": "AA"})

    resp, _ = call("_remove_printer", {"name": "kitchen"})

    assert resp == {"ok": True, "active_printer": None}
    assert config_module.load_config()["active_printer"] is None


def test_remove_printer_unknown_name_raises():
    with pytest.raises(ValueError, match="nonexistent"):
        call("_remove_printer", {"name": "nonexistent"})


def test_list_printers_marks_the_active_one():
    call("_add_printer", {"name": "kitchen", "address": "AA"})
    call("_add_printer", {"name": "office", "address": "BB"})

    resp, _ = call("_list_printers", {})

    by_name = {p["name"]: p for p in resp["printers"]}
    assert by_name["kitchen"]["active"] is True
    assert by_name["office"]["active"] is False
    assert resp["active_printer"] == "kitchen"


def test_set_options_with_no_name_creates_and_activates_default():
    resp, _ = call("_set_options", {"width": 400})

    assert resp["width"] == 400
    cfg = config_module.load_config()
    assert cfg["active_printer"] == "default"
    assert cfg["printers"]["default"]["width"] == 400


def test_set_options_targets_named_printer_without_switching_active():
    call("_add_printer", {"name": "kitchen", "address": "AA"})
    call("_add_printer", {"name": "office", "address": "BB"})

    resp, _ = call("_set_options", {"name": "office", "width": 400})

    assert resp["width"] == 400
    cfg = config_module.load_config()
    assert cfg["active_printer"] == "kitchen"  # unchanged by targeting "office"
    assert cfg["printers"]["office"]["width"] == 400
    assert "width" not in cfg["printers"]["kitchen"]


def test_set_options_unknown_printer_name_raises():
    with pytest.raises(ValueError, match="nonexistent"):
        call("_set_options", {"name": "nonexistent", "width": 400})
