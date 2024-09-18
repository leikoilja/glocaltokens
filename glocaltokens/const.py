"""Globally used constants."""

from __future__ import annotations

from typing import Final

ACCESS_TOKEN_APP_NAME: Final = "com.google.android.apps.chromecast.app"
ACCESS_TOKEN_CLIENT_SIGNATURE: Final = "24bb24c05e47e0aefa68a58a766179d9b613a600"
ACCESS_TOKEN_DURATION: Final = 60 * 60
ACCESS_TOKEN_SERVICE: Final = "oauth2:https://www.google.com/accounts/OAuthLogin"

ANDROID_ID_LENGTH: Final = 16
MASTER_TOKEN_LENGTH: Final = 216
ACCESS_TOKEN_LENGTH: Final = 315
LOCAL_AUTH_TOKEN_LENGTH: Final = 108

GOOGLE_HOME_FOYER_API: Final = "googlehomefoyer-pa.googleapis.com:443"

HOMEGRAPH_DURATION: Final = 24 * 60 * 60

DISCOVERY_TIMEOUT: Final = 2
DEFAULT_DISCOVERY_PORT: Final = 0

GOOGLE_HOME_MODELS: Final = [
    "Google Home",
    "Google Home Mini",
    "Google Nest Mini",
    "Lenovo Smart Clock",
]
GOOGLE_CAST_GROUP: Final = "Google Cast Group"

JSON_KEY_DEVICE_NAME: Final = "device_name"
JSON_KEY_NETWORK_DEVICE: Final = "network_device"
JSON_KEY_HARDWARE: Final = "hardware"
JSON_KEY_IP: Final = "ip"
JSON_KEY_LOCAL_AUTH_TOKEN: Final = "local_auth_token"
JSON_KEY_PORT: Final = "port"
