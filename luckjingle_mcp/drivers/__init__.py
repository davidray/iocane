from .base import DEFAULT_WIDTH, PrinterDriver, PrinterSession
from .d1x import D1XDriver
from .luckprinter import LuckPrinterDriver

DRIVERS: dict[str, type[PrinterDriver]] = {
    "luckprinter": LuckPrinterDriver,
    # Experimental / unverified against real hardware - see d1x.py's
    # module docstring before relying on this.
    "d1x": D1XDriver,
}


def get_driver_class(name: str) -> type[PrinterDriver]:
    try:
        return DRIVERS[name]
    except KeyError:
        raise ValueError(
            f"Unknown printer driver {name!r}. Known drivers: {', '.join(sorted(DRIVERS))}"
        ) from None


__all__ = ["DEFAULT_WIDTH", "PrinterDriver", "PrinterSession", "DRIVERS", "get_driver_class"]
