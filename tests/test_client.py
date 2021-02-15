from unittest import TestCase

from faker import Faker
from mock import patch

from glocaltokens.client import GLocalAuthenticationTokens
from glocaltokens.const import ANDROID_ID_LENGTH

faker = Faker()


class GLocalAuthenticationTokensClientTests(TestCase):
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

        self.assertIsNone(client.access_token)
        self.assertIsNone(client.homegraph)
        self.assertIsNone(client.access_token_date)
        self.assertIsNone(client.homegraph_date)

    @patch("glocaltokens.client.LOGGER.error")
    def test_initialization__valid(self, mock):

        # Without username and password
        GLocalAuthenticationTokens(username=faker.word(), password=faker.word())
        self.assertEqual(mock.call_count, 0)

        # Without master_token
        GLocalAuthenticationTokens(master_token=faker.word())
        self.assertEqual(mock.call_count, 0)

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

    def test_get_android_id(self):
        android_id = self.client.get_android_id()
        self.assertTrue(len(android_id) == ANDROID_ID_LENGTH)

        # Make sure we get the same ID when called further
        self.assertEqual(android_id, self.client.get_android_id())

    def test_generate_mac_string(self):
        mac_string = GLocalAuthenticationTokens._generate_mac_string()
        self.assertTrue(len(mac_string) == ANDROID_ID_LENGTH)

        # Make sure we get different generated mac string
        self.assertNotEqual(
            mac_string, GLocalAuthenticationTokens._generate_mac_string()
        )
