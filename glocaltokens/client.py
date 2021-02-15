"""
Credits to rithvikvibhu (https://github.com/rithvikvibhu)
for implementing master and access token fetching
See: https://gist.github.com/rithvikvibhu/952f83ea656c6782fbd0f1645059055d
"""
import logging
import json
from typing import List, Optional

import grpc
from datetime import datetime

from gpsoauth import perform_master_login, perform_oauth
from uuid import getnode as getmac

from .google.internal.home.foyer import v1_pb2_grpc
from .google.internal.home.foyer import v1_pb2
from .scanner import (
    discover_devices,
    GoogleDevice,
)
from .utils import network as net_utils

ACCESS_TOKEN_APP_NAME = "com.google.android.apps.chromecast.app"
ACCESS_TOKEN_CLIENT_SIGNATURE = "24bb24c05e47e0aefa68a58a766179d9b613a600"
ACCESS_TOKEN_SERVICE = "oauth2:https://www.google.com/accounts/OAuthLogin"
GOOGLE_HOME_FOYER_API = "googlehomefoyer-pa.googleapis.com:443"

ACCESS_TOKEN_DURATION = 60 * 60
HOMEGRAPH_DURATION = 24 * 60 * 60

DEBUG = False

logging_level = logging.DEBUG if DEBUG else logging.ERROR
logging.basicConfig(level=logging_level)
LOGGER = logging.getLogger(__name__)


class Device:
    def __init__(self, device_name: str, local_auth_token: str, google_device: Optional[GoogleDevice] = None,
                 ip: Optional[str] = None, port: Optional[int] = None):
        """
        Initializes a Device. Can set or google_device or ip and port
        """
        self.device_name = device_name
        self.local_auth_token = local_auth_token
        self.google_device = google_device
        if google_device:
            self.ip = google_device.ip
            self.port = google_device.port
        else:
            if (ip and not port) or (not ip and port):
                LOGGER.error(
                    "Both ip and port must be set, if one of them is specified."
                )
                return
            self.ip = ip
            self.port = port

        if self.ip and not net_utils.is_valid_ipv4_address(self.ip) and not net_utils.is_valid_ipv4_address(self.ip):
            LOGGER.error("ip must be a valid IP address")
            return

        if self.port and not net_utils.is_valid_port(self.port):
            LOGGER.error("port must be a valid port")
            return

    def __str__(self) -> str:
        return str(self.dict())

    def dict(self) -> []:
        return {
            "device_name": self.device_name,
            "local_auth_token": self.local_auth_token,
            "google_device": {
                "ip": self.ip,
                "port": self.port,
            },
        }


