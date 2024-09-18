"""Client specific unittests."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import logging
from unittest import TestCase, mock
from unittest.mock import NonCallableMock, patch

from faker import Faker
from faker.providers import internet
import grpc

from glocaltokens.client import Device, GLocalAuthenticationTokens
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

    @patch("glocaltokens.client.LOGGER.setLevel")
    def test_initialization__valid_verbose_logger(
        self, m_set_level: NonCallableMock
    ) -> None:
        """Valid initialization tests with verbose logging."""
        # Non verbose
        GLocalAuthenticationTokens(username=faker.word(), password=faker.word())
        m_set_level.assert_called_once_with(logging.ERROR)

        m_set_level.reset_mock()

        # Verbose
        GLocalAuthenticationTokens(
            username=faker.word(), password=faker.word(), verbose=True
        )
        m_set_level.assert_called_once_with(logging.DEBUG)

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
        now = datetime.now()
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
        m_perform_master_login.return_value = {"Token": expected_master_token}
        master_token = self.client.get_master_token()
        m_perform_master_login.assert_called_once_with(
            self.client.username, self.client.password, self.client.get_android_id()
        )
        assert expected_master_token == master_token
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

        # Another request with expired token must return new token (new request)
        assert self.client.access_token_date is not None
        self.client.access_token_date = self.client.access_token_date - timedelta(
            ACCESS_TOKEN_DURATION + 1
        )
        access_token = self.client.get_access_token()
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

        # Expired homegraph
        assert self.client.homegraph_date is not None
        self.client.homegraph_date = self.client.homegraph_date - timedelta(
            HOMEGRAPH_DURATION + 1
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
    def test_get_google_devices(self, m_get_homegraph: NonCallableMock) -> None:
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
        assert google_devices[0].network_device is not None
        if google_devices[0].network_device is not None:
            assert google_devices[0].network_device.ip_address == fake_ip_address

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
        )
        m_get_google_devices.return_value = [google_device]

        json_string = self.client.get_google_devices_json(disable_discovery=True)
        assert m_get_google_devices.call_count == 1
        received_json = json.loads(json_string)
        received_device = received_json[0]
        assert received_device[JSON_KEY_DEVICE_NAME] == device_name
        assert received_device[JSON_KEY_HARDWARE] == hardware
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

        # Invalid local_auth_token
        device = Device(
            device_id=str(faker.uuid4()),
            device_name=faker.word(),
            local_auth_token=faker.word(),
        )
        assert m_log.call_count == 1
        assert device.local_auth_token is None
