"""Globally used constants"""
from typing import Final, List

ACCESS_TOKEN_APP_NAME: Final[str] = "com.google.android.apps.chromecast.app"
ACCESS_TOKEN_CLIENT_SIGNATURE: Final[str] = "24bb24c05e47e0aefa68a58a766179d9b613a600"
ACCESS_TOKEN_DURATION: Final[int] = 60 * 60
ACCESS_TOKEN_SERVICE: Final[str] = "oauth2:https://www.google.com/accounts/OAuthLogin"

ANDROID_ID_LENGTH: Final[int] = 14
MASTER_TOKEN_LENGTH: Final[int] = 216
ACCESS_TOKEN_LENGTH: Final[int] = 315
LOCAL_AUTH_TOKEN_LENGTH: Final[int] = 108

GOOGLE_HOME_FOYER_API: Final[str] = "googlehomefoyer-pa.googleapis.com:443"

HOMEGRAPH_DURATION: Final[int] = 24 * 60 * 60

DISCOVERY_TIMEOUT: Final[int] = 2

GOOGLE_HOME_MODELS: Final[List[str]] = [
    "Google Home",
    "Google Home Mini",
    "Google Nest Mini",
    "Lenovo Smart Clock",
]

JSON_KEY_DEVICE_NAME: Final[str] = "device_name"
JSON_KEY_GOOGLE_DEVICE: Final[str] = "google_device"
JSON_KEY_HARDWARE: Final[str] = "hardware"
JSON_KEY_IP: Final[str] = "ip"
JSON_KEY_LOCAL_AUTH_TOKEN: Final[str] = "local_auth_token"
JSON_KEY_PORT: Final[str] = "port"
