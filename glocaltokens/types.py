"""Types used for package typing"""
from __future__ import annotations

from typing import TypedDict


class NetworkDeviceDict(TypedDict):
    """Typed dict for network_device field of DeviceDict."""

    ip: str | None
    port: int | None


class DeviceDict(TypedDict):
    """Typed dict for Device representation as dict."""

    device_id: str
    device_name: str
    hardware: str | None
    network_device: NetworkDeviceDict
    local_auth_token: str | None