class GLocalAuthenticationTokens:
    def __init__(
            self, username: Optional[str] = None, password: Optional[str] = None,
            master_token: Optional[str] = None, android_id: Optional[str] = None
    ):
        """
        Initialize an GLocalAuthenticationTokens instance with google account
        credentials
        :params
            username: google account username (the first part of email,
                excluding @gmail.com);
            password: google account password (can be app password);
            master_token: google master token (instead of username/password
                combination);
            android_id: the id of an android device. Will be randomly generated
                if not set;

        """
        self.username: Optional[str] = username
        self.password: Optional[str] = password
        self.master_token: Optional[str] = master_token
        self.android_id: Optional[str] = android_id
        if (not self.username or not self.password) and not self.master_token:
            LOGGER.error(
                "You must either provide google username/password "
                "or google master token"
            )
            return
        self.access_token: Optional[str] = None
        self.homegraph = None
        self.access_token_date: Optional[datetime] = None
        self.homegraph_date: Optional[datetime] = None

    @staticmethod
    def _create_mac_string(num: int, splitter: str = ":") -> str:
        mac = hex(num)[2:]
        if mac[-1] == "L":
            mac = mac[:-1]
        pad = max(12 - len(mac), 0)
        mac = "0" * pad + mac
        mac = splitter.join([mac[x: x + 2] for x in range(0, 12, 2)])
        mac = mac.upper()
        return mac

    def get_android_id(self) -> Optional[str]:
        if not self.android_id:
            mac_int = getmac()
            if (mac_int >> 40) % 2:
                LOGGER.error(
                    "a valid MAC could not be determined. "
                    "Provide an android_id (and be "
                    "sure to provide the same one on future runs)."
                )
                return

            android_id = self._create_mac_string(mac_int)
            self.android_id = android_id.replace(":", "")
        LOGGER.debug("Android ID: {}".format(self.android_id))
        return self.android_id

    @staticmethod
    def _token_has_expired(token_date: datetime, token_duration: int) -> bool:
        """Checks if an specified token has expired"""
        return datetime.now().timestamp() - token_date.timestamp() > token_duration

    def get_master_token(self) -> Optional[str]:
        """
        Get google master token from username and password
        """
        if not self.master_token:
            res = perform_master_login(
                self.username, self.password, self.get_android_id()
            )
            if "Token" not in res:
                LOGGER.error("[!] Could not get master token.")
                return
            self.master_token = res["Token"]
        LOGGER.debug("Master token: {}".format(self.master_token))
        return self.master_token

    def get_access_token(self) -> Optional[str]:
        if self.access_token is None or self._token_has_expired(
                self.access_token_date, ACCESS_TOKEN_DURATION
        ):
            res = perform_oauth(
                self.username,
                self.get_master_token(),
                self.get_android_id(),
                app=ACCESS_TOKEN_APP_NAME,
                service=ACCESS_TOKEN_SERVICE,
                client_sig=ACCESS_TOKEN_CLIENT_SIGNATURE,
            )
            if "Auth" not in res:
                LOGGER.error("[!] Could not get access token.")
                return
            self.access_token = res["Auth"]
            self.access_token_date = datetime.now()
        LOGGER.debug("Access token: {}".format(self.access_token))
        return self.access_token

    def get_homegraph(self):
        """
        Returns the entire Google Home Foyer V2 service
        """
        if self.homegraph is None or self._token_has_expired(
                self.homegraph_date, HOMEGRAPH_DURATION
        ):
            scc = grpc.ssl_channel_credentials(root_certificates=None)
            tok = grpc.access_token_call_credentials(self.get_access_token())
            ccc = grpc.composite_channel_credentials(scc, tok)

            with grpc.secure_channel(GOOGLE_HOME_FOYER_API, ccc) as channel:
                rpc_service = v1_pb2_grpc.StructuresServiceStub(channel)
                request = v1_pb2.GetHomeGraphRequest(string1="", num2="")
                response = rpc_service.GetHomeGraph(request)
                self.homegraph = response
            self.homegraph_date = datetime.now()
        return self.homegraph

    def get_google_devices(self, models_list=None) -> [Device]:
        """
        Returns a list of google devices with their local authentication tokens, and IP and ports if set in models_list.

        :param models_list The list of accepted model names.
        """

        # Set models_list to empty list if None
        models_list = models_list if models_list else []

        def find_device(name, devices_list: [GoogleDevice]) -> Optional[GoogleDevice]:
            for device in devices_list:
                if device.name == name:
                    return device
            return None

        def extract_devices(items, network_items) -> [Device]:
            devices_result: [Device] = []
            for item in items:
                if item.local_auth_token != "":
                    # This checks if the current item is a valid model, only if there are models in models_list.
                    # If models_list is empty, the check should be omitted, and accept all items.
                    if models_list and item.hardware.model not in models_list:
                        continue

                    google_device = find_device(item.device_name, network_items) if network_items else None
                    devices_result.append(
                        Device(
                            item.device_name,
                            item.local_auth_token,
                            google_device
                        )
                    )
            return devices_result

        homegraph = self.get_homegraph()
        network_devices = discover_devices(models_list)

        devices = extract_devices(homegraph.home.devices, network_devices)
        LOGGER.debug("Google Home devices: {}".format(devices))

        return devices

    def get_google_devices_json(self, models_list: Optional[List[str]] = None, indent: int = 2) -> str:
        """
        Returns a json list of google devices with their local authentication tokens, and IP and ports if set in
        models_list.

        :param models_list The list of accepted model names.
        :param indent The indentation for the json formatting.
        """
        devices_json = [
            device.dict() for device in self.get_google_devices(models_list)
        ]
        return json.dumps(devices_json, indent=indent)
