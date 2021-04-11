"""Client"""

from datetime import datetime
import json
import logging
from typing import Any, Dict, List, Optional
from uuid import uuid4

from gpsoauth import perform_master_login, perform_oauth
import grpc

from .const import (
    ACCESS_TOKEN_APP_NAME,
    ACCESS_TOKEN_CLIENT_SIGNATURE,
    ACCESS_TOKEN_DURATION,
    ACCESS_TOKEN_SERVICE,
    ANDROID_ID_LENGTH,
    DISCOVERY_TIMEOUT,
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
from .utils import network as net_utils, token as token_utils
from .utils.logs import censor

logging.basicConfig(level=logging.ERROR)
LOGGER = logging.getLogger(__name__)


class Device:
    """Device representation"""

    def __init__(
        self,
        device_name: str,
        local_auth_token: str,
        google_device: Optional[GoogleDevice] = None,
        ip_address: Optional[str] = None,
        port: Optional[int] = None,
        hardware: Optional[str] = None,
    ):
        """
        Initializes a Device. Can set or google_device or ip and port
        """
        log_prefix = f"[Device - {device_name}]"
        LOGGER.debug("%s Initializing new Device instance", log_prefix)
        self.device_name = device_name
        self.local_auth_token = None
        self.ip_address = ip_address
        self.port = port
        self.google_device = google_device
        self.hardware = hardware

        # Token and name validations
        if not self.device_name:
            LOGGER.error("%s device_name must be provided", log_prefix)
            return
        if not token_utils.is_local_auth_token(local_auth_token):
            LOGGER.error(
                "%s local_auth_token must follow the correct format", log_prefix
            )
            return

        # Setting IP and PORT
        if google_device:
            LOGGER.debug(
                "%s google_device is provided, using it's IP and PORT", log_prefix
            )
            self.ip_address = google_device.ip_address
            self.port = google_device.port
        else:
            LOGGER.debug(
                "%s google_device is not provided, "
                "using manually provided IP and PORT",
                log_prefix,
            )
            if (ip_address and not port) or (not ip_address and port):
                LOGGER.error(
                    "%s google_device is not provided, "
                    "both IP(%s) and PORT(%s) must be manually provided",
                    log_prefix,
                    ip_address,
                    port,
                )
                return
            self.ip_address = ip_address
            self.port = port

        # IP and PORT validation
        if (
            self.ip_address
            and not net_utils.is_valid_ipv4_address(self.ip_address)
            and not net_utils.is_valid_ipv6_address(self.ip_address)
        ):
            LOGGER.error("%s IP(%s) is invalid", log_prefix, self.ip_address)
            return

        if self.port and not net_utils.is_valid_port(self.port):
            LOGGER.error("%s PORT(%s) is invalid", log_prefix, self.port)
            return

        LOGGER.debug(
            '%s Set device_name to "%s", '
            'local_auth_token to "%s", '
            'IP to "%s", PORT to "%s" and hardware to "%s"',
            log_prefix,
            device_name,
            censor(local_auth_token),
            self.ip_address,
            self.port,
            hardware,
        )
        self.local_auth_token = local_auth_token

    def __str__(self) -> str:
        return str(self.dict())

    def dict(self) -> Dict[str, Any]:
        """Dictionary representation"""
        return {
            JSON_KEY_DEVICE_NAME: self.device_name,
            JSON_KEY_GOOGLE_DEVICE: {
                JSON_KEY_IP: self.ip_address,
                JSON_KEY_PORT: self.port,
            },
            JSON_KEY_HARDWARE: self.hardware,
            JSON_KEY_LOCAL_AUTH_TOKEN: self.local_auth_token,
        }


class GLocalAuthenticationTokens:
    """Client"""

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        master_token: Optional[str] = None,
        android_id: Optional[str] = None,
        verbose: bool = False,
    ):
        """
        Initialize an GLocalAuthenticationTokens instance with google account
        credentials
        :params
            username: google account username;
            password: google account password (can be an app password);
            master_token: google master token (instead of username/password
                combination);
            android_id: the id of an android device. Will be randomly generated
                if not set;
            verbose: wheather or not print debug logging information

        """
        self.logging_level = logging.DEBUG if verbose else logging.ERROR
        LOGGER.setLevel(self.logging_level)

        LOGGER.debug("Initializing new GLocalAuthenticationTokens instance.")

        self.username: Optional[str] = username
        self.password: Optional[str] = password
        self.master_token: Optional[str] = master_token
        self.android_id: Optional[str] = android_id
        self.access_token: Optional[str] = None
        self.access_token_date: Optional[datetime] = None
        self.homegraph = None
        self.homegraph_date: Optional[datetime] = None
        LOGGER.debug(
            "Set GLocalAuthenticationTokens client access_token, homegraph, "
            "access_token_date and homegraph_date to None"
        )

        LOGGER.debug(
            "Set GLocalAuthenticationTokens client "
            'username to "%s", password to "%s", '
            'master_token to "%s" and android_id to %s',
            censor(username),
            censor(password),
            censor(master_token),
            censor(android_id),
        )

        # Validation
        if (not self.username or not self.password) and not self.master_token:
            LOGGER.error(
                "You must either provide google username/password "
                "or google master token"
            )
            return
        if self.master_token and not token_utils.is_aas_et(self.master_token):
            LOGGER.error("master_token doesn't follow the AAS_ET format")
            return

    @staticmethod
    def _generate_mac_string() -> str:
        """Generate random 14 char long string"""
        LOGGER.debug("Generating mac string...")
        random_uuid = uuid4()
        random_string = str(random_uuid).replace("-", "")[:ANDROID_ID_LENGTH]
        mac_string = random_string.upper()
        LOGGER.debug("Generated mac string: %s", mac_string)
        return mac_string

    def get_android_id(self) -> str:
        """Return existing or generate android id"""
        if not self.android_id:
            LOGGER.debug("There is no stored android_id, generating a new one")
            self.android_id = self._generate_mac_string()
        return self.android_id

    @staticmethod
    def _has_expired(creation_dt, duration) -> bool:
        """Checks if an specified token/object has expired"""
        return datetime.now().timestamp() - creation_dt.timestamp() > duration

    def get_master_token(self) -> Optional[str]:
        """Get google master token from username and password"""
        if self.username is None or self.password is None:
            LOGGER.error("Username and password are not set.")
            return None

        if not self.master_token:
            LOGGER.debug(
                "There is no stored master_token, "
                "logging in using username and password"
            )
            res = perform_master_login(
                self.username, self.password, self.get_android_id()
            )
            if "Token" not in res:
                LOGGER.error("[!] Could not get master token.")
                LOGGER.debug("Request response: %s", res)
                return None
            self.master_token = res["Token"]
        LOGGER.debug("Master token: %s", censor(self.master_token))
        return self.master_token

    def get_access_token(self) -> Optional[str]:
        """Return existing or fetch access_token"""
        if self.access_token is None or self._has_expired(
            self.access_token_date, ACCESS_TOKEN_DURATION
        ):
            LOGGER.debug(
                "There is no access_token stored, "
                "or it has expired, getting a new one..."
            )
            master_token = self.get_master_token()
            if master_token is None:
                LOGGER.debug("Unable to obtain master token.")
                return None
            if self.username is None:
                LOGGER.error("Username is not set.")
                return None
            res = perform_oauth(
                self.username,
                master_token,
                self.get_android_id(),
                app=ACCESS_TOKEN_APP_NAME,
                service=ACCESS_TOKEN_SERVICE,
                client_sig=ACCESS_TOKEN_CLIENT_SIGNATURE,
            )
            if "Auth" not in res:
                LOGGER.error("[!] Could not get access token.")
                LOGGER.debug("Request response: %s", res)
                return None
            self.access_token = res["Auth"]
            self.access_token_date = datetime.now()
        LOGGER.debug(
            "Access token: %s, datetime %s",
            censor(self.access_token),
            self.access_token_date,
        )
        return self.access_token

    # pylint: disable=no-member
    def get_homegraph(self):
        """Returns the entire Google Home Foyer V2 service"""
        if self.homegraph is None or self._has_expired(
            self.homegraph_date, HOMEGRAPH_DURATION
        ):
            LOGGER.debug(
                "There is no stored homegraph, or it has expired, getting a new one..."
            )
            log_prefix = "[GRPC]"
            access_token = self.get_access_token()
            if not access_token:
                LOGGER.debug("%s Unable to obtain access token.", log_prefix)
                return None
            try:
                LOGGER.debug("%s Creating SSL channel credentials...", log_prefix)
                scc = grpc.ssl_channel_credentials(root_certificates=None)
                LOGGER.debug("%s Creating access token call credentials...", log_prefix)
                tok = grpc.access_token_call_credentials(access_token)
                LOGGER.debug("%s Compositing channel credentials...", log_prefix)
                channel_credentials = grpc.composite_channel_credentials(scc, tok)

                LOGGER.debug(
                    "%s Establishing secure channel with "
                    "the Google Home Foyer API...",
                    log_prefix,
                )
                with grpc.secure_channel(
                    GOOGLE_HOME_FOYER_API, channel_credentials
                ) as channel:
                    LOGGER.debug(
                        "%s Getting channels StructuresServiceStub...", log_prefix
                    )
                    rpc_service = v1_pb2_grpc.StructuresServiceStub(channel)
                    LOGGER.debug("%s Getting HomeGraph request...", log_prefix)
                    request = v1_pb2.GetHomeGraphRequest(string1="", num2="")
                    LOGGER.debug("%s Fetching HomeGraph...", log_prefix)
                    response = rpc_service.GetHomeGraph(request)
                    LOGGER.debug("%s Storing obtained HomeGraph...", log_prefix)
                    self.homegraph = response
                self.homegraph_date = datetime.now()
            except grpc.RpcError as rpc_error:
                LOGGER.debug("%s Got an RpcError", log_prefix)
                if rpc_error.code().name == "UNAUTHENTICATED":
                    LOGGER.warning(
                        "%s The access token has expired. Getting a new one.",
                        log_prefix,
                    )
                    self.invalidate_access_token()
                    return self.get_homegraph()
                LOGGER.error(
                    "%s Received unknown RPC error: code=%s message=%s",
                    log_prefix,
                    rpc_error.code(),
                    rpc_error.details(),
                )
        return self.homegraph

    def get_google_devices(
        self,
        models_list: Optional[List[str]] = None,
        disable_discovery: bool = False,
        zeroconf_instance=None,
        force_homegraph_reload: bool = False,
        discovery_timeout: int = DISCOVERY_TIMEOUT,
    ) -> List[Device]:
        """
        Returns a list of google devices with their local authentication tokens,
        and IP and ports if set in models_list.

        models_list: The list of accepted model names.
        disable_discovery: Whether or not the device's IP and port should
          be searched for in the network.
        zeroconf_instance: If you already have an initialized zeroconf instance,
          use it here.
        force_homegraph_reload: If the stored homegraph should be generated again.
        discovery_timeout: Timeout for zeroconf discovery in seconds.
        """

        # Set models_list to empty list if None
        LOGGER.debug("Initializing models list if empty...")
        models_list = models_list if models_list else []

        if force_homegraph_reload:
            LOGGER.debug("Forcing homegraph reload")
            self.invalidate_homegraph()

        LOGGER.debug("Getting homegraph...")
        homegraph = self.get_homegraph()

        network_devices = []
        if disable_discovery is False:
            LOGGER.debug("Getting network devices...")
            network_devices = discover_devices(
                models_list,
                timeout=discovery_timeout,
                zeroconf_instance=zeroconf_instance,
                logging_level=self.logging_level,
            )

        def find_device(name) -> Optional[GoogleDevice]:
            for device in network_devices:
                if device.name == name:
                    return device
            return None

        devices: List[Device] = []
        LOGGER.debug("Iterating in %d homegraph devices", len(homegraph.home.devices))
        for item in homegraph.home.devices:
            if item.local_auth_token != "":
                # This checks if the current item is a valid model,
                # only if there are models in models_list.
                # If models_list is empty, the check should be omitted,
                # and accept all items.
                if models_list and item.hardware.model not in models_list:
                    LOGGER.debug("%s not in models_list", item.hardware.model)
                    continue

                google_device = None
                if network_devices:
                    LOGGER.debug("Looking for '%s' in local network", item.device_name)
                    google_device = find_device(item.device_name)

                device = Device(
                    device_name=item.device_name,
                    local_auth_token=item.local_auth_token,
                    google_device=google_device,
                    hardware=item.hardware.model,
                )
                if device.local_auth_token:
                    LOGGER.debug("Adding %s to devices list", device.device_name)
                    devices.append(device)
                else:
                    LOGGER.warning(
                        "%s device initialization failed "
                        "because of missing local_auth_token, skipping.",
                        device.device_name,
                    )
            else:
                LOGGER.debug(
                    "'%s' local_auth_token is " "not found in Homegraph, skipping",
                    item.device_name,
                )

        LOGGER.debug("Sucessfully initialized %d Google Home devices", len(devices))
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
        Returns a json list of google devices with their local authentication tokens,
        and IP and ports if set in models_list.

        models_list: The list of accepted model names.
        indent: The indentation for the json formatting.
        disable_discovery: Whether or not the device's IP and port should
          be searched for in the network.
        zeroconf_instance: If you already have an initialized zeroconf instance,
          use it here.
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
