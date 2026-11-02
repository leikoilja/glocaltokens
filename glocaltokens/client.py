"""Client."""

# pylint: disable=too-many-lines

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from http import HTTPStatus
import json
import logging
import os
from pathlib import Path
import random
import ssl
from typing import TYPE_CHECKING, Final, override
from urllib.parse import urlencode
import warnings

import aiohttp
from ghome_foyer_api.api_pb2 import GetHomeGraphRequest, GetHomeGraphResponse, HomeGraph  # pylint: disable=no-name-in-module
from ghome_foyer_api.home_graph import GET_HOME_GRAPH, get_home_graph_bytes
from google.protobuf.message import DecodeError
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
from .types import NetworkDevice
from .utils import token as token_utils
from .utils.logs import censor
from .utils.network import is_valid_ipv4_address

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator, Mapping

    from requests import PreparedRequest, Response
    from zeroconf import Zeroconf

    from .types import DeviceDict

LOGGER = logging.getLogger(__name__)

_NO_CREDENTIALS: Final = (
    "No master token, and no username and password or oauth_token to get one with"
)
_PASSWORD_TOO_LONG: Final = (
    "Could not log in with the password to get a master "
    "token, the username and password may be too long together"
)


def _is_busy(status: int) -> bool:
    """Return whether an HTTP status means "try later" rather than an answer."""
    return (
        status >= HTTPStatus.INTERNAL_SERVER_ERROR
        or status == HTTPStatus.TOO_MANY_REQUESTS
    )


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
        if own_timeout is not None and _is_busy(response.status_code):
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


def _google_ssl_context() -> ssl.SSLContext:
    """Return the TLS settings of the async methods' requests to Google.

    They check Google's certificate even if the caller's session doesn't check
    certificates. Like gpsoauth's sign-in requests, they trust the system's
    certificate authorities and those of the bundle requests uses: certifi's,
    unless REQUESTS_CA_BUNDLE or CURL_CA_BUNDLE names another file or directory.
    Like gpsoauth, they offer no ALPN and allow TLS session tickets, as gpsoauth
    found that Google refuses its logins otherwise.
    """
    context = ssl.create_default_context()
    context.options &= ~ssl.OP_NO_TICKET  # pylint: disable=no-member
    bundle = (
        os.environ.get("REQUESTS_CA_BUNDLE")
        or os.environ.get("CURL_CA_BUNDLE")
        or requests.utils.DEFAULT_CA_BUNDLE_PATH
    )
    try:
        if Path(bundle).is_dir():
            context.load_verify_locations(capath=bundle)
        else:
            context.load_verify_locations(cafile=bundle)
    except OSError as error:
        msg = f"Could not load the TLS CA certificate bundle {bundle}: {error}"
        raise OSError(msg) from error
    return context


def _google_ssl() -> ssl.SSLContext:
    """Return the TLS settings of the requests to Google, or raise why there are none."""
    if isinstance(_GOOGLE_SSL_CONTEXT, OSError):
        raise OSError(*_GOOGLE_SSL_CONTEXT.args)
    return _GOOGLE_SSL_CONTEXT


# Created on import, as loading the certificates blocks. A bundle that can't be
# loaded fails the async requests rather than the import, as requests fails
# each of its own requests then.
try:
    _GOOGLE_SSL_CONTEXT: ssl.SSLContext | OSError = _google_ssl_context()
except OSError as bundle_error:
    _GOOGLE_SSL_CONTEXT = bundle_error

# The request gpsoauth 2.0.0 sends, which it can't send through another HTTP
# client. Keep the fields and their order in step with gpsoauth. The headers
# are those requests sends for gpsoauth, in the same order.
_AUTH_HEADERS: Final = {
    "User-Agent": gpsoauth.USER_AGENT,
    "Accept-Encoding": "identity",
    "Accept": "*/*",
    "Connection": "keep-alive",
    "Content-type": "application/x-www-form-urlencoded",
}
_GPSOAUTH_CLIENT_SIG: Final = "38918a453d07199354f8b19af05ec6562ced5788"


