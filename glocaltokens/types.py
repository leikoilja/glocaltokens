"""Types used for package typing"""

from typing import TypedDict, Union


class GoogleDeviceDict(TypedDict):
    """Typed dict for google_device field of DeviceDict."""

    ip: Union[str, None]
    port: Union[int, None]


class DeviceDict(TypedDict):
    """Typed dict for Device representation as dict."""

    device_id: str
    device_name: str
    hardware: Union[str, None]
    google_device: GoogleDeviceDict
    local_auth_token: Union[str, None]
