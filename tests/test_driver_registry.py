import pytest

from luckjingle_mcp.drivers import DRIVERS, PrinterDriver, get_driver_class
from luckjingle_mcp.drivers.luckprinter import LuckPrinterDriver


def test_known_driver_resolves_to_its_class():
    assert get_driver_class("luckprinter") is LuckPrinterDriver


def test_unknown_driver_raises_with_known_drivers_listed():
    with pytest.raises(ValueError, match="luckprinter"):
        get_driver_class("nonexistent-driver")


def test_luckprinter_driver_implements_the_full_interface():
    # PrinterDriver is an ABC - instantiating a subclass that's missing an
    # abstract method raises TypeError at construction time. This is
    # mostly a canary for future drivers: forgetting one method fails
    # loudly here instead of at print time on someone's real hardware.
    driver = LuckPrinterDriver()
    assert isinstance(driver, PrinterDriver)
    assert driver.write_characteristic
    assert driver.notify_characteristic
