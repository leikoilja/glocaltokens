"""Tests package."""

from __future__ import annotations

from contextlib import contextmanager
import sys
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from collections.abc import Iterator


@contextmanager
def without_zeroconf() -> Iterator[None]:
    """Make zeroconf impossible to import, as without the discovery extra.

    glocaltokens.scanner and zeroconf's modules are unloaded meanwhile, so
    importing them runs again, and they are restored afterwards.
    """
    # None in sys.modules makes importing zeroconf raise ModuleNotFoundError
    with patch.dict(sys.modules, {"zeroconf": None}):
        for name in list(sys.modules):
            if name == "glocaltokens.scanner" or name.startswith("zeroconf."):
                del sys.modules[name]
        yield
