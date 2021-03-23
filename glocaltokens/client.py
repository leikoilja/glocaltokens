import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

import grpc
from gpsoauth import perform_master_login, perform_oauth

from .const import (
    ACCESS_TOKEN_APP_NAME,
    ACCESS_TOKEN_CLIENT_SIGNATURE,
    ACCESS_TOKEN_DURATION,
    ACCESS_TOKEN_SERVICE,
    ANDROID_ID_LENGTH,
    GOOGLE_HOME_FOYER_API,
    HOMEGRAPH_DURATION,
    JSON_KEY_DEVICE_NAME,
    JSON_KEY_GOOGLE_DEVICE,
    JSON_KEY_HARDWARE,
    JSON_KEY_IP,
    JSON_KEY_LOCAL_AUTH_TOKEN,
    JSON_KEY_PORT,
)
from .google.internal.home.foyer import v1_pb2, v1_pb2_grpc
from .scanner import GoogleDevice, discover_devices
from .utils import network as net_utils
from .utils import token as token_utils
from .utils.logs import censor

DEBUG = False

logging_level = logging.DEBUG if DEBUG else logging.ERROR
logging.basicConfig(level=logging_level)
LOGGER = logging.getLogger(__name__)


class Device:
    def __init__(
        self,
        device_name: str,
        local_auth_token: str,
        google_device: Optional[GoogleDevice] = None,
        ip: Optional[str] = None,
        port: Optional[int] = None,
        hardware: Optional[str] = None,
    ):
        """
        Initializes a Device. Can set or google_device or ip and port
        """
        LOGGER.debug("Initializing new Device instance.")
        self.device_name = device_name
        self.local_auth_token = None
        self.google_device = google_device
        self.hardware = hardware
        LOGGER.debug(
            'Set self device_name to "{}", local_auth_token to None, google_device to {}, and hardware to {}'.format(
                device_name, google_device, hardware
            )
        )

        if google_device:
            LOGGER.debug(f"google_device is not None")
            LOGGER.debug(f"Setting self ip to {google_device.ip}")
            self.ip = google_device.ip
            LOGGER.debug(f"Setting self port to {google_device.port}")
            self.port = google_device.port
        else:
            LOGGER.debug(f"google_device is None")
            if (ip and not port) or (not ip and port):
                LOGGER.error(
                    "Both ip and port must be set, if one of them is specified."
                )
                return
            LOGGER.debug(f"Setting self ip to {ip}")
            self.ip = ip
            LOGGER.debug(f"Setting self port to {port}")
            self.port = port

        if not local_auth_token:
            LOGGER.error("local_auth_token not set")
            return

        if not self.device_name:
            LOGGER.error("device_name not set")
            return

        if not token_utils.is_local_auth_token(local_auth_token):
            LOGGER.error("local_auth_token doesn't follow the correct format.")
            return

        if (
            self.ip
            and not net_utils.is_valid_ipv4_address(self.ip)
            and not net_utils.is_valid_ipv6_address(self.ip)
        ):
            LOGGER.error("ip must be a valid IP address")
            return

        if self.port and not net_utils.is_valid_port(self.port):
            LOGGER.error("port must be a valid port")
            return

        LOGGER.debug(f"Setting self local_auth_token to {censor(local_auth_token)}")
        self.local_auth_token = local_auth_token

    def __str__(self) -> str:
        return str(self.dict())

    def dict(self) -> Dict[str, Any]:
        return {
            JSON_KEY_DEVICE_NAME: self.device_name,
            JSON_KEY_GOOGLE_DEVICE: {JSON_KEY_IP: self.ip, JSON_KEY_PORT: self.port},
            JSON_KEY_HARDWARE: self.hardware,
            JSON_KEY_LOCAL_AUTH_TOKEN: self.local_auth_token,
        }


