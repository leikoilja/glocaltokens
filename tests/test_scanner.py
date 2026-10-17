"""Scanner specific tests."""

from __future__ import annotations

import logging
from threading import Event
import time
from unittest import TestCase, mock
from unittest.mock import NonCallableMock, patch

from faker import Faker
from faker.providers import internet as internet_provider, python as python_provider
import pytest

from glocaltokens.const import GOOGLE_CAST_GROUP
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

    def test_service_info__invalid_utf8(self) -> None:
        """Skip a service whose TXT value is not valid UTF-8 without raising."""
        service = mock.Mock(name="Service")
        service.parsed_addresses.return_value = [faker.ipv4_private()]
        service.port = faker.port_number(is_user=True)
        service.properties = {b"fn": b"\xff\xfe", b"md": b"Chromecast", b"cd": b"id"}
        zc = mock.Mock(name="Zeroconf")
        zc.get_service_info.return_value = service

        listener = CastListener()
        listener.add_service(zc, faker.word(), faker.word())
        assert listener.count == 0

    @patch("glocaltokens.scanner.ServiceInfo")
    def test_service_info__deadline(self, m_service_info: NonCallableMock) -> None:
        """Service lookups wait no longer than the discovery deadline."""
        zc = mock.Mock(name="Zeroconf")
        zc.get_service_info.return_value = None

        # Out of time: only details zeroconf already has are used
        cached = m_service_info.return_value
        cached.load_from_cache.return_value = False
        listener = CastListener(deadline=time.monotonic() - 1)
        listener.add_service(zc, "type", "name")
        assert listener.count == 0

        cached.load_from_cache.return_value = True
        cached.parsed_addresses.return_value = [faker.ipv4_private()]
        cached.port = faker.port_number(is_user=True)
        cached.properties = {b"fn": b"Home", b"md": b"Google Home", b"cd": b"id"}
        listener.add_service(zc, "type", "name")
        assert listener.count == 1
        cached.load_from_cache.assert_called_with(zc)
        zc.get_service_info.assert_not_called()

        CastListener(deadline=time.monotonic() + 1).add_service(zc, "type", "name")
        assert zc.get_service_info.call_count == 4
        for call in zc.get_service_info.call_args_list:
            assert 0 < call.kwargs["timeout"] <= 1000

    def test_service_info__address_choice(self) -> None:
        """IPv4 is preferred, and a link-local IPv6 address is never used."""
        ipv4 = faker.ipv4_private()
        ipv6 = "2001:db8::1"
        link_local = "fe80::bbc8:4475:d22a:d8de"
        service = mock.Mock(name="Service")
        service.port = faker.port_number(is_user=True)
        service.properties = {b"fn": b"Home", b"md": b"Google Home", b"cd": b"id"}
        zc = mock.Mock(name="Zeroconf")
        zc.get_service_info.return_value = service

        # zeroconf lists IPv4 addresses before IPv6 ones
        for addresses, expected in (
            ([ipv4, ipv6], ipv4),
            ([ipv4, link_local], ipv4),
            ([link_local, ipv6], ipv6),
            ([ipv6], ipv6),
            ([link_local], None),
            ([], None),
        ):
            service.parsed_addresses.return_value = addresses
            listener = CastListener()
            listener.add_service(zc, "type", "name")
            if expected is None:
                assert listener.count == 0, addresses
            else:
                assert listener.devices["name"].ip_address == expected, addresses

    @patch("glocaltokens.scanner.LOGGER.error")
    def test_service_info__invalid(self, m_error: NonCallableMock) -> None:
        """Invalid service_info tests."""
        service = mock.Mock(name="Service")
        service.parsed_addresses.return_value = [faker.ipv4_private()]

        zc = mock.Mock(name="Zeroconf")
        zc.get_service_info.return_value = service

        listener = CastListener()
        type_ = faker.word()
        name = faker.word()

        # With negative port
        service.port = faker.pyint(min_value=-9999, max_value=-1)
        listener.add_service(zc, type_, name)
        assert m_error.call_count == 1

        # With greater port
        service.port = faker.pyint(min_value=65536, max_value=999999)
        listener.add_service(zc, type_, name)
        assert m_error.call_count == 2

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
    @patch("glocaltokens.scanner.Zeroconf", mock.Mock())
    def test_max_devices__counts_wanted_devices(
        self, m_service_browser: NonCallableMock, m_event: NonCallableMock
    ) -> None:
        """Devices that discovery filters out do not count towards max_devices."""
        discovery_complete = m_event.return_value = Event()
        complete_after: list[bool] = []

        def browse(_zc: object, _type: str, listener: CastListener) -> mock.Mock:
            for unique_id, model in (
                ("chromecast", "Chromecast"),
                ("group", GOOGLE_CAST_GROUP),
                ("home", "Google Home"),
            ):
                listener.devices[unique_id] = NetworkDevice(
                    unique_id, faker.ipv4_private(), 8009, model, unique_id
                )
                assert listener.add_callback is not None
                listener.add_callback()
                complete_after.append(discovery_complete.is_set())
            return mock.Mock()

        m_service_browser.side_effect = browse
        devices = discover_devices(
            models_list=["Google Home", GOOGLE_CAST_GROUP], max_devices=1
        )
        assert complete_after == [False, False, True]
        assert [device.unique_id for device in devices] == ["home"]

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
