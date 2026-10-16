"""Client."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
import json
import logging
import random
from typing import TYPE_CHECKING, override

from ghome_foyer_api.api_pb2 import GetHomeGraphRequest, GetHomeGraphResponse  # pylint: disable=no-name-in-module
from ghome_foyer_api.api_pb2_grpc import StructuresServiceStub
import gpsoauth
from gpsoauth import exchange_token, perform_master_login, perform_oauth
import grpc
import requests

from .const import (
    ACCESS_TOKEN_APP_NAME,
    ACCESS_TOKEN_CLIENT_SIGNATURE,
    ACCESS_TOKEN_DURATION,
    ACCESS_TOKEN_SERVICE,
    ANDROID_ID_LENGTH,
    DEFAULT_DISCOVERY_PORT,
    DISCOVERY_TIMEOUT,
    EMAIL_ACCESS_TOKEN_SERVICE,
    GOOGLE_HOME_FOYER_API,
    HOMEGRAPH_DURATION,
    REQUEST_TIMEOUT,
    USERINFO_URL,
)
from .scanner import NetworkDevice, discover_devices
from .utils import network as net_utils, token as token_utils
from .utils.logs import censor
from .utils.network import is_valid_ipv4_address

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from requests import PreparedRequest, Response
    from zeroconf import Zeroconf

    from .types import DeviceDict

LOGGER = logging.getLogger(__name__)


# Timeout for gpsoauth requests made by glocaltokens; see _TimeoutAuthHTTPAdapter.
_gpsoauth_timeout: ContextVar[float | None] = ContextVar(
    "_gpsoauth_timeout", default=None
)


class _TimeoutAuthHTTPAdapter(gpsoauth.AuthHTTPAdapter):
    """gpsoauth's HTTP adapter with a timeout for glocaltokens' own requests.

    gpsoauth sends its requests without a timeout and has no option to set one,
    so a stalled connection would make it wait forever. The timeout only applies
    inside _request_timeout(), so other gpsoauth users are not affected.
    """

    @override
    def send(
        self,
        request: PreparedRequest,
        stream: bool = False,
        timeout: float | tuple[float, float] | tuple[float, None] | None = None,
        verify: bool | str = True,
        cert: bytes | str | tuple[bytes | str, bytes | str] | None = None,
        proxies: Mapping[str, str] | None = None,
    ) -> Response:
        if timeout is None:
            timeout = _gpsoauth_timeout.get()
        return super().send(
            request,
            stream=stream,
            timeout=timeout,
            verify=verify,
            cert=cert,
            proxies=proxies,
        )


# gpsoauth looks the adapter up by this name for every request.
gpsoauth.AuthHTTPAdapter = _TimeoutAuthHTTPAdapter  # type: ignore[misc]


@contextmanager
def _request_timeout() -> Iterator[None]:
    """Apply REQUEST_TIMEOUT to gpsoauth requests made in this context."""
    token = _gpsoauth_timeout.set(REQUEST_TIMEOUT)
    try:
        yield
    finally:
        _gpsoauth_timeout.reset(token)


class Device:
    """Device representation."""

    def __init__(
        self,
        device_id: str,
        device_name: str,
        local_auth_token: str,
        network_device: NetworkDevice | None = None,
        hardware: str | None = None,
    ):
        """Initialize a Device."""
        log_prefix = f"[Device - {device_name}(id={device_id})]"
        LOGGER.debug("%s Initializing new Device instance", log_prefix)
        self.device_id = device_id
        self.device_name = device_name
        self.local_auth_token = None
        self.network_device = network_device
        self.hardware = hardware
        self.ip_address: str | None = None
        self.port: int | None = None

        # Token and name validations
        if not self.device_name:
            LOGGER.error("%s device_name must be provided", log_prefix)
            return
        if not token_utils.is_local_auth_token(local_auth_token):
            LOGGER.warning(
                "%s local_auth_token does not follow Google Home token format. "
                "Ignore for non-Google Home devices",
                log_prefix,
            )
            return

        # Setting IP and PORT
        if network_device:
            LOGGER.debug(
                "%s network_device is provided, using its IP and PORT", log_prefix
            )
            self.ip_address = network_device.ip_address
            self.port = network_device.port

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

    @override
    def __str__(self) -> str:
        """Return string representation of the device."""
        return str(self.as_dict())

    def as_dict(self) -> DeviceDict:
        """Return the dictionary representation of the device."""
        return {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "network_device": {
                "ip": self.ip_address,
                "port": self.port,
            },
            "hardware": self.hardware,
            "local_auth_token": self.local_auth_token,
        }


class GLocalAuthenticationTokens:
    """Client."""

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        master_token: str | None = None,
        android_id: str | None = None,
        verbose: bool = False,
        oauth_token: str | None = None,
    ):
        """Initialize a GLocalAuthenticationTokens instance with Google account credentials.

        :params
            username: Google account username, only required with password;
            password: Google account password (can be an app password);
            master_token: Google master token, instead of password;
            android_id: The ID of an Android device. Will be randomly generated if not set;
            verbose: Whether or not to print debug logging information;
            oauth_token: `oauth_token` cookie from a browser sign-in, exchanged for
              a master token instead of logging in with the password.
        """
        self.logging_level: int | None = logging.DEBUG if verbose else None
        if verbose:
            LOGGER.setLevel(logging.DEBUG)
            # Show the debug output in scripts; does nothing if the
            # application has already configured logging.
            logging.basicConfig()

        LOGGER.debug("Initializing new GLocalAuthenticationTokens instance.")

        self.username: str | None = username
        self.password: str | None = password
        self.master_token: str | None = master_token
        self.oauth_token: str | None = oauth_token
        self.android_id: str | None = android_id
        # Email address Google returns when this client gets a master token
        self.email: str | None = None
        self.access_token: str | None = None
        self.access_token_date: datetime | None = None
        self.homegraph: GetHomeGraphResponse | None = None
        self.homegraph_date: datetime | None = None
        LOGGER.debug(
            "Set GLocalAuthenticationTokens client access_token, homegraph, "
            "access_token_date and homegraph_date to None"
        )

        LOGGER.debug(
            "Set GLocalAuthenticationTokens client "
            'username to "%s", password to "%s", '
            'master_token to "%s", oauth_token to "%s" and android_id to %s',
            censor(username, hide_length=True),
            censor(password, hide_length=True, hide_first_letter=True),
            censor(master_token),
            censor(oauth_token, hide_length=True),
            censor(android_id),
        )

        # Validation
        can_log_in = self.oauth_token or (self.username and self.password)
        if not can_log_in and not self.master_token:
            LOGGER.error(
                "You must either provide google username with password, "
                "oauth_token, or google master token"
            )
            return
        if self.master_token and not token_utils.is_aas_et(self.master_token):
            LOGGER.error("master_token doesn't follow the AAS_ET format")
            return

    @staticmethod
    def _generate_android_id() -> str:
        """Generate random 16 char long string."""
        LOGGER.debug("Generating android id...")
        mac_string = "".join(
            [f"{random.randrange(16):x}" for _ in range(ANDROID_ID_LENGTH)]
        )
        LOGGER.debug("Generated android id: %s", mac_string)
        return mac_string

    def get_android_id(self) -> str:
        """Return existing or generate android id."""
        if not self.android_id:
            LOGGER.debug("There is no stored android_id, generating a new one")
            self.android_id = self._generate_android_id()
        return self.android_id

    @staticmethod
    def _has_expired(creation_dt: datetime, duration: int) -> bool:
        """Check if an specified token/object has expired."""
        return datetime.now(UTC).timestamp() - creation_dt.timestamp() > duration

    @staticmethod
    def _escape_username(username: str) -> str:
        """Escape plus sign for some exotic accounts."""
        return username.replace("+", "%2B")

    def get_master_token(self) -> str | None:
        """Return the stored master token, or get a new one.

        A new master token comes from exchanging the oauth_token if one is set,
        otherwise from logging in with the password.
        """
        if not self.master_token:
            res = {}
            if self.oauth_token:
                LOGGER.debug(
                    "There is no stored master_token, exchanging the oauth_token"
                )
                # Google doesn't need the email address to exchange the cookie
                with _request_timeout():
                    res = exchange_token(
                        self._escape_username(self.username or ""),
                        self.oauth_token,
                        self.get_android_id(),
                    )
            elif self.username is not None and self.password is not None:
                LOGGER.debug(
                    "There is no stored master_token, "
                    "logging in using username and password"
                )
                try:
                    with _request_timeout():
                        res = perform_master_login(
                            self._escape_username(self.username),
                            self.password,
                            self.get_android_id(),
                        )
                except ValueError:
                    LOGGER.exception(
                        "A ValueError exception has been thrown, this usually is "
                        "related to a password length that exceeds the boundaries "
                        "(too long)."
                    )
            else:
                LOGGER.error("Username and password or oauth_token are not set.")
                return None
            if "Token" not in res:
                LOGGER.error("[!] Could not get master token.")
                LOGGER.debug("Request response: %s", res)
                return None
            self.master_token = res["Token"]
            self.email = res.get("Email") or None
        LOGGER.debug("Master token: %s", censor(self.master_token))
        return self.master_token

    def get_access_token(self) -> str | None:
        """Return existing or fetch access_token."""
        if (
            self.access_token is None
            or self.access_token_date is None
            or self._has_expired(self.access_token_date, ACCESS_TOKEN_DURATION)
        ):
            LOGGER.debug(
                "There is no access_token stored, "
                "or it has expired, getting a new one..."
            )
            master_token = self.get_master_token()
            if master_token is None:
                LOGGER.debug("Unable to obtain master token.")
                return None
            # Google doesn't need the email address once there is a master token
            with _request_timeout():
                res = perform_oauth(
                    self._escape_username(self.username or ""),
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
            self.access_token_date = datetime.now(UTC)
        LOGGER.debug(
            "Access token: %s, datetime %s",
            censor(self.access_token),
            self.access_token_date,
        )
        return self.access_token

    def get_email(self) -> str | None:
        """Return the email address of the account, if Google gives it.

        If this client got the master token itself, this is the address Google
        returned with it. Otherwise, as a master token doesn't say which account
        it belongs to, this gets an access token that may only read the email
        address and asks Google's userinfo endpoint, which returns only an
        address Google has verified.
        """
        master_token = self.get_master_token()
        if self.email is not None:
            return self.email
        if master_token is None:
            LOGGER.debug("Unable to obtain master token.")
            return None
        with _request_timeout():
            res = perform_oauth(
                self._escape_username(self.username or ""),
                master_token,
                self.get_android_id(),
                app=ACCESS_TOKEN_APP_NAME,
                service=EMAIL_ACCESS_TOKEN_SERVICE,
                client_sig=ACCESS_TOKEN_CLIENT_SIGNATURE,
            )
        if "Auth" not in res:
            LOGGER.debug("Could not get an access token for the email address")
            LOGGER.debug("Request response: %s", res)
            return None
        # Send the token in a header: a URL ends up in debug logs and errors
        response = requests.get(
            USERINFO_URL,
            headers={"Authorization": f"Bearer {res['Auth']}"},
            timeout=REQUEST_TIMEOUT,
        )
        if not response.ok:
            LOGGER.debug(
                "Could not get the email address: HTTP %s", response.status_code
            )
            return None
        user_info = response.json()
        if str(user_info.get("email_verified")).lower() != "true":
            LOGGER.debug("Google gave no verified email address")
            return None
        email: str | None = user_info.get("email") or None
        return email

    def get_homegraph(self, auth_attempts: int = 3) -> GetHomeGraphResponse | None:
        """Return the entire Google Home Foyer V2 service."""
        if (
            self.homegraph is None
            or self.homegraph_date is None
            or self._has_expired(self.homegraph_date, HOMEGRAPH_DURATION)
        ):
            if auth_attempts == 0:
                LOGGER.error("Reached maximum number of authentication attempts")
                return None
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
                    "%s Establishing secure channel with the Google Home Foyer API...",
                    log_prefix,
                )
                with grpc.secure_channel(
                    GOOGLE_HOME_FOYER_API, channel_credentials
                ) as channel:
                    LOGGER.debug(
                        "%s Getting channels StructuresServiceStub...", log_prefix
                    )
                    rpc_service = StructuresServiceStub(channel)
                    LOGGER.debug("%s Getting HomeGraph request...", log_prefix)
                    request = GetHomeGraphRequest(string1="", num2="")
                    LOGGER.debug("%s Fetching HomeGraph...", log_prefix)
                    response = rpc_service.GetHomeGraph(
                        request, timeout=REQUEST_TIMEOUT
                    )
                    LOGGER.debug("%s Storing obtained HomeGraph...", log_prefix)
                    self.homegraph = response
                self.homegraph_date = datetime.now(UTC)
            except grpc.RpcError as rpc_error:
                LOGGER.debug("%s Got an RpcError", log_prefix)
                if (
                    rpc_error.code().name  # pylint: disable=no-member
                    == "UNAUTHENTICATED"
                ):
                    LOGGER.warning(
                        "%s The access token has expired. Getting a new one.",
                        log_prefix,
                    )
                    self.invalidate_access_token()
                    return self.get_homegraph(auth_attempts - 1)
                LOGGER.exception(
                    "%s Received unknown RPC error: code=%s message=%s",
                    log_prefix,
                    rpc_error.code(),  # pylint: disable=no-member
                    rpc_error.details(),  # pylint: disable=no-member
                )
                return None
        return self.homegraph

    def get_google_devices(
        self,
        models_list: list[str] | None = None,
        disable_discovery: bool = False,
        addresses: dict[str, str] | None = None,
        zeroconf_instance: Zeroconf | None = None,
        force_homegraph_reload: bool = False,
        discovery_timeout: int = DISCOVERY_TIMEOUT,
    ) -> list[Device]:
        """Return a list of Google devices with their local authentication tokens, IP, and ports.

        models_list: The list of accepted model names.
        disable_discovery: Whether or not the device's IP and port should
          be searched for in the network.
        addresses: Dict of network devices from the local network
          ({"name": "ip_address"}). Only used when discovery is disabled
          or finds no devices.
        zeroconf_instance: If you already have an initialized zeroconf instance,
          use it here.
        force_homegraph_reload: If the stored homegraph should be generated again.
        discovery_timeout: Timeout for zeroconf discovery in seconds.
        """

        # Set models_list to empty list if None
        LOGGER.debug("Initializing models list if empty...")
        models_list = models_list or []

        if force_homegraph_reload:
            LOGGER.debug("Forcing homegraph reload")
            self.invalidate_homegraph()

        LOGGER.debug("Getting homegraph...")
        homegraph = self.get_homegraph()

        devices: list[Device] = []

        def is_dict_with_valid_ipv4_addresses(data: dict[str, str]) -> bool:
            # Validate the data structure is correct and that each entry contains a
            # valid IPv4 address.
            return isinstance(data, dict) and all(
                isinstance(x, str) and is_valid_ipv4_address(x) for x in data.values()
            )

        if addresses and not is_dict_with_valid_ipv4_addresses(addresses):
            LOGGER.error(
                "Invalid dictionary structure for addresses dictionary "
                "argument. Correct structure is {'device_name': 'ipaddress'}"
            )
            return devices

        if homegraph is None:
            LOGGER.debug("Failed to fetch homegraph")
            return devices

        network_devices: list[NetworkDevice] = []
        if disable_discovery is False:
            LOGGER.debug("Automatically discovering network devices...")
            network_devices = discover_devices(
                models_list,
                timeout=discovery_timeout,
                zeroconf_instance=zeroconf_instance,
                logging_level=self.logging_level,
            )

        def find_device(unique_id: str) -> NetworkDevice | None:
            for device in network_devices:
                if device.unique_id == unique_id:
                    return device
            return None

        address_dict = addresses or {}

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

                network_device = None
                if network_devices:
                    unique_id = item.device_info.agent_info.unique_id
                    LOGGER.debug(
                        "Looking for '%s' (id=%s) in local network",
                        item.device_name,
                        unique_id,
                    )
                    network_device = find_device(unique_id)
                elif item.device_name in address_dict:
                    network_device = NetworkDevice(
                        name=item.device_name,
                        ip_address=address_dict[item.device_name],
                        port=DEFAULT_DISCOVERY_PORT,
                        model=item.hardware.model,
                        unique_id=item.device_info.device_id,
                    )

                device = Device(
                    device_id=item.device_info.device_id,
                    device_name=network_device.name
                    if network_device is not None
                    else item.device_name,
                    local_auth_token=item.local_auth_token,
                    network_device=network_device,
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
                    "'%s' local_auth_token is not found in Homegraph, skipping",
                    item.device_name,
                )

        LOGGER.debug("Successfully initialized %d Google Home devices", len(devices))
        return devices

    def get_google_devices_json(
        self,
        models_list: list[str] | None = None,
        indent: int = 2,
        disable_discovery: bool = False,
        addresses: dict[str, str] | None = None,
        zeroconf_instance: Zeroconf | None = None,
        force_homegraph_reload: bool = False,
        discovery_timeout: int = DISCOVERY_TIMEOUT,
    ) -> str:
        """Return a JSON list of devices with authentication tokens, IPs, and ports if models set.

        models_list: The list of accepted model names.
        indent: The indentation for the JSON formatting.
        disable_discovery: Whether or not the device's IP and port should
          be searched for in the network.
        addresses: Dict of network devices from the local network
          ({"name": "ip_address"}). Only used when discovery is disabled
          or finds no devices.
        zeroconf_instance: If you already have an initialized zeroconf instance,
          use it here.
        force_homegraph_reload: If the stored homegraph should be generated again.
        discovery_timeout: Timeout for zeroconf discovery in seconds.
        """

        google_devices = self.get_google_devices(
            models_list=models_list,
            disable_discovery=disable_discovery,
            addresses=addresses,
            zeroconf_instance=zeroconf_instance,
            force_homegraph_reload=force_homegraph_reload,
            discovery_timeout=discovery_timeout,
        )
        return json.dumps([obj.as_dict() for obj in google_devices], indent=indent)

    def invalidate_access_token(self) -> None:
        """Invalidate the current access token."""
        self.access_token = None
        self.access_token_date = None
        LOGGER.debug("Invalidated access_token")

    def invalidate_master_token(self) -> None:
        """Invalidate the current master token."""
        self.master_token = None
        self.email = None
        LOGGER.debug("Invalidated master_token")

    def invalidate_homegraph(self) -> None:
        """Invalidate the stored homegraph data."""
        self.homegraph = None
        self.homegraph_date = None
        LOGGER.debug("Invalidated homegraph")
