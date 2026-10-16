"""Scanner specific tests."""

from __future__ import annotations

import logging
from unittest import TestCase, mock
from unittest.mock import NonCallableMock, patch

from faker import Faker
from faker.providers import internet as internet_provider, python as python_provider
import pytest

from glocaltokens.scanner import LOGGER, CastListener, NetworkDevice, discover_devices

faker = Faker()
faker.add_provider(internet_provider)
faker.add_provider(python_provider)


class NetworkDeviceTests(TestCase):
    """NetworkDevice specific tests."""

    def test_initialization(self) -> None:
        """Initialization tests."""
        name = faker.word()
        ip_address = faker.ipv4_private()
        port = faker.port_number()
        model = faker.word()
        unique_id = faker.word()

        device = NetworkDevice(name, ip_address, port, model, unique_id)
        assert name == device.name
        assert ip_address == device.ip_address
        assert port == device.port
        assert model == device.model
        assert unique_id == device.unique_id

        assert (
            f"NetworkDevice(name='{name}', ip_address='{ip_address}', "
            f"port={port}, model='{model}', unique_id='{unique_id}')" == str(device)
        )

    @patch("glocaltokens.scanner.LOGGER.error")
    def test_service_info__valid(self, m_error: NonCallableMock) -> None:
        """Valid service_info tests."""
        ip_address = faker.ipv4_private()
        port = faker.port_number(is_user=True)
        friendly_name = faker.word()
        model = faker.word()
        unique_id = faker.hexify("^" * 32)

        service = mock.Mock(name="Service")
        service.parsed_addresses.return_value = [ip_address]
        service.port = port
        service.properties = {
            b"fn": friendly_name.encode(),
            b"md": model.encode(),
            b"cd": unique_id.encode(),
        }

        zc = mock.Mock(name="Zeroconf")
        zc.get_service_info.return_value = service

        add_callback = mock.Mock(name="add_callback")
        listener = CastListener(add_callback=add_callback)
        type_ = faker.word()
        name = faker.word()
        listener.add_service(zc, type_, name)
        assert m_error.call_count == 0
        assert listener.devices == {
            name: NetworkDevice(friendly_name, ip_address, port, model, unique_id)
        }
        add_callback.assert_called_once_with()

    @patch("glocaltokens.scanner.LOGGER.error")
    def test_service_info__invalid(self, m_error: NonCallableMock) -> None:
        """Invalid service_info tests."""
        service = mock.Mock(name="Service")
        service.parsed_addresses.return_value = None

        zc = mock.Mock(name="Zeroconf")
        zc.get_service_info.return_value = service

        listener = CastListener()
        type_ = faker.word()
        name = faker.word()

        # With invalid IP
        service.server = faker.word()
        service.port = faker.port_number(is_user=True)
        listener.add_service(zc, type_, name)
        assert m_error.call_count == 1

        # With negative port
        service.server = faker.ipv4_private()
        service.port = faker.pyint(min_value=-9999, max_value=-1)
        listener.add_service(zc, type_, name)
        assert m_error.call_count == 2

        # With greater port
        service.server = faker.ipv4_private()
        service.port = faker.pyint(min_value=65535, max_value=999999)
        listener.add_service(zc, type_, name)
        assert m_error.call_count == 3

        # No devices should be added
        assert listener.count == 0


class DiscoverDevicesTests(TestCase):
    """discover_devices specific tests."""

    @patch("glocaltokens.scanner.ServiceBrowser")
    @patch("glocaltokens.scanner.Zeroconf")
    def test_zeroconf_closing(
        self, m_zeroconf: NonCallableMock, m_service_browser: NonCallableMock
    ) -> None:
        """Close only the Zeroconf instance discovery created itself."""
        # Like the real ServiceBrowser, keep the instance it was given as `zc`
        m_service_browser.side_effect = lambda zc, *_: mock.Mock(zc=zc)

        # Supplied instance stays open
        zc = mock.Mock(name="Zeroconf")
        discover_devices(timeout=0, zeroconf_instance=zc)
        zc.close.assert_not_called()
        m_zeroconf.assert_not_called()

        # Own instance is closed
        discover_devices(timeout=0)
        m_zeroconf.return_value.close.assert_called_once_with()

    @patch("glocaltokens.scanner.ServiceBrowser", mock.Mock())
    @patch("glocaltokens.scanner.Zeroconf", mock.Mock())
    def test_discovery__keeps_application_log_level(self) -> None:
        """Without logging_level, discovery leaves the level to the application."""
        package_logger = logging.getLogger("glocaltokens")
        package_logger.setLevel(logging.CRITICAL)
        try:
            discover_devices(timeout=0)
            package_logger.setLevel(logging.DEBUG)
            assert LOGGER.level == logging.NOTSET
            assert LOGGER.getEffectiveLevel() == logging.DEBUG

            discover_devices(timeout=0, logging_level=logging.ERROR)
            assert LOGGER.level == logging.ERROR
        finally:
            package_logger.setLevel(logging.NOTSET)
            LOGGER.setLevel(logging.NOTSET)

    @patch("glocaltokens.scanner.ServiceBrowser")
    @patch("glocaltokens.scanner.Zeroconf")
    def test_zeroconf_closing__on_error(
        self, m_zeroconf: NonCallableMock, m_service_browser: NonCallableMock
    ) -> None:
        """Close the own Zeroconf instance even if discovery fails."""
        m_service_browser.side_effect = OSError("No network")
        with pytest.raises(OSError, match="No network"):
            discover_devices(timeout=0)
        m_zeroconf.return_value.close.assert_called_once_with()

    @patch("glocaltokens.scanner.Event")
    @patch("glocaltokens.scanner.ServiceBrowser")
    @patch("glocaltokens.scanner.Zeroconf")
    def test_discovery_cleanup__interrupted(
        self,
        m_zeroconf: NonCallableMock,
        m_service_browser: NonCallableMock,
        m_event: NonCallableMock,
    ) -> None:
        """Stop the browser and close the own Zeroconf if the wait is interrupted."""
        m_event.return_value.wait.side_effect = KeyboardInterrupt
        with pytest.raises(KeyboardInterrupt):
            discover_devices(timeout=0)
        m_service_browser.return_value.cancel.assert_called_once_with()
        m_zeroconf.return_value.close.assert_called_once_with()
