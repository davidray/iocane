import json

from luckjingle_mcp import config as config_module


def _use_temp_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "config.json")


def test_migrate_v1_flat_config_to_v2(tmp_path, monkeypatch):
    _use_temp_config(tmp_path, monkeypatch)
    config_module.CONFIG_PATH.write_text(
        json.dumps(
            {
                "address": "AA:BB:CC:DD:EE:FF",
                "width": 400,
                "density": 2,
                "_auth_token": "sometoken",
            }
        )
    )

    cfg = config_module.load_config()

    assert cfg["_schema_version"] == 2
    assert cfg["active_printer"] == "default"
    assert cfg["printers"] == {
        "default": {
            "driver": "luckprinter",
            "address": "AA:BB:CC:DD:EE:FF",
            "width": 400,
            "density": 2,
            "font_path": None,
        }
    }
    assert cfg["_auth_token"] == "sometoken"

    # Migration is persisted, not just returned in memory.
    on_disk = json.loads(config_module.CONFIG_PATH.read_text())
    assert on_disk["_schema_version"] == 2
    assert on_disk["printers"]["default"]["address"] == "AA:BB:CC:DD:EE:FF"


def test_migrate_empty_config_has_no_printers(tmp_path, monkeypatch):
    _use_temp_config(tmp_path, monkeypatch)

    cfg = config_module.load_config()

    assert cfg == {"_schema_version": 2, "printers": {}, "active_printer": None}


def test_migrate_v1_config_with_no_address_has_no_printers(tmp_path, monkeypatch):
    _use_temp_config(tmp_path, monkeypatch)
    config_module.CONFIG_PATH.write_text(json.dumps({"_auth_token": "sometoken"}))

    cfg = config_module.load_config()

    assert cfg["printers"] == {}
    assert cfg["active_printer"] is None
    assert cfg["_auth_token"] == "sometoken"


def test_already_current_config_is_not_rewritten(tmp_path, monkeypatch):
    _use_temp_config(tmp_path, monkeypatch)
    config_module.load_config()  # first load: migrates the fresh/empty config and saves it

    calls = []
    real_save_config = config_module.save_config

    def spy_save_config(cfg):
        calls.append(cfg)
        real_save_config(cfg)

    monkeypatch.setattr(config_module, "save_config", spy_save_config)

    config_module.load_config()

    assert calls == []


def test_get_or_create_token_is_stable_across_migration(tmp_path, monkeypatch):
    _use_temp_config(tmp_path, monkeypatch)

    token_a = config_module.get_or_create_token()
    token_b = config_module.get_or_create_token()

    assert token_a == token_b
    cfg = config_module.load_config()
    assert cfg["_auth_token"] == token_a


def test_get_printer_by_name_and_by_active():
    cfg = {
        "_schema_version": 2,
        "printers": {"kitchen": {"address": "1"}, "office": {"address": "2"}},
        "active_printer": "office",
    }

    assert config_module.get_printer(cfg, None) == {"address": "2"}
    assert config_module.get_printer(cfg, "kitchen") == {"address": "1"}
    assert config_module.get_printer(cfg, "nonexistent") is None


def test_get_printer_with_no_active_printer_set():
    cfg = {"_schema_version": 2, "printers": {}, "active_printer": None}

    assert config_module.get_printer(cfg, None) is None