def _master_token_data(
    email: str, android_id: str, credentials: Mapping[str, str | bytes | int]
) -> dict[str, str | bytes | int]:
    """Return the fields of gpsoauth's perform_master_login() or exchange_token()."""
    return {
        "accountType": "HOSTED_OR_GOOGLE",
        "Email": email,
        "has_permission": 1,
        "add_account": 1,
        **credentials,
        "service": "ac2dm",
        "source": "android",
        "androidId": android_id,
        "device_country": "us",
        "operatorCountry": "us",
        "lang": "en",
        "sdk_version": 17,
        "google_play_services_version": 240913000,
        "client_sig": _GPSOAUTH_CLIENT_SIG,
        "callerSig": _GPSOAUTH_CLIENT_SIG,
        "droidguard_results": "dummy123",
    }


def _oauth_data(
    email: str, master_token: str, android_id: str, service: str
) -> dict[str, str | bytes | int]:
    """Return the fields of gpsoauth's perform_oauth() for glocaltokens' tokens."""
    return {
        "accountType": "HOSTED_OR_GOOGLE",
        "Email": email,
        "has_permission": 1,
        "EncryptedPasswd": master_token,
        "service": service,
        "source": "android",
        "androidId": android_id,
        "app": ACCESS_TOKEN_APP_NAME,
        "client_sig": ACCESS_TOKEN_CLIENT_SIGNATURE,
        "device_country": "us",
        "operatorCountry": "us",
        "lang": "en",
        "sdk_version": 17,
        "google_play_services_version": 240913000,
    }


def _token(res: Mapping[str, str], key: str, name: str) -> str:
    """Return the token Google gave, or raise AuthenticationError with its reason."""
    if not res.get(key):
        LOGGER.debug("Request response: %s", res)
        raise AuthenticationError(f"Google gave no {name}", res.get("Error"))
    return res[key]


def _verified_email(user_info: Mapping[str, str]) -> str | None:
    """Return the email address of a userinfo answer, if Google has verified it."""
    if str(user_info.get("email_verified")).lower() != "true":
        LOGGER.debug("Google gave no verified email address")
        return None
    return user_info.get("email") or None


