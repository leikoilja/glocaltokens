"""Types used for package typing"""
from __future__ import annotations

from typing import TypedDict


class GoogleDeviceDict(TypedDict):
    """Typed dict for google_device field of DeviceDict."""

    ip: str | None
    port: int | None


class DeviceDict(TypedDict):
    """Typed dict for Device representation as dict."""

    device_id: str
    device_name: str
    hardware: str | None
    google_device: GoogleDeviceDict
    local_auth_token: str | None
