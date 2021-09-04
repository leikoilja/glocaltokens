"""Scanner specific tests"""
from __future__ import annotations

from unittest import TestCase, mock
from unittest.mock import NonCallableMock, patch

from faker import Faker
from faker.providers import internet as internet_provider, python as python_provider

from glocaltokens.scanner import CastListener, NetworkDevice

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
    def test_service_info__valid(self, m_error: NonCallableMock) -> None:
        """Valid service_info tests"""
        service = mock.Mock(name="Service")
        service.parsed_addresses.return_value = None
        service.server = faker.ipv4_private()
        service.port = faker.port_number()

        zc = mock.Mock(name="Zeroconf")
        zc.get_service_info.return_value = service

        listener = CastListener()
        type_ = faker.word()
        name = faker.word()
        listener.add_service(zc, type_, name)
        self.assertEqual(m_error.call_count, 0)

    @patch("glocaltokens.scanner.LOGGER.error")
    def test_service_info__invalid(self, m_error: NonCallableMock) -> None:
        """Invalid service_info tests"""
        service = mock.Mock(name="Service")
        service.parsed_addresses.return_value = None

        zc = mock.Mock(name="Zeroconf")
        zc.get_service_info.return_value = service

        listener = CastListener()
        type_ = faker.word()
        name = faker.word()

        # With invalid IP
        service.server = faker.word()
        service.port = faker.port_number()
        listener.add_service(zc, type_, name)
        self.assertEqual(m_error.call_count, 1)

        # With negative port
        service.server = faker.ipv4_private()
        service.port = faker.pyint(min_value=-9999, max_value=-1)
        listener.add_service(zc, type_, name)
        self.assertEqual(m_error.call_count, 2)

        # With greater port
        service.server = faker.ipv4_private()
        service.port = faker.pyint(min_value=65535, max_value=999999)
        listener.add_service(zc, type_, name)
        self.assertEqual(m_error.call_count, 3)

        # No devices should be added
        self.assertEqual(listener.count, 0)
