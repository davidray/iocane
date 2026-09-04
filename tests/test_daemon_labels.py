"""Exercise daemon.py's saved-label/border handlers: CRUD (direct method
calls, like test_daemon_printers.py) plus print_label/print_saved_label,
which need the daemon's asyncio loop actually running (like
test_daemon_locking.py) since they go through _open_printer/_run_coro."""

import threading
import time

import pytest
from PIL import Image

from luckjingle_mcp import config as config_module
from luckjingle_mcp import daemon as daemon_module


@pytest.fixture(autouse=True)
def temp_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "config.json")
    daemon_module._printer_locks.clear()


@pytest.fixture
def running_loop():
    thread = threading.Thread(target=daemon_module._run_loop, daemon=True)
    thread.start()
    time.sleep(0.05)  # let the loop actually start running
    yield
    daemon_module._loop.call_soon_threadsafe(daemon_module._loop.stop)


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


def _make_border_file(tmp_path, name="border.png", color=(10, 20, 30)):
    path = tmp_path / name
    Image.new("RGB", (20, 20), color).save(path)
    return path


# --- borders -------------------------------------------------------------


def test_save_border_then_list_and_remove(tmp_path):
    path = _make_border_file(tmp_path)

    resp, status = call("_save_border", {"name": "kittens", "image_path": str(path)})
    assert status == 200
    assert resp == {"ok": True}

    resp, _ = call("_list_borders", {})
    assert resp == {"borders": ["kittens"]}

    stored_file = config_module.load_config()["borders"]["kittens"]["file"]
    assert (config_module.borders_dir() / stored_file).exists()

    call("_remove_border", {"name": "kittens"})

    assert config_module.load_config()["borders"] == {}
    assert not (config_module.borders_dir() / stored_file).exists()


def test_save_border_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        call("_save_border", {"name": "x", "image_path": "/no/such/file.png"})


def test_save_border_overwriting_a_name_replaces_the_stored_file(tmp_path):
    path_a = _make_border_file(tmp_path, "a.png", (10, 10, 10))
    call("_save_border", {"name": "kittens", "image_path": str(path_a)})
    old_file = config_module.load_config()["borders"]["kittens"]["file"]

    path_b = _make_border_file(tmp_path, "b.png", (200, 200, 200))
    call("_save_border", {"name": "kittens", "image_path": str(path_b)})

    new_file = config_module.load_config()["borders"]["kittens"]["file"]
    assert new_file != old_file
    assert not (config_module.borders_dir() / old_file).exists()
    assert (config_module.borders_dir() / new_file).exists()


def test_remove_border_unknown_name_raises():
    with pytest.raises(ValueError, match="nonexistent"):
        call("_remove_border", {"name": "nonexistent"})


def test_load_border_raises_a_clean_error_if_the_file_is_missing_despite_the_config_entry(tmp_path):
    # Simulates the race between a concurrent remove_border deleting the
    # file and a print job that already resolved the config entry: the
    # file lookup should still fail as "no such border", not a raw
    # FileNotFoundError.
    path = _make_border_file(tmp_path)
    call("_save_border", {"name": "kittens", "image_path": str(path)})
    stored_file = config_module.load_config()["borders"]["kittens"]["file"]
    (config_module.borders_dir() / stored_file).unlink()

    with pytest.raises(ValueError, match="kittens"):
        daemon_module._load_border("kittens")


# --- labels ----------------------------------------------------------------


def test_save_label_then_list_and_remove():
    resp, status = call(
        "_save_label", {"name": "sign", "text": "Hello", "font_size": 30, "align": "right"}
    )
    assert status == 200
    assert resp == {"ok": True}

    resp, _ = call("_list_labels", {})
    assert resp == {
        "labels": [
            {
                "name": "sign",
                "text": "Hello",
                "font_size": 30,
                "align": "right",
                "border": None,
                "dither": None,
            }
        ]
    }

    call("_remove_label", {"name": "sign"})

    assert config_module.load_config()["labels"] == {}


def test_save_label_defaults_font_size_and_align():
    call("_save_label", {"name": "sign", "text": "Hi"})

    cfg = config_module.load_config()
    assert cfg["labels"]["sign"] == {
        "text": "Hi",
        "font_size": 24,
        "align": "center",
        "border": None,
        "dither": None,
    }


def test_save_label_with_unknown_border_raises():
    with pytest.raises(ValueError, match="nonexistent"):
        call("_save_label", {"name": "sign", "text": "Hi", "border": "nonexistent"})

    assert config_module.load_config()["labels"] == {}


def test_save_label_requires_text():
    with pytest.raises(ValueError, match="text"):
        call("_save_label", {"name": "sign", "text": ""})

    assert config_module.load_config()["labels"] == {}


def test_save_label_rejects_non_positive_font_size():
    with pytest.raises(ValueError, match="font_size"):
        call("_save_label", {"name": "sign", "text": "Hi", "font_size": 0})


def test_remove_label_unknown_name_raises():
    with pytest.raises(ValueError, match="nonexistent"):
        call("_remove_label", {"name": "nonexistent"})