def _channel_credentials(access_token: str) -> grpc.ChannelCredentials:
    """Return the credentials of a home graph request."""
    return grpc.composite_channel_credentials(
        grpc.ssl_channel_credentials(root_certificates=None),
        grpc.access_token_call_credentials(access_token),
    )


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
    """Client.

    Each get_* method that asks Google has an async_* counterpart with the same
    results and errors, except that the async methods raise aiohttp's errors
    where the others raise requests' errors. Two have none: get_homegraph(),
    whose single merged home is a legacy form of get_home_graph(), and
    get_google_devices_json(), which only formats get_google_devices(). The
    async methods take their options by name only, and the device methods name
    them more clearly.
    """

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        master_token: str | None = None,
        android_id: str | None = None,
        verbose: bool | None = None,
        oauth_token: str | None = None,
        *,
        session: aiohttp.ClientSession | None = None,
    ):
        """Initialize a GLocalAuthenticationTokens instance with Google account credentials.

        :params
            username: Google account username, only required with password;
            password: Google account password (can be an app password);
            master_token: Google master token, instead of password;
            android_id: The ID of an Android device. Will be randomly generated if not set;
            verbose: Deprecated and ignored, configure logging in your application instead;
            oauth_token: `oauth_token` cookie from a browser sign-in, exchanged for
              a master token instead of logging in with the password;
            session: The aiohttp session for the HTTP requests of the async_*
              methods, which is never closed here. Without one, each request
              uses a new session. The home graph is fetched with gRPC instead.

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
        self.session = session
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
                    raise AuthenticationError(_PASSWORD_TOO_LONG) from error
            else:
                raise AuthenticationError(_NO_CREDENTIALS)
            self.master_token = _token(res, "Token", "master token")
            self.email = res.get("Email") or None
        LOGGER.debug("Master token: %s", censor(self.master_token))
        return self.master_token

    async def async_get_master_token(self) -> str:
        """Return the stored master token, or get a new one, as get_master_token().

        Raises the errors of get_master_token(), except that Google answering
        with a 5xx or 429 raises aiohttp.ClientResponseError, and failing to
        reach Google raises aiohttp.ClientError or TimeoutError.
        """
        if not self.master_token:
            username = self._escape_username(self.username or "")
            credentials: dict[str, str | bytes | int]
            if self.oauth_token:
                LOGGER.debug(
                    "There is no stored master_token, exchanging the oauth_token"
                )
                # Google doesn't need the email address to exchange the cookie
                credentials = {"ACCESS_TOKEN": 1, "Token": self.oauth_token}
            elif self.username and self.password:
                LOGGER.debug(
                    "There is no stored master_token, "
                    "logging in using username and password"
                )
                try:
                    signature = gpsoauth.google.construct_signature(
                        username, self.password, gpsoauth.ANDROID_KEY_7_3_29
                    )
                except ValueError as error:
                    # gpsoauth encrypts the username and password together
                    raise AuthenticationError(_PASSWORD_TOO_LONG) from error
                credentials = {"EncryptedPasswd": signature}
            else:
                raise AuthenticationError(_NO_CREDENTIALS)
            res = await self._async_auth_request(
                _master_token_data(username, self.get_android_id(), credentials)
            )
            self.master_token = _token(res, "Token", "master token")
            self.email = res.get("Email") or None
        LOGGER.debug("Master token: %s", censor(self.master_token))
        return self.master_token

    def _stored_access_token(self) -> str | None:
        """Return the stored access token, unless there is none or it has expired."""
        if (
            self.access_token is None
            or self.access_token_date is None
            or self._has_expired(self.access_token_date, ACCESS_TOKEN_DURATION)
        ):
            LOGGER.debug(
                "There is no access_token stored, "
                "or it has expired, getting a new one..."
            )
            return None
        return self.access_token

    def _store_access_token(self, res: Mapping[str, str]) -> str:
        """Store the access token Google gave, or raise AuthenticationError."""
        self.access_token = _token(res, "Auth", "access token")
        self.access_token_date = datetime.now(UTC)
        return self.access_token

    def _log_access_token(self, access_token: str) -> str:
        """Log the access token, censored, and return it."""
        LOGGER.debug(
            "Access token: %s, datetime %s",
            censor(access_token),
            self.access_token_date,
        )
        return access_token

    def get_access_token(self) -> str:
        """Return existing or fetch access_token.

        Raises AuthenticationError if Google gives no access token, or no
        master token to get one with.
        """
        if (access_token := self._stored_access_token()) is not None:
            return self._log_access_token(access_token)
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
        return self._log_access_token(self._store_access_token(res))

    async def async_get_access_token(self) -> str:
        """Return existing or fetch access_token, as get_access_token().

        Raises the errors of get_access_token(), with aiohttp's errors as in
        async_get_master_token().
        """
        if (access_token := self._stored_access_token()) is not None:
            return self._log_access_token(access_token)
        master_token = await self.async_get_master_token()
        # Google doesn't need the email address once there is a master token
        res = await self._async_auth_request(
            _oauth_data(
                self._escape_username(self.username or ""),
                master_token,
                self.get_android_id(),
                ACCESS_TOKEN_SERVICE,
            )
        )
        return self._log_access_token(self._store_access_token(res))

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
        return _verified_email(response.json())

    async def async_get_email(self) -> str | None:
        """Return the email address of the account, if Google gives it, as get_email().

        Raises the errors of get_email(), with aiohttp's errors as in
        async_get_master_token(). If the userinfo answer isn't JSON, raises
        aiohttp.ContentTypeError for another content type, or
        json.JSONDecodeError, where get_email() raises requests' JSONDecodeError.
        """
        master_token = await self.async_get_master_token()
        if self.email is not None:
            return self.email
        res = await self._async_auth_request(
            _oauth_data(
                self._escape_username(self.username or ""),
                master_token,
                self.get_android_id(),
                EMAIL_ACCESS_TOKEN_SERVICE,
            )
        )
        if not res.get("Auth"):
            LOGGER.debug("Could not get an access token for the email address")
            LOGGER.debug("Request response: %s", res)
            return None
        async with (
            self._client_session() as session,
            session.get(
                USERINFO_URL,
                # Send the token in a header: a URL ends up in debug logs and errors
                headers={"Authorization": f"Bearer {res['Auth']}"},
                ssl=_google_ssl(),
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                raise_for_status=False,
            ) as response,
        ):
            if not response.ok:
                LOGGER.debug(
                    "Could not get the email address: HTTP %s", response.status
                )
                return None
            user_info = await response.json()
            if user_info is None:
                # aiohttp gives None for an empty body, where json.loads() raises
                user_info = json.loads(await response.text())
            return _verified_email(user_info)

    @asynccontextmanager
    async def _client_session(self) -> AsyncIterator[aiohttp.ClientSession]:
        """Yield the caller's session, or a new one that is closed afterwards."""
        if self.session is not None:
            yield self.session
            return
        # Like requests, follow the proxy environment variables
        async with aiohttp.ClientSession(trust_env=True) as session:
            yield session

    async def _async_auth_request(
        self, data: Mapping[str, str | bytes | int]
    ) -> dict[str, str]:
        """Send the request gpsoauth would send, and return Google's answer.

        The caller's middlewares still apply, but not its raise_for_status: an
        answer that means "try later" raises aiohttp.ClientResponseError, as
        gpsoauth would read it as a login response, and other answers are read.
        """
        async with (
            self._client_session() as session,
            session.post(
                gpsoauth.AUTH_URL,
                data=urlencode(data).encode(),
                headers=_AUTH_HEADERS,
                ssl=_google_ssl(),
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                raise_for_status=False,
            ) as response,
        ):
            text = await response.text(errors="replace")
            if _is_busy(response.status):
                LOGGER.debug("Request response: HTTP %s %s", response.status, text)
                response.raise_for_status()
        return gpsoauth.google.parse_auth_response(text)

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

    async def async_get_home_graph(self, *, auth_attempts: int = 3) -> HomeGraph:
        """Return the home graph with each home separately, as get_home_graph().

        The sync and async methods share the stored home graph.

        Raises the errors of get_home_graph(), with aiohttp's errors as in
        async_get_master_token().
        """
        return (await self._async_get_home_graphs(auth_attempts))[0]

    def _stored_home_graphs(self) -> tuple[HomeGraph, GetHomeGraphResponse] | None:
        """Return the stored home graph in both forms, unless it is missing or expired."""
        if (
            self.home_graph is None
            or self.homegraph is None
            or self.homegraph_date is None
            or self._has_expired(self.homegraph_date, HOMEGRAPH_DURATION)
        ):
            LOGGER.debug(
                "There is no stored homegraph, or it has expired, getting a new one..."
            )
            return None
        return self.home_graph, self.homegraph

    def _store_home_graphs(
        self, response: bytes
    ) -> tuple[HomeGraph, GetHomeGraphResponse]:
        """Parse the response as one merged home and home by home, and store it."""
        try:
            homegraph = GetHomeGraphResponse.FromString(response)
            home_graph = HomeGraph.FromString(response)
        except DecodeError as error:
            # gRPC used to report this as INTERNAL when it parsed the response
            raise HomegraphError(grpc.StatusCode.INTERNAL, str(error)) from error
        self.homegraph, self.home_graph = homegraph, home_graph
        self.homegraph_date = datetime.now(UTC)
        return home_graph, homegraph

    def _check_auth_retry(self, rpc_error: grpc.RpcError, auth_attempts: int) -> None:
        """Raise HomegraphError for a failed request, unless a new access token may help."""
        code = rpc_error.code()  # pylint: disable=no-member
        if code == grpc.StatusCode.UNAUTHENTICATED:
            self.invalidate_access_token()
            if auth_attempts > 1:
                LOGGER.warning(
                    "%s The access token has expired. Getting a new one.", "[GRPC]"
                )
                return
        raise HomegraphError(
            code,
            rpc_error.details(),  # pylint: disable=no-member
        ) from rpc_error

    def _get_home_graphs(
        self, auth_attempts: int
    ) -> tuple[HomeGraph, GetHomeGraphResponse]:
        """Return the stored home graph in both forms, or fetch it."""
        if (stored := self._stored_home_graphs()) is not None:
            return stored
        access_token = self.get_access_token()
        try:
            with grpc.secure_channel(
                GOOGLE_HOME_FOYER_API, _channel_credentials(access_token)
            ) as channel:
                request = GetHomeGraphRequest(string1="", num2="")
                LOGGER.debug("%s Fetching HomeGraph...", "[GRPC]")
                response = get_home_graph_bytes(
                    channel, request, timeout=REQUEST_TIMEOUT
                )
        except grpc.RpcError as rpc_error:
            self._check_auth_retry(rpc_error, auth_attempts)
            return self._get_home_graphs(auth_attempts - 1)
        return self._store_home_graphs(response)

    async def _async_get_home_graphs(
        self, auth_attempts: int
    ) -> tuple[HomeGraph, GetHomeGraphResponse]:
        """Return the stored home graph in both forms, or fetch it."""
        if (stored := self._stored_home_graphs()) is not None:
            return stored
        access_token = await self.async_get_access_token()
        try:
            # A channel for each fetch, closed when it ends or is cancelled
            async with grpc.aio.secure_channel(
                GOOGLE_HOME_FOYER_API, _channel_credentials(access_token)
            ) as channel:
                call: grpc.aio.UnaryUnaryMultiCallable[GetHomeGraphRequest, bytes] = (
                    channel.unary_unary(
                        GET_HOME_GRAPH,
                        request_serializer=GetHomeGraphRequest.SerializeToString,
                        response_deserializer=None,
                    )
                )
                LOGGER.debug("%s Fetching HomeGraph...", "[GRPC]")
                response = await call(
                    GetHomeGraphRequest(string1="", num2=""), timeout=REQUEST_TIMEOUT
                )
        except grpc.RpcError as rpc_error:
            self._check_auth_retry(rpc_error, auth_attempts)
            return await self._async_get_home_graphs(auth_attempts - 1)
        return self._store_home_graphs(response)

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
          use it here. It can't run on this thread's event loop: there, use
          the async methods, or run this call in an executor.
        force_homegraph_reload: If the stored homegraph should be generated again.
        discovery_timeout: Timeout for zeroconf discovery in seconds.
        home_id: Only return the devices of the home with this ID, the
          home_id of a Device or the id of a home in get_home_graph().

        Raises ValueError if addresses isn't a dict of IPv4 addresses,
        ModuleNotFoundError if discovery is on without the glocaltokens[discovery]
        extra (zeroconf), RuntimeError if zeroconf_instance runs on this
        thread's event loop, all before any request, the errors of
        get_home_graph(), and those of discover_devices() if the event loop of
        zeroconf_instance stalls or cancels discovery.
        """
        _check_addresses(addresses)
        if disable_discovery is False:
            # Raises before any request if zeroconf isn't installed, or if
            # discovery can't run on the loop of zeroconf_instance
            from .scanner import _check_sync_loop  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

            _check_sync_loop(zeroconf_instance)

        # Set models_list to empty list if None
        LOGGER.debug("Initializing models list if empty...")
        models_list = models_list or []

        if force_homegraph_reload:
            LOGGER.debug("Forcing homegraph reload")
            self.invalidate_homegraph()

        LOGGER.debug("Getting homegraph...")
        home_graph = self.get_home_graph()

        network_devices: list[NetworkDevice] = []
        if disable_discovery is False:
            from .scanner import discover_devices  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

            LOGGER.debug("Automatically discovering network devices...")
            network_devices = discover_devices(
                models_list,
                timeout=discovery_timeout,
                zeroconf_instance=zeroconf_instance,
            )
        return _devices_from_home_graph(
            home_graph, models_list, home_id, network_devices, addresses or {}
        )

    async def async_get_google_devices_and_home_graph(
        self,
        *,
        models: list[str] | None = None,
        home_id: str | None = None,
        discover: bool = True,
        zeroconf_instance: Zeroconf | None = None,
        discovery_timeout: float = DISCOVERY_TIMEOUT,
        addresses: dict[str, str] | None = None,
        reload_home_graph: bool = False,
    ) -> tuple[list[Device], HomeGraph]:
        """Return the devices of get_google_devices(), and the home graph they come from.

        The options are those of get_google_devices(), by name only and named
        more clearly:
        models: Only return these models (models_list). None returns every model.
        home_id: Only return the devices of the home with this ID, the home_id
          of a Device or the id of a home in the home graph.
        discover: Whether to search the local network for the devices' IP
          addresses and ports (the opposite of disable_discovery).
        zeroconf_instance: The Zeroconf to search with, which must run on the
          calling event loop, as Home Assistant's shared instance does, or
          ValueError is raised. Without one, glocaltokens creates its own and
          closes it afterwards.
        discovery_timeout: How long to search the local network, in seconds.
        addresses: {"device name": "IPv4 address"}, used when discovery is off
          or finds no devices.
        reload_home_graph: Fetch a new home graph even if the stored one is less
          than a day old (force_homegraph_reload).

        The home graph is the response that the devices were read from, with
        every device of every home, including those that the list leaves out,
        such as devices without a local authentication token. It stays that
        response even if another call fetches or drops the stored home graph
        meanwhile.

        Raises the errors of get_google_devices(), except the RuntimeError and
        EventLoopBlocked of its discovery, with aiohttp's errors as in
        async_get_master_token().
        """
        # Refuse the caller's mistakes before any request
        _check_addresses(addresses)
        if discover:
            # Raises before any request if zeroconf isn't installed
            from .scanner import _check_loop  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

            _check_loop(zeroconf_instance)
        models = models or []

        if reload_home_graph:
            LOGGER.debug("Forcing homegraph reload")
            self.invalidate_homegraph()

        LOGGER.debug("Getting homegraph...")
        home_graph = await self.async_get_home_graph()

        network_devices: list[NetworkDevice] = []
        if discover:
            from .scanner import async_discover_devices  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

            LOGGER.debug("Automatically discovering network devices...")
            network_devices = await async_discover_devices(
                models=models,
                timeout=discovery_timeout,
                zeroconf_instance=zeroconf_instance,
            )
        devices = _devices_from_home_graph(
            home_graph, models, home_id, network_devices, addresses or {}
        )
        return devices, home_graph

    async def async_get_google_devices(
        self,
        *,
        models: list[str] | None = None,
        home_id: str | None = None,
        discover: bool = True,
        zeroconf_instance: Zeroconf | None = None,
        discovery_timeout: float = DISCOVERY_TIMEOUT,
        addresses: dict[str, str] | None = None,
        reload_home_graph: bool = False,
    ) -> list[Device]:
        """Return a list of Google devices, as get_google_devices().

        It takes the options of async_get_google_devices_and_home_graph(), and
        raises the same errors. Use that method to also get the home graph the
        devices come from.
        """
        devices, _ = await self.async_get_google_devices_and_home_graph(
            models=models,
            home_id=home_id,
            discover=discover,
            zeroconf_instance=zeroconf_instance,
            discovery_timeout=discovery_timeout,
            addresses=addresses,
            reload_home_graph=reload_home_graph,
        )
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


def _check_addresses(addresses: dict[str, str] | None) -> None:
    """Raise ValueError if addresses isn't a dict of IPv4 addresses."""
    # Validate the data structure is correct and that each entry contains a
    # valid IPv4 address.
    if addresses and not (
        isinstance(addresses, dict)
        and all(
            isinstance(x, str) and is_valid_ipv4_address(x) for x in addresses.values()
        )
    ):
        raise ValueError(
            "Invalid dictionary structure for addresses dictionary "
            "argument. Correct structure is {'device_name': 'ipaddress'}"
        )


def _devices_from_home_graph(
    home_graph: HomeGraph,
    models_list: list[str],
    home_id: str | None,
    network_devices: list[NetworkDevice],
    address_dict: dict[str, str],
) -> list[Device]:
    """Return the Cast devices of a home graph that have local authentication tokens."""

    def find_device(unique_id: str) -> NetworkDevice | None:
        for device in network_devices:
            if device.unique_id == unique_id:
                return device
        return None

    devices: list[Device] = []
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
