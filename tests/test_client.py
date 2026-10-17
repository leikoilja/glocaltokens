"""Client specific unittests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import logging
import subprocess
import sys
from typing import override
from unittest import TestCase, mock
from unittest.mock import NonCallableMock, patch

from faker import Faker
from faker.providers import internet
import gpsoauth
import grpc
import pytest
import requests

from glocaltokens.client import LOGGER, Device, GLocalAuthenticationTokens
from glocaltokens.const import (
    ACCESS_TOKEN_APP_NAME,
    ACCESS_TOKEN_CLIENT_SIGNATURE,
    ACCESS_TOKEN_DURATION,
    ACCESS_TOKEN_SERVICE,
    ANDROID_ID_LENGTH,
    HOMEGRAPH_DURATION,
    JSON_KEY_DEVICE_NAME,
    JSON_KEY_HARDWARE,
    JSON_KEY_IP,
    JSON_KEY_LOCAL_AUTH_TOKEN,
    JSON_KEY_NETWORK_DEVICE,
    JSON_KEY_PORT,
    REQUEST_TIMEOUT,
)
from glocaltokens.scanner import NetworkDevice
from tests.assertions import DeviceAssertions, TypeAssertions
from tests.factory.providers import HomegraphProvider, TokenProvider

faker = Faker()
faker.add_provider(TokenProvider)
faker.add_provider(HomegraphProvider)
faker.add_provider(internet)


class GLocalAuthenticationTokensClientTests(DeviceAssertions, TypeAssertions, TestCase):
    """GLocalAuthenticationTokens clien specific unittests."""

    @override
    def setUp(self) -> None:
        """Set up the test client before each test."""
        self.client = GLocalAuthenticationTokens(
            username=faker.word(), password=faker.word()
        )

    def test_initialization(self) -> None:
        """Valid initialization tests."""
        username = faker.word()
        password = faker.word()
        master_token = faker.master_token()
        android_id = faker.word()

        client = GLocalAuthenticationTokens(
            username=username,
            password=password,
            master_token=master_token,
            android_id=android_id,
        )
        assert username == client.username
        assert password == client.password
        assert master_token == client.master_token
        assert android_id == client.android_id

        assert client.access_token is None
        assert client.homegraph is None
        assert client.access_token_date is None
        assert client.homegraph_date is None

        assert client.master_token is not None
        self.assertIsAasEt(client.master_token)

    @patch("glocaltokens.client.LOGGER.error")
    def test_initialization__valid(self, m_log: NonCallableMock) -> None:
        """Valid initialization tests."""
        # With username and password
        GLocalAuthenticationTokens(username=faker.word(), password=faker.word())
        assert m_log.call_count == 0

        # With master_token
        GLocalAuthenticationTokens(master_token=faker.master_token())
        assert m_log.call_count == 0

    @patch("glocaltokens.client.logging.basicConfig")
    @patch("glocaltokens.client.LOGGER.setLevel")
    def test_initialization__valid_verbose_logger(
        self, m_set_level: NonCallableMock, m_basic_config: NonCallableMock
    ) -> None:
        """Valid initialization tests with verbose logging."""
        # Non verbose
        GLocalAuthenticationTokens(username=faker.word(), password=faker.word())
        m_set_level.assert_not_called()
        m_basic_config.assert_not_called()

        # Verbose
        GLocalAuthenticationTokens(
            username=faker.word(), password=faker.word(), verbose=True
        )
        m_set_level.assert_called_once_with(logging.DEBUG)
        m_basic_config.assert_called_once_with()

    def test_initialization__verbose_output(self) -> None:
        """Verbose logging reaches stderr in a script without logging configured."""
        script = (
            "from glocaltokens.client import GLocalAuthenticationTokens\n"
            "client = GLocalAuthenticationTokens(username='u', password='p', verbose={})\n"
            "client.get_android_id()\n"
        )
        for verbose, expected in ((True, True), (False, False)):
            result = subprocess.run(
                [sys.executable, "-c", script.format(verbose)],
                capture_output=True,
                text=True,
                check=True,
            )
            assert ("DEBUG:glocaltokens.client" in result.stderr) is expected

    def test_initialization__keeps_application_log_level(self) -> None:
        """A non-verbose client keeps the level the application set."""
        package_logger = logging.getLogger("glocaltokens")
        package_logger.setLevel(logging.DEBUG)
        try:
            GLocalAuthenticationTokens(username=faker.word(), password=faker.word())
            assert LOGGER.getEffectiveLevel() == logging.DEBUG
        finally:
            package_logger.setLevel(logging.NOTSET)

    @patch("glocaltokens.client.LOGGER.error")
    def test_initialization__invalid(self, m_log: NonCallableMock) -> None:
        """Invalid initialization tests."""
        # Without username
        GLocalAuthenticationTokens(password=faker.word())
        assert m_log.call_count == 1

        # Without password
        GLocalAuthenticationTokens(username=faker.word())
        assert m_log.call_count == 2

        # Without username and password
        GLocalAuthenticationTokens()
        assert m_log.call_count == 3

        # With invalid master_token
        GLocalAuthenticationTokens(master_token=faker.word())
        assert m_log.call_count == 4

    def test_get_android_id(self) -> None:
        """Test getting android id."""
        android_id = self.client.get_android_id()
        assert len(android_id) == ANDROID_ID_LENGTH

        # Make sure we get the same ID when called further
        assert android_id == self.client.get_android_id()

    # pylint: disable=protected-access
    def test_generate_android_id(self) -> None:
        """Test generating mac string."""
        android_id = GLocalAuthenticationTokens._generate_android_id()
        assert len(android_id) == ANDROID_ID_LENGTH

        # Make sure we get different generated mac string
        assert android_id != GLocalAuthenticationTokens._generate_android_id()

    def test_has_expired(self) -> None:
        """Test expiry method."""
        duration_sec = 60
        now = datetime.now(UTC)
        token_dt_expired = now - timedelta(seconds=duration_sec + 1)
        token_dt_non_expired = now - timedelta(seconds=duration_sec - 1)

        # Expired
        assert GLocalAuthenticationTokens._has_expired(token_dt_expired, duration_sec)

        # Non expired
        assert not GLocalAuthenticationTokens._has_expired(
            token_dt_non_expired, duration_sec
        )

    @patch("glocaltokens.client.LOGGER.error")
    @patch("glocaltokens.client.perform_master_login")
    def test_get_master_token(
        self, m_perform_master_login: NonCallableMock, m_log: NonCallableMock
    ) -> None:
        """Test getting master token."""
        # No token in response
        assert self.client.get_master_token() is None
        m_perform_master_login.assert_called_once_with(
            self.client.username, self.client.password, self.client.get_android_id()
        )
        assert m_log.call_count == 1

        # Reset mocks
        m_perform_master_login.reset_mock()
        m_log.reset_mock()

        # With token in response
        expected_master_token = faker.master_token()
        email = faker.email()
        m_perform_master_login.return_value = {
            "Token": expected_master_token,
            "Email": email,
        }
        master_token = self.client.get_master_token()
        m_perform_master_login.assert_called_once_with(
            self.client.username, self.client.password, self.client.get_android_id()
        )
        assert expected_master_token == master_token
        assert self.client.email == email
        assert m_log.call_count == 0

        # Another request - must return the same token all the time
        master_token = self.client.get_master_token()
        assert expected_master_token == master_token

        # Reset mocks
        m_perform_master_login.reset_mock()
        m_log.reset_mock()

        # For passwords that are too long
        m_perform_master_login.side_effect = ValueError("Plaintext is too long.")
        self.client.invalidate_master_token()
        master_token = self.client.get_master_token()
        assert master_token is None
        assert m_log.call_count == 2

    @patch("glocaltokens.client.LOGGER.error")
    @patch("glocaltokens.client.perform_master_login")
    @patch("glocaltokens.client.exchange_token")
    def test_get_master_token__oauth_token(
        self,
        m_exchange_token: NonCallableMock,
        m_perform_master_login: NonCallableMock,
        m_log: NonCallableMock,
    ) -> None:
        """Test getting a master token by exchanging an oauth_token cookie."""
        oauth_token = faker.word()
        client = GLocalAuthenticationTokens(
            username=faker.word(), password=faker.word(), oauth_token=oauth_token
        )
        assert m_log.call_count == 0

        # Failed exchange
        m_exchange_token.return_value = {"Error": "BadAuthentication"}
        assert client.get_master_token() is None
        assert m_log.call_count == 1

        # Successful exchange, preferred over the password
        expected_master_token = faker.master_token()
        m_exchange_token.return_value = {"Token": expected_master_token}
        assert client.get_master_token() == expected_master_token
        m_exchange_token.assert_called_with(
            client.username, oauth_token, client.get_android_id()
        )
        m_perform_master_login.assert_not_called()

        # The stored master token is used from now on
        m_exchange_token.reset_mock()
        assert client.get_master_token() == expected_master_token
        m_exchange_token.assert_not_called()

    @patch("glocaltokens.client.LOGGER.error")
    @patch("glocaltokens.client.perform_oauth")
    @patch("glocaltokens.client.exchange_token")
    def test_get_master_token__oauth_token_without_username(
        self,
        m_exchange_token: NonCallableMock,
        m_perform_oauth: NonCallableMock,
        m_log: NonCallableMock,
    ) -> None:
        """Test an oauth_token alone is enough, and Google's email is kept."""
        oauth_token = faker.word()
        client = GLocalAuthenticationTokens(oauth_token=oauth_token)
        assert m_log.call_count == 0

        master_token = faker.master_token()
        email = faker.email()
        m_exchange_token.return_value = {"Token": master_token, "Email": email}
        assert client.get_master_token() == master_token
        m_exchange_token.assert_called_once_with(
            "", oauth_token, client.get_android_id()
        )
        assert client.email == email
        assert client.username is None

        # get_email() needs no further request
        assert client.get_email() == email
        m_perform_oauth.assert_not_called()

        client.invalidate_master_token()
        assert client.email is None

    @patch("requests.adapters.HTTPAdapter.send")
    def test_get_master_token__oauth_token_request_timeout(
        self, m_send: NonCallableMock
    ) -> None:
        """Test the oauth_token exchange made through gpsoauth has a timeout."""
        m_send.side_effect = requests.ConnectionError("No network")
        client = GLocalAuthenticationTokens(
            username=faker.word(), oauth_token=faker.word()
        )
        with pytest.raises(requests.ConnectionError, match="No network"):
            client.get_master_token()
        m_send.assert_called_once()
        assert m_send.call_args.kwargs["timeout"] == REQUEST_TIMEOUT

    @patch("glocaltokens.client.perform_master_login")
    def test_get_master_token__stored_without_password(
        self, m_perform_master_login: NonCallableMock
    ) -> None:
        """Test a stored master token is returned without a password."""
        master_token = faker.master_token()
        client = GLocalAuthenticationTokens(
            username=faker.word(), master_token=master_token
        )
        assert client.get_master_token() == master_token
        m_perform_master_login.assert_not_called()

    @patch("glocaltokens.client.perform_oauth")
    def test_get_access_token__without_username(
        self, m_perform_oauth: NonCallableMock
    ) -> None:
        """Test a master token alone is enough to get an access token."""
        access_token = faker.access_token()
        m_perform_oauth.return_value = {"Auth": access_token}
        master_token = faker.master_token()
        client = GLocalAuthenticationTokens(master_token=master_token)

        assert client.get_access_token() == access_token
        assert m_perform_oauth.call_args.args == (
            "",
            master_token,
            client.get_android_id(),
        )

    @patch("requests.adapters.HTTPAdapter.send")
    def test_get_master_token__request_timeout(self, m_send: NonCallableMock) -> None:
        """Test requests to Google made through gpsoauth have a timeout."""
        m_send.side_effect = requests.ConnectionError("No network")
        with pytest.raises(requests.ConnectionError, match="No network"):
            self.client.get_master_token()
        m_send.assert_called_once()
        assert m_send.call_args.kwargs["timeout"] == REQUEST_TIMEOUT

    @patch("requests.adapters.HTTPAdapter.send")
    def test_get_access_token__request_timeout(self, m_send: NonCallableMock) -> None:
        """Test the access token request made through gpsoauth has a timeout."""
        m_send.side_effect = requests.ConnectionError("No network")
        client = GLocalAuthenticationTokens(
            username=faker.word(), master_token=faker.master_token()
        )
        with pytest.raises(requests.ConnectionError, match="No network"):
            client.get_access_token()
        m_send.assert_called_once()
        assert m_send.call_args.kwargs["timeout"] == REQUEST_TIMEOUT

    @patch("requests.adapters.HTTPAdapter.send")
    def test_gpsoauth_timeout__not_applied_to_other_callers(
        self, m_send: NonCallableMock
    ) -> None:
        """Test gpsoauth requests made outside glocaltokens keep their timeout."""
        m_send.side_effect = requests.ConnectionError("No network")
        with pytest.raises(requests.ConnectionError, match="No network"):
            gpsoauth.perform_oauth(
                faker.email(),
                faker.master_token(),
                faker.word(),
                "service",
                "app",
                "sig",
            )
        m_send.assert_called_once()
        assert m_send.call_args.kwargs["timeout"] is None

    @patch("glocaltokens.client.requests.get")
    @patch("glocaltokens.client.perform_oauth")
    def test_get_email(
        self, m_perform_oauth: NonCallableMock, m_get: NonCallableMock
    ) -> None:
        """Test the email address is read with a token that may only read it."""
        email = faker.email()
        access_token = faker.access_token()
        m_perform_oauth.return_value = {"Auth": access_token}
        m_get.return_value.ok = True
        m_get.return_value.json.return_value = {
            "email": email,
            "email_verified": True,
        }
        client = GLocalAuthenticationTokens(master_token=faker.master_token())

        assert client.get_email() == email
        assert m_perform_oauth.call_args.kwargs["service"] == (
            "oauth2:https://www.googleapis.com/auth/userinfo.email"
        )
        assert m_get.call_args.kwargs["headers"] == {
            "Authorization": f"Bearer {access_token}"
        }
        assert m_get.call_args.kwargs["timeout"] == REQUEST_TIMEOUT

    @patch("glocaltokens.client.requests.get")
    @patch("glocaltokens.client.perform_oauth")
    def test_get_email__unverified(
        self, m_perform_oauth: NonCallableMock, m_get: NonCallableMock
    ) -> None:
        """Test an email address that Google hasn't verified is not returned."""
        m_perform_oauth.return_value = {"Auth": faker.access_token()}
        m_get.return_value.ok = True
        m_get.return_value.json.return_value = {
            "email": faker.email(),
            "email_verified": False,
        }
        client = GLocalAuthenticationTokens(master_token=faker.master_token())

        assert client.get_email() is None

    @patch("glocaltokens.client.requests.get")
    @patch("glocaltokens.client.perform_oauth")
    def test_get_email__http_error(
        self, m_perform_oauth: NonCallableMock, m_get: NonCallableMock
    ) -> None:
        """Test an error response from Google gives no email address."""
        m_perform_oauth.return_value = {"Auth": faker.access_token()}
        m_get.return_value.ok = False
        m_get.return_value.status_code = 401
        client = GLocalAuthenticationTokens(master_token=faker.master_token())

        assert client.get_email() is None
        m_get.return_value.json.assert_not_called()

    @patch("requests.adapters.HTTPAdapter.send")
    @patch("glocaltokens.client.perform_oauth")
    def test_get_email__token_not_in_url_or_logs(
        self, m_perform_oauth: NonCallableMock, m_send: NonCallableMock
    ) -> None:
        """Test the access token is sent in a header, never in the URL or logs.

        Requests and urllib3 put the URL in debug logs and in connection errors.
        """
        access_token = faker.access_token()
        email = faker.email()
        m_perform_oauth.return_value = {"Auth": access_token}
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(  # pylint: disable=protected-access
            {"email": email, "email_verified": True}
        ).encode()
        m_send.return_value = response
        client = GLocalAuthenticationTokens(
            master_token=faker.master_token(), verbose=True
        )

        with self.assertLogs(level=logging.DEBUG) as logs:
            assert client.get_email() == email

        request = m_send.call_args.args[0]
        assert access_token not in request.url
        assert request.headers["Authorization"] == f"Bearer {access_token}"
        assert not any(access_token in line for line in logs.output)

    @patch("glocaltokens.client.requests.get")
    @patch("glocaltokens.client.perform_oauth")
    def test_get_email__no_access_token(
        self, m_perform_oauth: NonCallableMock, m_get: NonCallableMock
    ) -> None:
        """Test nothing is asked about the email address when Google refuses the token."""
        m_perform_oauth.return_value = {"Error": "BadAuthentication"}
        client = GLocalAuthenticationTokens(master_token=faker.master_token())

        assert client.get_email() is None
        m_get.assert_not_called()

    @patch("requests.adapters.HTTPAdapter.send")
    def test_get_email__request_timeout(self, m_send: NonCallableMock) -> None:
        """Test the access token request for the email address has a timeout."""
        m_send.side_effect = requests.ConnectionError("No network")
        client = GLocalAuthenticationTokens(master_token=faker.master_token())
        with pytest.raises(requests.ConnectionError, match="No network"):
            client.get_email()
        m_send.assert_called_once()
        assert m_send.call_args.kwargs["timeout"] == REQUEST_TIMEOUT

    @patch("glocaltokens.client.LOGGER.error")
    @patch("glocaltokens.client.perform_master_login")
    @patch("glocaltokens.client.perform_oauth")
    def test_get_access_token(
        self,
        m_perform_oauth: NonCallableMock,
        m_get_master_token: NonCallableMock,
        m_log: NonCallableMock,
    ) -> None:
        """Test getting access token."""
        master_token = faker.master_token()
        m_get_master_token.return_value = {"Token": master_token}

        # No token in response
        assert self.client.get_access_token() is None
        m_perform_oauth.assert_called_once_with(
            self.client.username,
            master_token,
            self.client.get_android_id(),
            app=ACCESS_TOKEN_APP_NAME,
            service=ACCESS_TOKEN_SERVICE,
            client_sig=ACCESS_TOKEN_CLIENT_SIGNATURE,
        )
        assert m_log.call_count == 1

        # Reset mocks
        m_perform_oauth.reset_mock()
        m_log.reset_mock()

        # With token in response
        expected_access_token = faker.access_token()
        m_perform_oauth.return_value = {"Auth": expected_access_token}
        access_token = self.client.get_access_token()
        m_perform_oauth.assert_called_once_with(
            self.client.username,
            master_token,
            self.client.get_android_id(),
            app=ACCESS_TOKEN_APP_NAME,
            service=ACCESS_TOKEN_SERVICE,
            client_sig=ACCESS_TOKEN_CLIENT_SIGNATURE,
        )
        assert expected_access_token == access_token
        assert m_log.call_count == 0

        # Reset mocks
        m_perform_oauth.reset_mock()
        m_log.reset_mock()

        # Another request with non expired token must return the same token
        # (no new requests)
        access_token = self.client.get_access_token()
        assert expected_access_token == access_token
        assert m_perform_oauth.call_count == 0

        # Just before expiry the token is still used (no new request)
        self.client.access_token_date = datetime.now(UTC) - timedelta(
            seconds=ACCESS_TOKEN_DURATION - 1
        )
        self.client.get_access_token()
        assert m_perform_oauth.call_count == 0

        # Just after expiry a new token is requested
        self.client.access_token_date = datetime.now(UTC) - timedelta(
            seconds=ACCESS_TOKEN_DURATION + 1
        )
        self.client.get_access_token()
        assert m_perform_oauth.call_count == 1

    @patch("glocaltokens.client.grpc.ssl_channel_credentials")
    @patch("glocaltokens.client.grpc.access_token_call_credentials")
    @patch("glocaltokens.client.grpc.composite_channel_credentials")
    @patch("glocaltokens.client.grpc.secure_channel")
    @patch("glocaltokens.client.StructuresServiceStub")
    @patch("glocaltokens.client.GetHomeGraphRequest")
    @patch("glocaltokens.client.GLocalAuthenticationTokens.get_access_token")
    def test_get_homegraph(
        self,
        m_get_access_token: NonCallableMock,
        m_get_home_graph_request: NonCallableMock,
        m_structure_service_stub: NonCallableMock,
        m_secure_channel: NonCallableMock,
        m_composite_channel_credentials: NonCallableMock,
        m_access_token_call_credentials: NonCallableMock,
        m_ssl_channel_credentials: NonCallableMock,
    ) -> None:
        """Test getting homegraph."""
        # New homegraph
        self.client.get_homegraph()
        assert m_ssl_channel_credentials.call_count == 1
        assert m_access_token_call_credentials.call_count == 1
        assert m_composite_channel_credentials.call_count == 1
        assert m_secure_channel.call_count == 1
        assert m_structure_service_stub.call_count == 1
        assert m_get_home_graph_request.call_count == 1
        assert m_get_access_token.call_count == 1
        m_structure_service_stub.return_value.GetHomeGraph.assert_called_once_with(
            m_get_home_graph_request.return_value, timeout=REQUEST_TIMEOUT
        )

        # Another request with non expired homegraph must return the same homegraph
        # (no new requests)
        self.client.get_homegraph()
        assert m_ssl_channel_credentials.call_count == 1
        assert m_access_token_call_credentials.call_count == 1
        assert m_composite_channel_credentials.call_count == 1
        assert m_secure_channel.call_count == 1
        assert m_structure_service_stub.call_count == 1
        assert m_get_home_graph_request.call_count == 1
        assert m_get_access_token.call_count == 1

        # Just before expiry the homegraph is still used (no new requests)
        self.client.homegraph_date = datetime.now(UTC) - timedelta(
            seconds=HOMEGRAPH_DURATION - 1
        )
        self.client.get_homegraph()
        assert m_secure_channel.call_count == 1

        # Just after expiry a new homegraph is requested
        self.client.homegraph_date = datetime.now(UTC) - timedelta(
            seconds=HOMEGRAPH_DURATION + 1
        )
        self.client.get_homegraph()
        assert m_ssl_channel_credentials.call_count == 2
        assert m_access_token_call_credentials.call_count == 2
        assert m_composite_channel_credentials.call_count == 2
        assert m_secure_channel.call_count == 2
        assert m_structure_service_stub.call_count == 2
        assert m_get_home_graph_request.call_count == 2
        assert m_get_access_token.call_count == 2

    @patch("glocaltokens.client.GLocalAuthenticationTokens.get_access_token")
    @patch("glocaltokens.client.StructuresServiceStub")
    def test_get_homegraph_retries(
        self,
        m_structure_service_stub: NonCallableMock,
        m_get_access_token: NonCallableMock,
    ) -> None:
        """Test retries in  get_homegraph."""
        m_get_access_token.return_value = faker.word()
        rpc_error = grpc.RpcError()
        rpc_error.code = mock.Mock()  # type: ignore[method-assign]
        rpc_error.code.return_value.name = "UNAUTHENTICATED"
        rpc_error.details = mock.Mock()  # type: ignore[method-assign]
        m_structure_service_stub.return_value.GetHomeGraph.side_effect = rpc_error
        result = self.client.get_homegraph()
        assert result is None
        assert m_structure_service_stub.return_value.GetHomeGraph.call_count == 3

    @patch("glocaltokens.client.GLocalAuthenticationTokens.get_homegraph")
    @patch("glocaltokens.client.LOGGER.warning")
    def test_get_google_devices(
        self, m_warning: NonCallableMock, m_get_homegraph: NonCallableMock
    ) -> None:
        """Test getting google devices."""
        # With just one device returned from homegraph
        fake_device_name = faker.word()
        fake_ip_address = faker.ipv4()
        homegraph_device = faker.homegraph_device(device_name=fake_device_name)
        m_get_homegraph.return_value.home.devices = [homegraph_device]

        # With no discover_devices, with no model_list
        google_devices = self.client.get_google_devices(
            disable_discovery=True,
            addresses={fake_device_name: fake_ip_address},
        )
        assert len(google_devices) == 1

        google_device = google_devices[0]
        self.assertDevice(google_device, homegraph_device)
        assert google_device.network_device is not None
        if google_device.network_device is not None:
            assert google_device.network_device.ip_address == fake_ip_address

        # With two devices returned from homegraph
        # but one device having the invalid token
        homegraph_device_valid = faker.homegraph_device(device_name=fake_device_name)
        homegraph_device_invalid = faker.homegraph_device()
        homegraph_device_invalid.local_auth_token = (
            faker.word()
        )  # setting invalid token intentionally
        # Note that we initialize the list with homegraph_device_invalid
        # which should be ignored
        m_get_homegraph.return_value.home.devices = [
            homegraph_device_invalid,
            homegraph_device_valid,
        ]
        google_devices = self.client.get_google_devices(
            disable_discovery=True,
            addresses={fake_device_name: fake_ip_address},
        )
        assert len(google_devices) == 1
        self.assertDevice(google_devices[0], homegraph_device_valid)
        # Devices without a Cast token, like Google Wifi and Nest Wifi routers,
        # are skipped quietly
        m_warning.assert_not_called()
        assert google_devices[0].network_device is not None
        if google_devices[0].network_device is not None:
            assert google_devices[0].network_device.ip_address == fake_ip_address

    @patch("glocaltokens.client.discover_devices")
    @patch("glocaltokens.client.GLocalAuthenticationTokens.get_homegraph")
    def test_get_google_devices_discovered(
        self, m_get_homegraph: NonCallableMock, m_discover_devices: NonCallableMock
    ) -> None:
        """Test that a discovered device keeps its name from the home graph."""
        homegraph_device = faker.homegraph_device()
        m_get_homegraph.return_value.home.devices = [homegraph_device]
        # A speaker pair announces the name of its leading speaker
        network_device = NetworkDevice(
            faker.word(),
            faker.ipv4(),
            8009,
            homegraph_device.hardware.model,
            homegraph_device.device_info.agent_info.unique_id,
        )
        m_discover_devices.return_value = [network_device]

        google_devices = self.client.get_google_devices()
        assert len(google_devices) == 1
        self.assertDevice(google_devices[0], homegraph_device)
        assert google_devices[0].network_device == network_device
        assert google_devices[0].ip_address == network_device.ip_address

    @patch("glocaltokens.client.GLocalAuthenticationTokens.get_google_devices")
    def test_get_google_devices_json(
        self, m_get_google_devices: NonCallableMock
    ) -> None:
        """Test getting google devices as JSON."""
        device_id = str(faker.uuid4())
        device_name = faker.word()
        local_auth_token = faker.local_auth_token()
        ip_address = faker.ipv4()
        port = faker.port_number()
        hardware = faker.word()
        unique_id = faker.word()
        google_device = Device(
            device_id=device_id,
            device_name=device_name,
            local_auth_token=local_auth_token,
            network_device=NetworkDevice(
                device_name, ip_address, port, hardware, unique_id
            ),
            hardware=hardware,
            cloud_device_id=unique_id,
        )
        m_get_google_devices.return_value = [google_device]

        json_string = self.client.get_google_devices_json(
            disable_discovery=True, discovery_timeout=5
        )
        assert m_get_google_devices.call_count == 1
        assert m_get_google_devices.call_args.kwargs["discovery_timeout"] == 5
        received_json = json.loads(json_string)
        received_device = received_json[0]
        assert received_device[JSON_KEY_DEVICE_NAME] == device_name
        assert received_device[JSON_KEY_HARDWARE] == hardware
        assert received_device["cloud_device_id"] == unique_id
        assert received_device[JSON_KEY_LOCAL_AUTH_TOKEN] == local_auth_token
        assert received_device[JSON_KEY_NETWORK_DEVICE][JSON_KEY_PORT] == port
        assert received_device[JSON_KEY_NETWORK_DEVICE][JSON_KEY_IP] == ip_address

    def test_username_escaping(self) -> None:
        """Test that plus sign is escaped."""
        assert self.client._escape_username("login@domain.com") == "login@domain.com"
        assert (
            self.client._escape_username("login+tag@domain.com")
            == "login%2Btag@domain.com"
        )
        assert self.client._escape_username("login") == "login"
        # Such account should be impossible to create.
        assert self.client._escape_username("login+tag") == "login%2Btag"


