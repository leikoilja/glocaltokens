"""Tests package."""

from __future__ import annotations

from contextlib import contextmanager
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import ModuleType


def _unload_discovery() -> dict[str, ModuleType]:
    """Remove glocaltokens.scanner and zeroconf's modules from sys.modules, and return them."""
    names = [
        name
        for name in sys.modules
        if name == "glocaltokens.scanner" or name.partition(".")[0] == "zeroconf"
    ]
    return {name: sys.modules.pop(name) for name in names}


@contextmanager
def without_zeroconf() -> Iterator[None]:
    """Make zeroconf impossible to import, as without the discovery extra.

    Meanwhile, importing glocaltokens.scanner runs it again, and fails.
    Only those modules are restored afterwards, so that any other module
    imported meanwhile stays loaded.
    """
    unloaded = _unload_discovery()
    # None in sys.modules makes importing zeroconf raise ModuleNotFoundError
    sys.modules["zeroconf"] = None  # type: ignore[assignment]
    try:
        yield
    finally:
        _unload_discovery()
        sys.modules.update(unloaded)
