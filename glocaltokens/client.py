"""Client."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from http import HTTPStatus
import json
import logging
import random
from typing import TYPE_CHECKING, override
import warnings

from ghome_foyer_api.api_pb2 import GetHomeGraphRequest, GetHomeGraphResponse, HomeGraph  # pylint: disable=no-name-in-module
from ghome_foyer_api.home_graph import get_home_graph_bytes
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
    LOCAL_AUTH_TOKEN_LENGTH,
    REQUEST_TIMEOUT,
    USERINFO_URL,
)
from .exceptions import AuthenticationError, HomegraphError
from .scanner import NetworkDevice, discover_devices
from .utils import token as token_utils
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
    so a stalled connection would make it wait forever. gpsoauth also reads any
    answer as a login response, so an answer that means "try later" would look
    like Google refusing the credentials: this adapter raises HTTPError for it.
    Both only apply inside _request_timeout(), so other gpsoauth users are not
    affected.
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
        own_timeout = _gpsoauth_timeout.get()
        if timeout is None:
            timeout = own_timeout
        response = super().send(
            request,
            stream=stream,
            timeout=timeout,
            verify=verify,
            cert=cert,
            proxies=proxies,
        )
        if own_timeout is not None and (
            response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR
            or response.status_code == HTTPStatus.TOO_MANY_REQUESTS
        ):
            # Read Google's answer, so the error keeps it, then close the
            # connection, as the error may be kept for long; gpsoauth mounts a
            # new adapter for each request.
            text = response.text
            LOGGER.debug("Request response: HTTP %s %s", response.status_code, text)
            self.close()
            response.raise_for_status()
        return response


# gpsoauth looks the adapter up by this name for every request.
gpsoauth.AuthHTTPAdapter = _TimeoutAuthHTTPAdapter  # type: ignore[misc]


@contextmanager
def _request_timeout() -> Iterator[None]:
    """Apply REQUEST_TIMEOUT and HTTPError to gpsoauth requests in this context."""
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
        cloud_device_id: str | None = None,
        home_id: str | None = None,
        home_name: str | None = None,
    ):
        """Initialize a Device."""
        self.device_id = device_id
        self.device_name = device_name
        self.local_auth_token = local_auth_token
        self.network_device = network_device
        self.hardware = hardware
        self.cloud_device_id = cloud_device_id
        self.home_id = home_id
        self.home_name = home_name
        self.ip_address = network_device.ip_address if network_device else None
        self.port = network_device.port if network_device else None

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
            "cloud_device_id": self.cloud_device_id,
            "home_id": self.home_id,
            "home_name": self.home_name,
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
        verbose: bool | None = None,
        oauth_token: str | None = None,
    ):
        """Initialize a GLocalAuthenticationTokens instance with Google account credentials.

        :params
            username: Google account username, only required with password;
            password: Google account password (can be an app password);
            master_token: Google master token, instead of password;
            android_id: The ID of an Android device. Will be randomly generated if not set;
            verbose: Deprecated and ignored, configure logging in your application instead;
            oauth_token: `oauth_token` cookie from a browser sign-in, exchanged for
              a master token instead of logging in with the password.

        Raises ValueError if there are no credentials, or if master_token
        doesn't start with "aas_et/".
        """
        if verbose is not None:
            warnings.warn(
                "verbose is deprecated and ignored, set the level of the "
                "glocaltokens logger in your application instead",
                DeprecationWarning,
                stacklevel=2,
            )

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
        # The same response as homegraph, with each home separately
        self.home_graph: HomeGraph | None = None
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
            raise ValueError(
                "You must either provide google username with password, "
                "oauth_token, or google master token"
            )
        # Only check the prefix: is_aas_et() also checks today's length, which
        # Google may change for the tokens get_master_token() gets
        if self.master_token and not self.master_token.startswith("aas_et/"):
            raise ValueError("master_token doesn't follow the AAS_ET format")

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

    def get_master_token(self) -> str:
        """Return the stored master token, or get a new one.

        A new master token comes from exchanging the oauth_token if one is set,
        otherwise from logging in with the password.

        Raises AuthenticationError if Google gives no master token, or if there
        is no oauth_token or username and password to get one with.
        """
        if not self.master_token:
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
            elif self.username and self.password:
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
                except ValueError as error:
                    # Some requests errors, such as InvalidProxyURL, are ValueErrors
                    if isinstance(error, requests.RequestException):
                        raise
                    # gpsoauth encrypts the username and password together
                    raise AuthenticationError(
                        "Could not log in with the password to get a master "
                        "token, the username and password may be too long together"
                    ) from error
            else:
                raise AuthenticationError(
                    "No master token, and no username and password or "
                    "oauth_token to get one with"
                )
            if not res.get("Token"):
                LOGGER.debug("Request response: %s", res)
                raise AuthenticationError(
                    "Google gave no master token", res.get("Error")
                )
            self.master_token = res["Token"]
            self.email = res.get("Email") or None
        LOGGER.debug("Master token: %s", censor(self.master_token))
        return self.master_token

    def get_access_token(self) -> str:
        """Return existing or fetch access_token.

        Raises AuthenticationError if Google gives no access token, or no
        master token to get one with.
        """
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
            if not res.get("Auth"):
                LOGGER.debug("Request response: %s", res)
                raise AuthenticationError(
                    "Google gave no access token", res.get("Error")
                )
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

        Raises AuthenticationError if Google gives no master token.
        """
        master_token = self.get_master_token()
        if self.email is not None:
            return self.email
        with _request_timeout():
            res = perform_oauth(
                self._escape_username(self.username or ""),
                master_token,
                self.get_android_id(),
                app=ACCESS_TOKEN_APP_NAME,
                service=EMAIL_ACCESS_TOKEN_SERVICE,
                client_sig=ACCESS_TOKEN_CLIENT_SIGNATURE,
            )
        if not res.get("Auth"):
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

    def get_homegraph(self, auth_attempts: int = 3) -> GetHomeGraphResponse:
        """Return the entire Google Home Foyer V2 service.

        It merges all homes of the account into one home, which has the rooms
        and devices of every home but the ID and name of only one of them. Use
        get_home_graph() to read each home separately.

        auth_attempts: How many times to try, with a new access token each
          time Google rejects the access token.

        Raises HomegraphError if Google doesn't return the home graph, and
        AuthenticationError if Google gives no access token.
        """
        return self._get_home_graphs(auth_attempts)[1]

    def get_home_graph(self, auth_attempts: int = 3) -> HomeGraph:
        """Return the home graph with each home of the account separately.

        It comes from the same request as get_homegraph(), so calling both
        fetches it once.

        auth_attempts: How many times to try, with a new access token each
          time Google rejects the access token.

        Raises HomegraphError if Google doesn't return the home graph, and
        AuthenticationError if Google gives no access token.
        """
        return self._get_home_graphs(auth_attempts)[0]

    def _get_home_graphs(
        self, auth_attempts: int
    ) -> tuple[HomeGraph, GetHomeGraphResponse]:
        """Return the stored home graph in both forms, or fetch it."""
        if (
            self.home_graph is None
            or self.homegraph is None
            or self.homegraph_date is None
            or self._has_expired(self.homegraph_date, HOMEGRAPH_DURATION)
        ):
            LOGGER.debug(
                "There is no stored homegraph, or it has expired, getting a new one..."
            )
            log_prefix = "[GRPC]"
            access_token = self.get_access_token()
            try:
                scc = grpc.ssl_channel_credentials(root_certificates=None)
                tok = grpc.access_token_call_credentials(access_token)
                channel_credentials = grpc.composite_channel_credentials(scc, tok)
                with grpc.secure_channel(
                    GOOGLE_HOME_FOYER_API, channel_credentials
                ) as channel:
                    request = GetHomeGraphRequest(string1="", num2="")
                    LOGGER.debug("%s Fetching HomeGraph...", log_prefix)
                    response = get_home_graph_bytes(
                        channel, request, timeout=REQUEST_TIMEOUT
                    )
                    # Parse it both ways: as one merged home, and home by home
                    self.homegraph = GetHomeGraphResponse.FromString(response)
                    self.home_graph = HomeGraph.FromString(response)
                self.homegraph_date = datetime.now(UTC)
            except grpc.RpcError as rpc_error:
                code = rpc_error.code()  # pylint: disable=no-member
                if code == grpc.StatusCode.UNAUTHENTICATED:
                    self.invalidate_access_token()
                    if auth_attempts > 1:
                        LOGGER.warning(
                            "%s The access token has expired. Getting a new one.",
                            log_prefix,
                        )
                        return self._get_home_graphs(auth_attempts - 1)
                raise HomegraphError(
                    code,
                    rpc_error.details(),  # pylint: disable=no-member
                ) from rpc_error
        return self.home_graph, self.homegraph

    def get_google_devices(
        self,
        models_list: list[str] | None = None,
        disable_discovery: bool = False,
        addresses: dict[str, str] | None = None,
        zeroconf_instance: Zeroconf | None = None,
        force_homegraph_reload: bool = False,
        discovery_timeout: int = DISCOVERY_TIMEOUT,
        home_id: str | None = None,
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
        home_id: Only return the devices of the home with this ID, the
          home_id of a Device or the id of a home in get_home_graph().

        Raises ValueError if addresses isn't a dict of IPv4 addresses, and the
        errors of get_home_graph().
        """

        def is_dict_with_valid_ipv4_addresses(data: dict[str, str]) -> bool:
            # Validate the data structure is correct and that each entry contains a
            # valid IPv4 address.
            return isinstance(data, dict) and all(
                isinstance(x, str) and is_valid_ipv4_address(x) for x in data.values()
            )

        if addresses and not is_dict_with_valid_ipv4_addresses(addresses):
            raise ValueError(
                "Invalid dictionary structure for addresses dictionary "
                "argument. Correct structure is {'device_name': 'ipaddress'}"
            )

        # Set models_list to empty list if None
        LOGGER.debug("Initializing models list if empty...")
        models_list = models_list or []

        if force_homegraph_reload:
            LOGGER.debug("Forcing homegraph reload")
            self.invalidate_homegraph()

        LOGGER.debug("Getting homegraph...")
        home_graph = self.get_home_graph()

        devices: list[Device] = []
        network_devices: list[NetworkDevice] = []
        if disable_discovery is False:
            LOGGER.debug("Automatically discovering network devices...")
            network_devices = discover_devices(
                models_list,
                timeout=discovery_timeout,
                zeroconf_instance=zeroconf_instance,
            )

        def find_device(unique_id: str) -> NetworkDevice | None:
            for device in network_devices:
                if device.unique_id == unique_id:
                    return device
            return None

        address_dict = addresses or {}

        homes = [home for home in home_graph.homes if home_id in (None, home.id)]
        items = [(home, item) for home in homes for item in home.devices]
        LOGGER.debug("Iterating in %d homegraph devices", len(items))
        for home, item in items:
            if not item.local_auth_token:
                LOGGER.debug(
                    "'%s' local_auth_token is not found in Homegraph, skipping",
                    item.display_name,
                )
                continue
            # This checks if the current item is a valid model,
            # only if there are models in models_list.
            # If models_list is empty, the check should be omitted,
            # and accept all items.
            if models_list and item.hardware.model not in models_list:
                LOGGER.debug("%s not in models_list", item.hardware.model)
                continue

            network_device = None
            unique_id = item.id.agent_info.unique_id
            if network_devices:
                LOGGER.debug(
                    "Looking for '%s' (id=%s) in local network",
                    item.display_name,
                    unique_id,
                )
                network_device = find_device(unique_id)
            elif item.display_name in address_dict:
                network_device = NetworkDevice(
                    name=item.display_name,
                    ip_address=address_dict[item.display_name],
                    port=DEFAULT_DISCOVERY_PORT,
                    model=item.hardware.model,
                    unique_id=unique_id,
                )

            log_prefix = f"[Device - {item.display_name}(id={item.id.device_id})]"
            if not item.display_name:
                LOGGER.error("%s device_name must be provided", log_prefix)
                continue
            if not token_utils.is_local_auth_token(item.local_auth_token):
                # Only a device found on the network or given in addresses is
                # known to be a Cast device; others, such as Google Wifi and
                # Nest Wifi routers, get tokens of another format.
                log = LOGGER.warning if network_device else LOGGER.debug
                log(
                    "%s local_auth_token isn't %d characters as expected for a "
                    "Cast device, skipping it",
                    log_prefix,
                    LOCAL_AUTH_TOKEN_LENGTH,
                )
                continue

            device = Device(
                device_id=item.id.device_id,
                device_name=item.display_name,
                local_auth_token=item.local_auth_token,
                network_device=network_device,
                hardware=item.hardware.model,
                cloud_device_id=unique_id or None,
                home_id=home.id or None,
                home_name=home.display_name or None,
            )
            LOGGER.debug(
                "Adding %s to devices list (IP %s, port %s)",
                device.device_name,
                device.ip_address,
                device.port,
            )
            devices.append(device)

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
        home_id: str | None = None,
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
        home_id: Only return the devices of the home with this ID, the
          home_id of a Device or the id of a home in get_home_graph().

        Raises the errors of get_google_devices().
        """

        google_devices = self.get_google_devices(
            models_list=models_list,
            disable_discovery=disable_discovery,
            addresses=addresses,
            zeroconf_instance=zeroconf_instance,
            force_homegraph_reload=force_homegraph_reload,
            discovery_timeout=discovery_timeout,
            home_id=home_id,
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
        self.home_graph = None
        self.homegraph_date = None
        LOGGER.debug("Invalidated homegraph")