class GLocalAuthenticationTokens:
    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        master_token: Optional[str] = None,
        android_id: Optional[str] = None,
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
        LOGGER.debug("Initializing new GLocalAuthenticationTokens instance.")
        self.username: Optional[str] = username
        self.password: Optional[str] = password
        self.master_token: Optional[str] = master_token
        self.android_id: Optional[str] = android_id
        LOGGER.debug(
            'Set self username to "{}", password to "{}", master_token to "{}" and android_id to {}'.format(
                censor(username),
                censor(password),
                censor(master_token),
                censor(android_id),
            )
        )
        if (not self.username or not self.password) and not self.master_token:
            LOGGER.error(
                "You must either provide google username/password "
                "or google master token"
            )
            return
        if self.master_token and not token_utils.is_aas_et(self.master_token):
            LOGGER.error("master_token doesn't follow the AAS_ET format")
            return
        self.access_token: Optional[str] = None
        self.homegraph = None
        self.access_token_date: Optional[datetime] = None
        self.homegraph_date: Optional[datetime] = None
        LOGGER.debug(
            "Set self access_token, homegraph, access_token_date and homegraph_date to None"
        )

    @staticmethod
    def _generate_mac_string():
        """Generate random 14 char long string"""
        LOGGER.debug(f"Generating mac...")
        random_uuid = uuid4()
        random_string = str(random_uuid).replace("-", "")[:ANDROID_ID_LENGTH]
        mac_string = random_string.upper()
        LOGGER.debug(f"Generated mac: {mac_string}")
        return mac_string

    def get_android_id(self) -> Optional[str]:
        if not self.android_id:
            LOGGER.debug("There is not any stored android_id, generating a new one")
            self.android_id = self._generate_mac_string()
        return self.android_id

    @staticmethod
    def _has_expired(creation_dt, duration) -> bool:
        """Checks if an specified token/object has expired"""
        return datetime.now().timestamp() - creation_dt.timestamp() > duration

    def get_master_token(self) -> Optional[str]:
        """
        Get google master token from username and password
        """
        if not self.master_token:
            LOGGER.debug("There is not any stored master_token, logging in...")
            res = perform_master_login(
                self.username, self.password, self.get_android_id()
            )
            if "Token" not in res:
                LOGGER.error("[!] Could not get master token.")
                LOGGER.debug(f"Request response: {res}")
                return
            self.master_token = res["Token"]
        LOGGER.debug("Master token: {}".format(self.master_token))
        return self.master_token

    def get_access_token(self) -> Optional[str]:
        if self.access_token is None or self._has_expired(
            self.access_token_date, ACCESS_TOKEN_DURATION
        ):
            LOGGER.debug(
                "There is not any stored access_token, or the stored one has expired, getting a new one..."
            )
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
                LOGGER.debug(f"Request response: {res}")
                return
            self.access_token = res["Auth"]
            self.access_token_date = datetime.now()
        LOGGER.debug(
            f"Access token: {self.access_token}, datetime {self.access_token_date}"
        )
        return self.access_token

    def get_homegraph(self):
        """
        Returns the entire Google Home Foyer V2 service
        """
        if self.homegraph is None or self._has_expired(
            self.homegraph_date, HOMEGRAPH_DURATION
        ):
            LOGGER.debug(
                "There is not any stored homegraph, or the stored one has expired, getting a new one..."
            )
            try:
                LOGGER.debug("Creating SSL channel credentials...")
                scc = grpc.ssl_channel_credentials(root_certificates=None)
                LOGGER.debug("Creating access token call credentials...")
                tok = grpc.access_token_call_credentials(self.get_access_token())
                LOGGER.debug("Compositing channel credentials...")
                ccc = grpc.composite_channel_credentials(scc, tok)

                LOGGER.debug(
                    "Establishing secure channel with the Google Home Foyer API..."
                )
                with grpc.secure_channel(GOOGLE_HOME_FOYER_API, ccc) as channel:
                    LOGGER.debug("Getting channels StructuresServiceStub...")
                    rpc_service = v1_pb2_grpc.StructuresServiceStub(channel)
                    LOGGER.debug("Getting HomeGraph request...")
                    request = v1_pb2.GetHomeGraphRequest(string1="", num2="")
                    LOGGER.debug("Fetching HomeGraph...")
                    response = rpc_service.GetHomeGraph(request)
                    LOGGER.debug("Storing gotten homegraph...")
                    self.homegraph = response
                self.homegraph_date = datetime.now()
            except grpc.RpcError as rpc_error:
                LOGGER.debug("Got an RpcError.")
                if rpc_error.code().name == "UNAUTHENTICATED":
                    LOGGER.warning("The access token has expired. Getting a new one.")
                    self.invalidate_access_token()
                    return self.get_homegraph()
                else:
                    LOGGER.error(
                        f"Received unknown RPC error: code={rpc_error.code()} message={rpc_error.details()}"
                    )
        return self.homegraph

    def get_google_devices(
        self,
        models_list: Optional[List[str]] = None,
        disable_discovery: bool = False,
        zeroconf_instance=None,
        force_homegraph_reload: bool = False,
    ) -> [Device]:
        """
        Returns a list of google devices with their local authentication tokens, and IP and ports if set in models_list.

        models_list: The list of accepted model names.
        disable_discovery: Whether or not the device's IP and port should be searched for in the network.
        zeroconf_instance: If you already have an initialized zeroconf instance, use it here.
        force_homegraph_reload: If the stored homegraph should be generated again.
        """

        # Set models_list to empty list if None
        LOGGER.debug("Initializing models list if empty...")
        models_list = models_list if models_list else []

        if force_homegraph_reload:
            LOGGER.debug("Forcing homegraph reload.")
            self.invalidate_homegraph()

        LOGGER.debug("Getting homegraph...")
        homegraph = self.get_homegraph()
        LOGGER.debug("Getting network devices...")
        network_devices = (
            discover_devices(models_list, zeroconf_instance=zeroconf_instance)
            if not disable_discovery
            else None
        )

        def find_device(name) -> Optional[GoogleDevice]:
            for device in network_devices:
                if device.name == name:
                    return device
            return None

        devices: [Device] = []
        LOGGER.debug(
            f"Iterating in homegraph devices (len={len(homegraph.home.devices)})"
        )
        for item in homegraph.home.devices:
            if item.local_auth_token != "":
                # This checks if the current item is a valid model, only if there are models in models_list.
                # If models_list is empty, the check should be omitted, and accept all items.
                if models_list and item.hardware.model not in models_list:
                    LOGGER.debug("{} not in models_list".format(item.hardware.model))
                    continue

                LOGGER.debug(
                    "Looking for a device in local network? {}".format(
                        network_devices is not None
                    )
                )
                google_device = (
                    find_device(item.device_name) if network_devices else None
                )
                device = Device(
                    device_name=item.device_name,
                    local_auth_token=item.local_auth_token,
                    google_device=google_device,
                    hardware=item.hardware.model,
                )
                if device.local_auth_token:
                    LOGGER.debug("Adding {device.device_name} to devices list")
                    devices.append(device)
                else:
                    LOGGER.warning("Device initialization failed, skipping.")
            else:
                LOGGER.debug("local_auth_token is not initialized")

        LOGGER.debug("Google Home devices: {}".format(devices))

        return devices

    def get_google_devices_json(
        self,
        models_list: Optional[List[str]] = None,
        indent: int = 2,
        disable_discovery: bool = False,
        zeroconf_instance=None,
        force_homegraph_reload: bool = False,
    ) -> str:
        """
        Returns a json list of google devices with their local authentication tokens, and IP and ports if set in
        models_list.

        models_list: The list of accepted model names.
        indent: The indentation for the json formatting.
        disable_discovery: Whether or not the device's IP and port should be searched for in the network.
        zeroconf_instance: If you already have an initialized zeroconf instance, use it here.
        force_homegraph_reload: If the stored homegraph should be generated again.
        """

        google_devices = self.get_google_devices(
            models_list=models_list,
            disable_discovery=disable_discovery,
            zeroconf_instance=zeroconf_instance,
            force_homegraph_reload=force_homegraph_reload,
        )
        json_string = json.dumps([obj.dict() for obj in google_devices], indent=indent)
        return json_string

    def invalidate_access_token(self):
        """Invalidates the current access token"""
        self.access_token = None
        self.access_token_date = None
        LOGGER.debug("Invalidated access_token")

    def invalidate_homegraph(self):
        """Invalidates the stored homegraph data"""
        self.homegraph = None
        self.homegraph_date = None
        LOGGER.debug("Invalidated homegraph")
