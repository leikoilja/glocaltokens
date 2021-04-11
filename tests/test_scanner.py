"""Scanner specifc tests"""
from unittest import TestCase

from faker import Faker
from faker.providers import internet as internet_provider, python as python_provider
from mock import patch

from glocaltokens.scanner import GoogleDevice

faker = Faker()
faker.add_provider(internet_provider)
faker.add_provider(python_provider)


class GoogleDeviceTests(TestCase):
    """
    GoogleDevice specific tests
    """

    def test_initialization(self):
        """Initialization tests"""
        name = faker.word()
        ip_address = faker.ipv4_private()
        port = faker.port_number()
        model = faker.word()

        device = GoogleDevice(name, ip_address, port, model)
        self.assertEqual(name, device.name)
        self.assertEqual(ip_address, device.ip_address)
        self.assertEqual(port, device.port)
        self.assertEqual(model, device.model)

        self.assertEqual(
            f"{{name:{name},ip:{ip_address},port:{port},model:{model}}}", str(device)
        )

    @patch("glocaltokens.scanner.LOGGER.error")
    def test_initialization__valid(self, mock):
        """Valid initialization tests"""
        GoogleDevice(
            faker.word(), faker.ipv4_private(), faker.port_number(), faker.word()
        )
        self.assertEqual(mock.call_count, 0)

    @patch("glocaltokens.scanner.LOGGER.error")
    def test_initialization__invalid(self, mock):
        """Invalid initialization tests"""
        # With invalid IP
        GoogleDevice(faker.word(), faker.word(), faker.port_number(), faker.word())
        self.assertEqual(mock.call_count, 1)

        # With negative port
        GoogleDevice(
            faker.word(),
            faker.ipv4_private(),
            faker.pyint(min_value=-9999, max_value=-1),
            faker.word(),
        )
        self.assertEqual(mock.call_count, 2)

        # With greater port
        GoogleDevice(
            faker.word(),
            faker.ipv4_private(),
            faker.pyint(min_value=65535, max_value=999999),
            faker.word(),
        )
        self.assertEqual(mock.call_count, 3)
