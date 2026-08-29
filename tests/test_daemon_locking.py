"""Verify per-printer locking: two printers can print concurrently, but a
single printer still serializes its own overlapping print jobs (protecting
the one BLE connection it actually has)."""

import asyncio
import threading
import time

import pytest

from luckjingle_mcp import config as config_module
from luckjingle_mcp import daemon as daemon_module


@pytest.fixture
def running_daemon_loop(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "config.json")
    daemon_module._printer_locks.clear()
    thread = threading.Thread(target=daemon_module._run_loop, daemon=True)
    thread.start()
    time.sleep(0.05)  # let the loop actually start running
    yield
    daemon_module._loop.call_soon_threadsafe(daemon_module._loop.stop)


class FakePrinterSession:
    """Tracks, per printer name and globally, how many "print jobs" are
    concurrently in flight - lets a test prove locking is per-name instead
    of one lock serializing everything."""

    lock = threading.Lock()
    active_by_name: dict = {}
    max_active_by_name: dict = {}
    max_global_active = 0
    _global_active = 0

    def __init__(self, name: str, delay: float):
        self.name = name
        self.delay = delay

    async def print_text(self, *_args, **_kwargs):
        cls = FakePrinterSession
        with cls.lock:
            n = cls.active_by_name.get(self.name, 0) + 1
            cls.active_by_name[self.name] = n
            cls.max_active_by_name[self.name] = max(cls.max_active_by_name.get(self.name, 0), n)
            cls._global_active += 1
            cls.max_global_active = max(cls.max_global_active, cls._global_active)
        await asyncio.sleep(self.delay)
        with cls.lock:
            cls.active_by_name[self.name] -= 1
            cls._global_active -= 1

    async def print_end(self):
        pass

    async def close(self):
        pass


def _run_print(name: str):
    handler = object.__new__(daemon_module.Handler)
    handler._send_json = lambda *_args, **_kwargs: None
    handler._print_text({"text": "hi", "printer": name})


def test_different_printers_print_concurrently_but_each_serializes_itself(
    running_daemon_loop, monkeypatch
):
    FakePrinterSession.active_by_name = {}
    FakePrinterSession.max_active_by_name = {}
    FakePrinterSession.max_global_active = 0
    FakePrinterSession._global_active = 0

    async def fake_open_printer(name=None):
        return FakePrinterSession(name, delay=0.15)

    monkeypatch.setattr(daemon_module, "_open_printer", fake_open_printer)

    names = ["kitchen", "office"] * 3  # 3 jobs per printer, interleaved
    threads = [threading.Thread(target=_run_print, args=(name,)) for name in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert all(not t.is_alive() for t in threads), "a print job never completed (deadlock?)"

    # Each printer's own jobs are still serialized - only one BLE
    # "connection" active per printer name at a time.
    assert FakePrinterSession.max_active_by_name["kitchen"] == 1
    assert FakePrinterSession.max_active_by_name["office"] == 1
    # But kitchen and office overlap with each other - proof this isn't
    # one global lock serializing every printer behind every other one.
    assert FakePrinterSession.max_global_active >= 2
