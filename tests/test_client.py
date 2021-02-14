from faker import Faker
from mock import patch
from unittest import TestCase

from token_provider import AASETProvider as aas_et_provider

from glocaltokens.client import GLocalAuthenticationTokens
from glocaltokens.client import Device


faker = Faker()
faker.add_provider(aas_et_provider)


class GLocalAuthenticationTokensClientTests(TestCase):
    def setUp(self):
        """Setup method run before every test"""
        pass

    def tearDown(self):
        """Teardown method run after every test"""
        pass

    def test_initialization(self):
        username = faker.word()
        password = faker.word()
        master_token = faker.word()
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

        self.assertIs(client.username, str)
        self.assertIs(client.password, str)
        self.assertIs(client.master_token, str)
        self.assertIs(client.android_id, str)

        self.assertIsNone(client.access_token)
        self.assertIsNone(client.homegraph)
        self.assertIsNone(client.access_token_date)
        self.assertIsNone(client.homegraph_date)

        # Test get_android_id
        client = GLocalAuthenticationTokens(username, password)
        android_id = client.get_android_id()
        self.assertIsNotNone(android_id)
        self.assertIs(android_id, str)

    @patch("glocaltokens.client.LOGGER.error")
    def test_initialization__valid(self, mock):
        # --- GLocalAuthenticationTokens initialization --- #
        # With username and password
        GLocalAuthenticationTokens(username=faker.word(), password=faker.word())
        self.assertEqual(mock.call_count, 0)

        # With master_token
        GLocalAuthenticationTokens(master_token=faker.word())
        self.assertEqual(mock.call_count, 0)

        # --- client.Device initialization --- #
        # With ip and port
        # TODO: local_auth_token doesn't follow aas_et
        Device(device_name=faker.word(), local_auth_token=faker.aas_et)

    @patch("glocaltokens.client.LOGGER.error")
    def test_initialization__invalid(self, mock):

        # Without username
        GLocalAuthenticationTokens(password=faker.word())
        self.assertEqual(mock.call_count, 1)

        # Without password
        GLocalAuthenticationTokens(username=faker.word())
        self.assertEqual(mock.call_count, 2)

        # Without username and password
        GLocalAuthenticationTokens()
        self.assertEqual(mock.call_count, 3)
