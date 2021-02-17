from unittest import TestCase

from faker import Faker
from faker.providers import internet as internet_provider
from faker.providers import python as python_provider
from mock import patch

from glocaltokens.scanner import GoogleDevice

faker = Faker()
faker.add_provider(internet_provider)
faker.add_provider(python_provider)


class GLocalAuthenticationTokensClientTests(TestCase):
    def setUp(self):
        """Setup method run before every test"""
        pass

    def tearDown(self):
        """Teardown method run after every test"""
        pass

    def test_initialization(self):
        name = faker.word()
        ip = faker.ipv4_private()
        port = faker.port_number()
        model = faker.word()

        device = GoogleDevice(name, ip, port, model)
        self.assertEqual(name, device.name)
        self.assertEqual(ip, device.ip)
        self.assertEqual(port, device.port)
        self.assertEqual(model, device.model)

    @patch("glocaltokens.scanner._LOGGER.error")
    def test_initialization__valid(self, mock):
        GoogleDevice(
            faker.word(), faker.ipv4_private(), faker.port_number(), faker.word()
        )
        self.assertEqual(mock.call_count, 0)

    @patch("glocaltokens.scanner._LOGGER.error")
    def test_initialization__invalid(self, mock):
        # With invalid IP
        GoogleDevice(faker.word(), faker.word(), faker.port_number(), faker.word())
        self.assertEqual(mock.call_count, 1)

        # With non-numeric port
        GoogleDevice(faker.word(), faker.ipv4_private(), faker.word(), faker.word())
        self.assertEqual(mock.call_count, 2)

        # With float port
        GoogleDevice(faker.word(), faker.ipv4_private(), faker.pyfloat(), faker.word())
        self.assertEqual(mock.call_count, 3)

        # With negative port
        GoogleDevice(
            faker.word(),
            faker.ipv4_private(),
            faker.pyint(min_value=-9999, max_value=-1),
            faker.word(),
        )
        self.assertEqual(mock.call_count, 4)

        # With greater port
        GoogleDevice(
            faker.word(),
            faker.ipv4_private(),
            faker.pyint(min_value=65535, max_value=999999),
            faker.word(),
        )
        self.assertEqual(mock.call_count, 5)