def test_save_label_does_not_open_the_border_image(tmp_path, monkeypatch):
    # save_label only needs to validate that the border name exists - it
    # shouldn't open (and leave dangling) an Image handle to do that.
    path = _make_border_file(tmp_path)
    call("_save_border", {"name": "kittens", "image_path": str(path)})

    opened = []
    original_open = daemon_module.Image.open
    monkeypatch.setattr(
        daemon_module.Image, "open", lambda *a, **kw: opened.append(a) or original_open(*a, **kw)
    )

    call("_save_label", {"name": "sign", "text": "Hi", "border": "kittens"})

    assert opened == []


# --- printing (composition + reprint, via a fake printer session) ---------


class FakePrinterSession:
    def __init__(self, width=200, font_path=None):
        self.width = width
        self.font_path = font_path
        self.printed = []
        self.ended = False
        self.closed = False

    async def print_image(self, img, dither):
        self.printed.append((img, dither))

    async def print_end(self):
        self.ended = True

    async def close(self):
        self.closed = True


@pytest.fixture
def fake_printer(monkeypatch):
    session = FakePrinterSession()

    async def fake_open_printer(name=None):
        return session

    monkeypatch.setattr(daemon_module, "_open_printer", fake_open_printer)
    return session


def test_print_label_sends_a_composed_image(fake_printer, running_loop):
    resp, status = call("_print_label", {"text": "Flux Capacitor"})

    assert status == 200
    assert resp == {"ok": True, "saved_as": None}
    assert len(fake_printer.printed) == 1
    img, dither = fake_printer.printed[0]
    assert img.width == fake_printer.width
    assert dither is False  # no border -> crisp text, no dithering
    assert fake_printer.ended
    assert fake_printer.closed


def test_print_label_with_border_dithers(tmp_path, fake_printer, running_loop):
    path = _make_border_file(tmp_path)
    call("_save_border", {"name": "kittens", "image_path": str(path)})

    call("_print_label", {"text": "Flux Capacitor", "border": "kittens"})

    _img, dither = fake_printer.printed[0]
    assert dither is True


def test_print_label_dither_override_forces_dither_true_without_a_border(fake_printer, running_loop):
    call("_print_label", {"text": "hi", "dither": True})

    _img, dither = fake_printer.printed[0]
    assert dither is True


def test_print_label_dither_override_forces_dither_false_with_a_border(
    tmp_path, fake_printer, running_loop
):
    path = _make_border_file(tmp_path)
    call("_save_border", {"name": "kittens", "image_path": str(path)})

    call("_print_label", {"text": "hi", "border": "kittens", "dither": False})

    _img, dither = fake_printer.printed[0]
    assert dither is False


def test_print_label_rejects_non_boolean_dither(fake_printer):
    with pytest.raises(ValueError, match="dither"):
        call("_print_label", {"text": "hi", "dither": "yes"})

    assert fake_printer.printed == []


def test_print_label_rejects_non_positive_font_size(fake_printer):
    with pytest.raises(ValueError, match="font_size"):
        call("_print_label", {"text": "hi", "font_size": -5})

    assert fake_printer.printed == []


def test_print_label_unknown_border_raises(fake_printer):
    with pytest.raises(ValueError, match="nonexistent"):
        call("_print_label", {"text": "hi", "border": "nonexistent"})

    assert fake_printer.printed == []


def test_print_label_requires_text(fake_printer):
    with pytest.raises(ValueError, match="text"):
        call("_print_label", {"text": ""})

    assert fake_printer.printed == []


def test_print_label_save_as_persists_the_label(fake_printer, running_loop):
    resp, _ = call(
        "_print_label", {"text": "Flux Capacitor", "save_as": "flux", "align": "right"}
    )

    assert resp["saved_as"] == "flux"
    cfg = config_module.load_config()
    assert cfg["labels"]["flux"] == {
        "text": "Flux Capacitor",
        "font_size": 24,
        "align": "right",
        "border": None,
        "dither": None,
    }


def test_print_saved_label_reprints_by_name(fake_printer, running_loop):
    call("_save_label", {"name": "flux", "text": "Flux Capacitor", "align": "right"})

    resp, status = call("_print_saved_label", {"name": "flux"})

    assert status == 200
    assert resp == {"ok": True}
    assert len(fake_printer.printed) == 1


def test_print_saved_label_unknown_name_raises(fake_printer):
    with pytest.raises(ValueError, match="nonexistent"):
        call("_print_saved_label", {"name": "nonexistent"})

    assert fake_printer.printed == []


def test_print_saved_label_with_removed_border_raises_a_clean_error(fake_printer, running_loop, tmp_path):
    path = _make_border_file(tmp_path)
    call("_save_border", {"name": "kittens", "image_path": str(path)})
    call("_save_label", {"name": "flux", "text": "Flux Capacitor", "border": "kittens"})

    call("_remove_border", {"name": "kittens"})

    with pytest.raises(ValueError, match="kittens"):
        call("_print_saved_label", {"name": "flux"})
    assert fake_printer.printed == []
