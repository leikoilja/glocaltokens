import json
from datetime import datetime, timedelta
from unittest import TestCase

from faker import Faker
from faker.providers import internet
from mock import patch

from glocaltokens.client import Device, GLocalAuthenticationTokens
from glocaltokens.const import (
    ACCESS_TOKEN_APP_NAME,
    ACCESS_TOKEN_CLIENT_SIGNATURE,
    ACCESS_TOKEN_DURATION,
    ACCESS_TOKEN_SERVICE,
    ANDROID_ID_LENGTH,
    HOMEGRAPH_DURATION,
    JSON_KEY_DEVICE_NAME,
    JSON_KEY_GOOGLE_DEVICE,
    JSON_KEY_HARDWARE,
    JSON_KEY_IP,
    JSON_KEY_LOCAL_AUTH_TOKEN,
    JSON_KEY_PORT,
)
from glocaltokens.utils.types import Struct
from tests.factory.mixin import TypeTestMixin
from tests.factory.providers import HomegraphProvider, TokenProvider

faker = Faker()
faker.add_provider(TokenProvider)
faker.add_provider(HomegraphProvider)
faker.add_provider(internet)


class GLocalAuthenticationTokensClientTests(TypeTestMixin, TestCase):
    def setUp(self):
        """Setup method run before every test"""
        self.client = GLocalAuthenticationTokens(
            username=faker.word(), password=faker.word()
        )

    def tearDown(self):
        """Teardown method run after every test"""
        pass

    def test_initialization(self):
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
        self.assertEqual(username, client.username)
        self.assertEqual(password, client.password)
        self.assertEqual(master_token, client.master_token)
        self.assertEqual(android_id, client.android_id)

        self.assertIsString(client.username)
        self.assertIsString(client.password)
        self.assertIsString(client.master_token)
        self.assertIsString(client.android_id)

        self.assertIsNone(client.access_token)
        self.assertIsNone(client.homegraph)
        self.assertIsNone(client.access_token_date)
        self.assertIsNone(client.homegraph_date)

        self.assertIsAASET(client.master_token)

    @patch("glocaltokens.client.LOGGER.error")
    def test_initialization__valid(self, m_log):
        # With username and password
        GLocalAuthenticationTokens(username=faker.word(), password=faker.word())
        self.assertEqual(m_log.call_count, 0)

        # With master_token
        GLocalAuthenticationTokens(master_token=faker.master_token())
        self.assertEqual(m_log.call_count, 0)

    @patch("glocaltokens.client.LOGGER.error")
    def test_initialization__invalid(self, m_log):
        # Without username
        GLocalAuthenticationTokens(password=faker.word())
        self.assertEqual(m_log.call_count, 1)

        # Without password
        GLocalAuthenticationTokens(username=faker.word())
        self.assertEqual(m_log.call_count, 2)

        # Without username and password
        GLocalAuthenticationTokens()
        self.assertEqual(m_log.call_count, 3)

        # With invalid master_token
        GLocalAuthenticationTokens(master_token=faker.word())
        self.assertEqual(m_log.call_count, 4)

    def test_get_android_id(self):
        android_id = self.client.get_android_id()
        self.assertTrue(len(android_id) == ANDROID_ID_LENGTH)

        self.assertIsString(android_id)

        # Make sure we get the same ID when called further
        self.assertEqual(android_id, self.client.get_android_id())

    def test_generate_mac_string(self):
        mac_string = GLocalAuthenticationTokens._generate_mac_string()
        self.assertTrue(len(mac_string) == ANDROID_ID_LENGTH)

        # Make sure we get different generated mac string
        self.assertNotEqual(
            mac_string, GLocalAuthenticationTokens._generate_mac_string()
        )

    def test_has_expired(self):
        duration_sec = 60
        now = datetime.now()
        token_dt__expired = now - timedelta(seconds=duration_sec + 1)
        token_dt__non_expired = now - timedelta(seconds=duration_sec - 1)

        # Expired
        self.assertTrue(
            GLocalAuthenticationTokens._has_expired(token_dt__expired, duration_sec)
        )

        # Non expired
        self.assertFalse(
            GLocalAuthenticationTokens._has_expired(token_dt__non_expired, duration_sec)
        )

    @patch("glocaltokens.client.LOGGER.error")
    @patch("glocaltokens.client.perform_master_login")
    def test_get_master_token(self, m_perform_master_login, m_log):
        # No token in response
        self.assertIsNone(self.client.get_master_token())
        m_perform_master_login.assert_called_once_with(
            self.client.username, self.client.password, self.client.get_android_id()
        )
        self.assertEqual(m_log.call_count, 1)

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
        self.assertEqual(expected_master_token, master_token)
        self.assertEqual(m_log.call_count, 0)

        # Another request - must return the same token all the time
        master_token = self.client.get_master_token()
        self.assertEqual(expected_master_token, master_token)

    @patch("glocaltokens.client.LOGGER.error")
    @patch("glocaltokens.client.perform_master_login")
    @patch("glocaltokens.client.perform_oauth")
    def test_get_access_token(self, m_perform_oauth, m_get_master_token, m_log):
        master_token = faker.master_token()
        m_get_master_token.return_value = {"Token": master_token}

        # No token in response
        self.assertIsNone(self.client.get_access_token())
        m_perform_oauth.assert_called_once_with(
            self.client.username,
            master_token,
            self.client.get_android_id(),
            app=ACCESS_TOKEN_APP_NAME,
            service=ACCESS_TOKEN_SERVICE,
            client_sig=ACCESS_TOKEN_CLIENT_SIGNATURE,
        )
        self.assertEqual(m_log.call_count, 1)

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
        self.assertEqual(expected_access_token, access_token)
        self.assertEqual(m_log.call_count, 0)

        # Reset mocks
        m_perform_oauth.reset_mock()
        m_log.reset_mock()

        # Another request with non expired token must return the same token
        # (no new requests)
        access_token = self.client.get_access_token()
        self.assertEqual(expected_access_token, access_token)
        self.assertEqual(m_perform_oauth.call_count, 0)

        # Another request with expired token must return new token (new request)
        self.client.access_token_date = self.client.access_token_date - timedelta(
            ACCESS_TOKEN_DURATION + 1
        )
        access_token = self.client.get_access_token()
        self.assertEqual(m_perform_oauth.call_count, 1)

    @patch("glocaltokens.client.grpc.ssl_channel_credentials")
    @patch("glocaltokens.client.grpc.access_token_call_credentials")
    @patch("glocaltokens.client.grpc.composite_channel_credentials")
    @patch("glocaltokens.client.grpc.secure_channel")
    @patch("glocaltokens.client.v1_pb2_grpc.StructuresServiceStub")
    @patch("glocaltokens.client.v1_pb2.GetHomeGraphRequest")
    @patch("glocaltokens.client.GLocalAuthenticationTokens.get_access_token")
    def test_get_homegraph(
        self,
        m_get_access_token,
        m_get_home_graph_request,
        m_structure_service_stub,
        m_secure_channel,
        m_composite_channel_credentials,
        m_access_token_call_credentials,
        m_ssl_channel_credentials,
    ):
        # New homegraph
        self.client.get_homegraph()
        self.assertEqual(m_ssl_channel_credentials.call_count, 1)
        self.assertEqual(m_access_token_call_credentials.call_count, 1)
        self.assertEqual(m_composite_channel_credentials.call_count, 1)
        self.assertEqual(m_secure_channel.call_count, 1)
        self.assertEqual(m_structure_service_stub.call_count, 1)
        self.assertEqual(m_get_home_graph_request.call_count, 1)

        # Another request with non expired homegraph must return the same homegraph
        # (no new requests)
        self.client.get_homegraph()
        self.assertEqual(m_ssl_channel_credentials.call_count, 1)
        self.assertEqual(m_access_token_call_credentials.call_count, 1)
        self.assertEqual(m_composite_channel_credentials.call_count, 1)
        self.assertEqual(m_secure_channel.call_count, 1)
        self.assertEqual(m_structure_service_stub.call_count, 1)
        self.assertEqual(m_get_home_graph_request.call_count, 1)

        # Expired homegraph
        self.client.homegraph_date = self.client.homegraph_date - timedelta(
            HOMEGRAPH_DURATION + 1
        )
        self.client.get_homegraph()
        self.assertEqual(m_ssl_channel_credentials.call_count, 2)
        self.assertEqual(m_access_token_call_credentials.call_count, 2)
        self.assertEqual(m_composite_channel_credentials.call_count, 2)
        self.assertEqual(m_secure_channel.call_count, 2)
        self.assertEqual(m_structure_service_stub.call_count, 2)
        self.assertEqual(m_get_home_graph_request.call_count, 2)

    @patch("glocaltokens.client.GLocalAuthenticationTokens.get_homegraph")
    def test_get_google_devices(self, m_get_homegraph):
        # With just one device returned from homegraph
        homegraph_devices = faker.google_devices(max_devices=1)
        homegraph_device = homegraph_devices[0]
        m_get_homegraph.return_value.home.devices = homegraph_devices

        # With no discover_devices, with no model_list
        google_devices = self.client.get_google_devices(disable_discovery=True)
        self.assertEqual(len(google_devices), 1)

        google_device = google_devices[0]
        self.assertEqual(type(google_device), Device)
        self.assertEqual(
            google_device.local_auth_token, homegraph_device.local_auth_token
        )
        self.assertEqual(google_device.device_name, homegraph_device.device_name)
        self.assertEqual(google_device.hardware, homegraph_device.hardware.model)

        # With many devices returned from homegraph
        homegraph_devices = faker.google_devices()
        m_get_homegraph.return_value.home.devices = homegraph_devices

        # With no discover_devices, with no model_list
        google_devices = self.client.get_google_devices(disable_discovery=True)
        self.assertEqual(len(homegraph_devices), len(google_devices))

    @patch("glocaltokens.client.GLocalAuthenticationTokens.get_google_devices")
    def test_get_google_devices_json(self, m_get_google_devices):
        device_name = faker.word()
        local_auth_token = faker.local_auth_token()
        ip = faker.ipv4()
        port = faker.port_number()
        hardware = faker.word()
        google_device = Device(
            device_name=device_name,
            local_auth_token=local_auth_token,
            ip=ip,
            port=port,
            hardware=hardware,
        )
        m_get_google_devices.return_value = [google_device]

        json_string = self.client.get_google_devices_json(disable_discovery=True)
        self.assertEqual(m_get_google_devices.call_count, 1)
        self.assertIsString(json_string)
        received_json = json.loads(json_string)
        received_device = received_json[0]
        self.assertEqual(received_device[JSON_KEY_DEVICE_NAME], device_name)
        self.assertEqual(received_device[JSON_KEY_HARDWARE], hardware)
        self.assertEqual(received_device[JSON_KEY_LOCAL_AUTH_TOKEN], local_auth_token)
        self.assertEqual(received_device[JSON_KEY_GOOGLE_DEVICE][JSON_KEY_PORT], port)
        self.assertEqual(received_device[JSON_KEY_GOOGLE_DEVICE][JSON_KEY_IP], ip)


class DeviceClientTests(TypeTestMixin, TestCase):
    def test_initialization__valid(self):
        local_auth_token = faker.local_auth_token()

        # With ip and port
        device = Device(device_name=faker.word(), local_auth_token=local_auth_token)

        self.assertEqual(device.local_auth_token, local_auth_token)

    @patch("glocaltokens.client.LOGGER.error")
    def test_initialization__invalid(self, m_log):
        local_auth_token = faker.local_auth_token()

        # With only ip
        device = Device(
            device_name=faker.word(),
            local_auth_token=local_auth_token,
            ip=faker.ipv4_private(),
        )
        self.assertEqual(m_log.call_count, 1)
        self.assertIsNone(device.local_auth_token)

        # With only port
        device = Device(
            device_name=faker.word(),
            local_auth_token=local_auth_token,
            port=faker.port_number(),
        )
        self.assertEqual(m_log.call_count, 2)
        self.assertIsNone(device.local_auth_token)

        # Invalid local_auth_token
        device = Device(device_name=faker.word(), local_auth_token=local_auth_token)
        self.assertEqual(m_log.call_count, 3)
        self.assertIsNone(device.local_auth_token)