class DeviceClientTests(TypeAssertions, TestCase):
    """Device specific unittests."""

    def test_initialization__valid(self) -> None:
        """Test initialization that is valid."""
        local_auth_token = faker.local_auth_token()

        # With ip and port
        device = Device(
            device_id=str(faker.uuid4()),
            device_name=faker.word(),
            network_device=NetworkDevice(
                faker.word(),
                faker.ipv4(),
                faker.port_number(),
                faker.word(),
                faker.word(),
            ),
            local_auth_token=local_auth_token,
        )

        assert device.local_auth_token == local_auth_token

    @patch("glocaltokens.client.LOGGER.warning")
    def test_initialization__invalid(self, m_log: NonCallableMock) -> None:
        """Test initialization that is invalid."""

        # Invalid local_auth_token, for example from a Google Wifi or Nest Wifi router
        device = Device(
            device_id=str(faker.uuid4()),
            device_name=faker.word(),
            local_auth_token=faker.word(),
        )
        m_log.assert_not_called()
        assert device.local_auth_token is None
        # A device that failed validation can still be represented
        assert device.as_dict()["network_device"] == {"ip": None, "port": None}

        # A Cast device found on the network with an invalid token is worth a warning
        device = Device(
            device_id=str(faker.uuid4()),
            device_name=faker.word(),
            local_auth_token=faker.word(),
            network_device=NetworkDevice(
                faker.word(), faker.ipv4(), 8009, faker.word(), faker.word()
            ),
        )
        assert m_log.call_count == 1
        assert device.local_auth_token is None
