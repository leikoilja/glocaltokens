"""Scanner specific tests"""
from __future__ import annotations

from unittest import TestCase
from unittest.mock import NonCallableMock, patch

from faker import Faker
from faker.providers import internet as internet_provider, python as python_provider

from glocaltokens.scanner import NetworkDevice

faker = Faker()  # type: ignore
faker.add_provider(internet_provider)
faker.add_provider(python_provider)


class NetworkDeviceTests(TestCase):
    """
    NetworkDevice specific tests
    """

    def test_initialization(self) -> None:
        """Initialization tests"""
        name = faker.word()
        ip_address = faker.ipv4_private()
        port = faker.port_number()
        model = faker.word()
        unique_id = faker.word()

        device = NetworkDevice(name, ip_address, port, model, unique_id)
        self.assertEqual(name, device.name)
        self.assertEqual(ip_address, device.ip_address)
        self.assertEqual(port, device.port)
        self.assertEqual(model, device.model)
        self.assertEqual(unique_id, device.unique_id)

        self.assertEqual(
            f"NetworkDevice(name='{name}', ip_address='{ip_address}', "
            f"port={port}, model='{model}', unique_id='{unique_id}')",
            str(device),
        )

    @patch("glocaltokens.scanner.LOGGER.error")
    def test_initialization__valid(self, mock: NonCallableMock) -> None:
        """Valid initialization tests"""
        NetworkDevice(
            faker.word(),
            faker.ipv4_private(),
            faker.port_number(),
            faker.word(),
            faker.word(),
        )
        self.assertEqual(mock.call_count, 0)
