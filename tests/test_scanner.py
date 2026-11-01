"""Scanner specific tests."""

from __future__ import annotations

import asyncio
import logging
from threading import Event
import time
from typing import TYPE_CHECKING, Protocol, override
from unittest import IsolatedAsyncioTestCase, TestCase, mock
from unittest.mock import NonCallableMock, patch

from faker import Faker
from faker.providers import internet as internet_provider, python as python_provider
import pytest
from zeroconf import BadTypeInNameException, ServiceStateChange

from glocaltokens.const import GOOGLE_CAST_GROUP, SERVICE_INFO_TIMEOUT
from glocaltokens.scanner import (
    LOGGER,
    CastListener,
    NetworkDevice,
    _async_request,
    async_discover_devices,
    discover_devices,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from zeroconf import Zeroconf

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

    def test_service_info__update_adds_ipv4(self) -> None:
        """An IPv4 address that arrives after IPv6 replaces it on update.

        zeroconf sends an update when a new address record for the device's
        host arrives, and the listener then looks the service up again.
        """
        ipv4 = faker.ipv4_private()
        ipv6 = "2001:db8::1"
        service = mock.Mock(name="Service")
        service.port = faker.port_number(is_user=True)
        service.properties = {b"fn": b"Home", b"md": b"Google Home", b"cd": b"id"}
        zc = mock.Mock(name="Zeroconf")
        zc.get_service_info.return_value = service
        listener = CastListener()

        service.parsed_addresses.return_value = [ipv6]
        listener.add_service(zc, "type", "name")
        assert listener.devices["name"].ip_address == ipv6

        service.parsed_addresses.return_value = [ipv4, ipv6]
        listener.update_service(zc, "type", "name")
        assert listener.devices["name"].ip_address == ipv4

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
        """Discovery leaves the level to the application."""
        package_logger = logging.getLogger("glocaltokens")
        package_logger.setLevel(logging.CRITICAL)
        try:
            discover_devices(timeout=0)
            package_logger.setLevel(logging.DEBUG)
            assert LOGGER.level == logging.NOTSET
            assert LOGGER.getEffectiveLevel() == logging.DEBUG

            with pytest.warns(DeprecationWarning, match="logging_level is deprecated"):
                discover_devices(timeout=0, logging_level=logging.ERROR)
            assert LOGGER.level == logging.NOTSET
        finally:
            package_logger.setLevel(logging.NOTSET)

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
    def test_max_devices__counts_device_added_on_update(
        self, m_service_browser: NonCallableMock, m_event: NonCallableMock
    ) -> None:
        """A device that discovery first adds on an update counts towards max_devices."""
        discovery_complete = m_event.return_value = Event()

        def browse(_zc: object, _type: str, listener: CastListener) -> mock.Mock:
            service = mock.Mock(name="Service")
            service.port = 8009
            service.properties = {b"fn": b"Home", b"md": b"Google Home", b"cd": b"id"}
            zc = mock.Mock(name="Zeroconf")
            zc.get_service_info.return_value = service
            # Skipped, as a link-local IPv6 address can't be used
            service.parsed_addresses.return_value = ["fe80::1"]
            listener.add_service(zc, "type", "name")
            # zeroconf sends an update when an IPv4 address arrives
            service.parsed_addresses.return_value = [faker.ipv4_private()]
            listener.update_service(zc, "type", "name")
            return mock.Mock()

        m_service_browser.side_effect = browse
        discover_devices(max_devices=1, timeout=1)
        assert discovery_complete.is_set()

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


CAST_SERVICE = "_googlecast._tcp.local."


class Handler(Protocol):
    """A service browser handler, which zeroconf calls with keywords."""

    def __call__(
        self,
        *,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        """Handle a change of a service."""


class FakeServiceInfo:
    """A lookup of a Cast service, answered when the test chooses.

    on_cancel says what a cancelled lookup does: "raise" at once, "hold" its
    cleanup until finish_cleanup is set and then raise, or "complete" with its
    answer once finish_cleanup is set, as a lookup that cancellation reaches
    too late would. Requests answer False at once while misses remain, and
    raise error if it is set.
    """

    def __init__(self, type_: str, name: str) -> None:
        """Start a lookup with no answer yet."""
        self.type = type_
        self.name = name
        self.port: int | None = None
        self.properties: dict[bytes, bytes] = {}
        self.addresses: list[str] = []
        self.answer = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.finish_cleanup = asyncio.Event()
        self.on_cancel = "raise"
        self.task: asyncio.Task[object] | None = None
        self.requests: list[tuple[object, float]] = []
        self.misses = 0
        self.error: Exception | None = None
        self.cached: NetworkDevice | None = None

    def describe(self, device: NetworkDevice) -> None:
        """Answer with the service of this device."""
        self.port = device.port
        self.addresses = [device.ip_address]
        self.properties = {
            b"fn": device.name.encode(),
            b"md": device.model.encode(),
            b"cd": device.unique_id.encode(),
        }
        self.answer.set()

    def parsed_addresses(self) -> list[str]:
        """Return the addresses of the answer."""
        return self.addresses

    def load_from_cache(self, _zc: object) -> bool:
        """Answer with the cached device, if there is one."""
        if self.cached is None:
            return False
        self.describe(self.cached)
        return True

    # The signature of zeroconf's AsyncServiceInfo.async_request()
    async def async_request(self, zc: object, timeout: float) -> bool:  # noqa: ASYNC109
        """Wait for the test to answer, or handle cancellation as asked."""
        self.task = asyncio.current_task()
        self.requests.append((zc, timeout))
        if self.error is not None:
            raise self.error
        if len(self.requests) <= self.misses:
            return False
        try:
            await self.answer.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            if self.on_cancel == "raise":
                raise
            await self.finish_cleanup.wait()
            if self.on_cancel == "hold":
                raise
        return True


class FakeBrowser:
    """A service browser whose changes the test reports."""

    def __init__(self, zc: Zeroconf, type_: str, handlers: list[Handler]) -> None:
        """Keep the handler that discovery gave."""
        self.zc = zc
        self.type = type_
        self.handlers = handlers
        self.cancelled = asyncio.Event()

    def change(self, name: str, state_change: ServiceStateChange) -> None:
        """Report a change of a Cast service, as zeroconf does."""
        for handler in self.handlers:
            handler(
                zeroconf=self.zc,
                service_type=CAST_SERVICE,
                name=name,
                state_change=state_change,
            )

    async def async_cancel(self) -> None:
        """Stop browsing, without waiting."""
        self.cancelled.set()


class FakeAsyncZeroconf:
    """A Zeroconf instance that discovery creates itself."""

    def __init__(self) -> None:
        """Create an instance that isn't closed."""
        self.zeroconf = mock.NonCallableMock(name="OwnZeroconf")
        self.closed = False
        self.closing = asyncio.Event()
        # Set to hold closing until release_close is set
        self.hold_close = False
        self.release_close = asyncio.Event()
        self.close_error: Exception | None = None

    async def async_close(self) -> None:
        """Close the instance, once released if it is held."""
        self.closing.set()
        if self.hold_close:
            await self.release_close.wait()
        if self.close_error is not None:
            raise self.close_error
        self.closed = True


def network_device(model: str = "Google Nest Mini") -> NetworkDevice:
    """Return an invented Cast device on the local network."""
    return NetworkDevice(
        name=faker.word(),
        ip_address=faker.ipv4_private(),
        port=faker.port_number(is_user=True),
        model=model,
        unique_id=faker.hexify("^" * 32),
    )


class AsyncDiscoveryTests(IsolatedAsyncioTestCase):
    """async_discover_devices() with a fake browser and lookups."""

    @override
    async def asyncSetUp(self) -> None:
        """Replace zeroconf's browser, lookups and instance with fakes."""
        self.browsers: list[FakeBrowser] = []
        self.lookups: list[FakeServiceInfo] = []
        self.own_zeroconfs: list[FakeAsyncZeroconf] = []
        # Answers the lookups of these services have when they start
        self.known: dict[str, NetworkDevice] = {}
        # Errors the lookups of these services raise
        self.failing: dict[str, Exception] = {}

        def browser(zc: Zeroconf, type_: str, handlers: list[Handler]) -> FakeBrowser:
            self.browsers.append(FakeBrowser(zc, type_, handlers))
            return self.browsers[-1]

        def lookup(type_: str, name: str) -> FakeServiceInfo:
            if not name.endswith(f".{type_}"):
                # As zeroconf does for an alias of another type
                raise BadTypeInNameException(name)
            self.lookups.append(FakeServiceInfo(type_, name))
            if name in self.known:
                self.lookups[-1].describe(self.known[name])
            self.lookups[-1].error = self.failing.get(name)
            return self.lookups[-1]

        def own_zeroconf() -> FakeAsyncZeroconf:
            self.own_zeroconfs.append(FakeAsyncZeroconf())
            return self.own_zeroconfs[-1]

        for target, side_effect in (
            ("glocaltokens.scanner.AsyncServiceBrowser", browser),
            ("glocaltokens.scanner.AsyncServiceInfo", lookup),
            ("glocaltokens.scanner.AsyncZeroconf", own_zeroconf),
        ):
            patcher = patch(target, side_effect=side_effect)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.caller_zeroconf: Zeroconf = mock.NonCallableMock(name="Zeroconf")

    async def start(
        self,
        listen: float = 10,
        max_devices: int | None = None,
        zeroconf_instance: Zeroconf | None = None,
    ) -> asyncio.Task[list[NetworkDevice]]:
        """Start discovery for listen seconds, and wait until it browses."""
        task = asyncio.create_task(
            async_discover_devices(
                timeout=listen,
                max_devices=max_devices,
                zeroconf_instance=zeroconf_instance,
            )
        )
        await self.until(lambda: bool(self.browsers))
        return task

    @staticmethod
    async def until(condition: Callable[[], object]) -> None:
        """Let the event loop run until a condition holds."""
        for _ in range(100):
            if condition():
                return
            await asyncio.sleep(0)
        raise AssertionError("condition never held")

    async def change(self, name: str, state_change: ServiceStateChange) -> None:
        """Report a change, and let a lookup it starts begin."""
        count = len(self.lookups)
        self.browsers[0].change(name, state_change)
        if state_change is not ServiceStateChange.Removed:
            await self.until(lambda: len(self.lookups) > count)

    async def test_found_devices(self) -> None:
        """The wanted devices found, using the caller's Zeroconf without closing it."""
        speaker = network_device()
        group = network_device(model=GOOGLE_CAST_GROUP)
        task = await self.start(max_devices=1, zeroconf_instance=self.caller_zeroconf)
        assert self.browsers[0].zc is self.caller_zeroconf
        assert self.browsers[0].type == CAST_SERVICE
        await self.change(f"group.{CAST_SERVICE}", ServiceStateChange.Added)
        self.lookups[0].describe(group)
        await self.change(f"speaker.{CAST_SERVICE}", ServiceStateChange.Added)
        # A speaker group doesn't count towards max_devices: the speaker ends it
        assert not task.done()
        self.lookups[1].describe(speaker)
        assert await asyncio.wait_for(task, 5) == [speaker]
        # With 10 seconds left, each lookup gets zeroconf's usual 3000 ms
        assert self.lookups[1].requests == [
            (self.caller_zeroconf, SERVICE_INFO_TIMEOUT)
        ]
        assert self.browsers[0].cancelled.is_set()
        assert not self.caller_zeroconf.mock_calls  # type: ignore[attr-defined]
        assert not self.own_zeroconfs

    async def test_timeout(self) -> None:
        """Without enough devices, discovery ends at the timeout and closes its own Zeroconf."""
        speaker = network_device()
        task = await self.start(listen=0.3)
        await self.change(f"speaker.{CAST_SERVICE}", ServiceStateChange.Added)
        self.lookups[0].describe(speaker)
        await self.change(f"unanswered.{CAST_SERVICE}", ServiceStateChange.Added)
        assert await asyncio.wait_for(task, 5) == [speaker]
        assert self.lookups[1].task is not None
        assert self.lookups[1].task.cancelled()
        assert self.own_zeroconfs[0].closed

    async def test_removed_while_looking_up(self) -> None:
        """A lookup that ends after its service was removed adds nothing."""
        task = await self.start(listen=0.3)
        await self.change(f"speaker.{CAST_SERVICE}", ServiceStateChange.Added)
        lookup = self.lookups[0]
        lookup.on_cancel = "complete"
        await self.change(f"speaker.{CAST_SERVICE}", ServiceStateChange.Removed)
        await lookup.cancelled.wait()
        lookup.describe(network_device())
        lookup.finish_cleanup.set()
        assert await asyncio.wait_for(task, 5) == []

    async def test_removed_after_found(self) -> None:
        """A device whose service is removed isn't returned."""
        task = await self.start(listen=0.3)
        await self.change(f"speaker.{CAST_SERVICE}", ServiceStateChange.Added)
        self.lookups[0].describe(network_device())
        await self.until(lambda: self.lookups[0].task and self.lookups[0].task.done())
        await self.change(f"speaker.{CAST_SERVICE}", ServiceStateChange.Removed)
        assert await asyncio.wait_for(task, 5) == []

    async def test_later_update_kept(self) -> None:
        """An earlier lookup that ends after a later one doesn't replace its answer."""
        earlier, later = network_device(), network_device()
        task = await self.start(listen=0.3)
        await self.change(f"speaker.{CAST_SERVICE}", ServiceStateChange.Added)
        self.lookups[0].on_cancel = "complete"
        await self.change(f"speaker.{CAST_SERVICE}", ServiceStateChange.Updated)
        self.lookups[1].describe(later)
        await self.until(lambda: self.lookups[1].task and self.lookups[1].task.done())
        self.lookups[0].describe(earlier)
        self.lookups[0].finish_cleanup.set()
        assert await asyncio.wait_for(task, 5) == [later]

    async def test_waits_for_retired_lookups(self) -> None:
        """Discovery ends only once lookups it stopped have finished their cleanup.

        A second cancellation would cut that cleanup short, so a lookup that is
        already being cancelled isn't cancelled again.
        """
        for retire in (ServiceStateChange.Updated, ServiceStateChange.Removed):
            with self.subTest(retire=retire.name):
                self.browsers.clear()
                self.lookups.clear()
                speaker = network_device()
                task = await self.start(listen=0.3)
                await self.change(f"speaker.{CAST_SERVICE}", ServiceStateChange.Added)
                retired = self.lookups[0]
                retired.on_cancel = "hold"
                await self.change(f"speaker.{CAST_SERVICE}", retire)
                await retired.cancelled.wait()
                if retire is ServiceStateChange.Updated:
                    self.lookups[1].describe(speaker)

                # Past the timeout, discovery stops browsing, then waits
                await self.browsers[0].cancelled.wait()
                await asyncio.sleep(0.01)
                assert not task.done()
                assert not self.own_zeroconfs[-1].closed
                assert retired.task is not None
                assert not retired.task.done()
                assert retired.task.cancelling() == 1

                retired.finish_cleanup.set()
                devices = await asyncio.wait_for(task, 5)
                assert devices == (
                    [speaker] if retire is ServiceStateChange.Updated else []
                )
                assert all(
                    lookup.task is not None and lookup.task.done()
                    for lookup in self.lookups
                )
                assert self.own_zeroconfs[-1].closed

    async def test_cleanup_outlasts_repeated_cancellation(self) -> None:
        """Cancelling discovery while it waits for lookups to end doesn't cut them short.

        The cancellation is raised once they have finished their cleanup and
        the own Zeroconf is closed.
        """

        async def cancel_twice(task: asyncio.Task[list[NetworkDevice]]) -> None:
            # Cancelled while listening, then again while it waits for lookups
            task.cancel()
            await self.lookups[0].cancelled.wait()
            task.cancel()

        async def cancel_after_timeout(task: asyncio.Task[list[NetworkDevice]]) -> None:
            # A lookup that an update retired, then cancelled while it waits
            await self.change(f"speaker.{CAST_SERVICE}", ServiceStateChange.Updated)
            await self.lookups[0].cancelled.wait()
            await self.browsers[0].cancelled.wait()
            task.cancel()

        for cancel, listen in ((cancel_twice, 10.0), (cancel_after_timeout, 0.3)):
            with self.subTest(cancel=cancel.__name__):
                self.browsers.clear()
                self.lookups.clear()
                task = await self.start(listen=listen)
                await self.change(f"speaker.{CAST_SERVICE}", ServiceStateChange.Added)
                held = self.lookups[0]
                held.on_cancel = "hold"
                await cancel(task)
                await asyncio.sleep(0.01)
                assert not task.done()
                assert not self.own_zeroconfs[-1].closed
                assert held.task is not None
                assert not held.task.done()
                assert held.task.cancelling() == 1

                held.finish_cleanup.set()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 5)
                assert held.task.cancelled()
                assert self.own_zeroconfs[-1].closed

    async def test_close_outlasts_repeated_cancellation(self) -> None:
        """Cancelling discovery while it closes its own Zeroconf doesn't stop the closing.

        The cancellation is raised once the Zeroconf is closed.
        """
        task = await self.start()
        own = self.own_zeroconfs[0]
        own.hold_close = True
        task.cancel()
        await own.closing.wait()
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done()
        assert not own.closed

        own.release_close.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        assert own.closed

    async def test_close_error_raised(self) -> None:
        """An error closing the own Zeroconf reaches the caller, as before."""
        task = await self.start(listen=0.3)
        self.own_zeroconfs[0].close_error = OSError("Invented failure")
        with pytest.raises(OSError, match="Invented failure"):
            await asyncio.wait_for(task, 5)

    async def test_cancelled(self) -> None:
        """Cancelling discovery stops browsing and the lookups, and closes its own Zeroconf."""
        task = await self.start()
        await self.change(f"speaker.{CAST_SERVICE}", ServiceStateChange.Added)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert self.browsers[0].cancelled.is_set()
        assert self.lookups[0].task is not None
        assert self.lookups[0].task.cancelled()
        assert self.own_zeroconfs[0].closed

    async def test_eager_task_factory(self) -> None:
        """A lookup answered at once is kept, even if it runs as soon as it starts."""
        loop = asyncio.get_running_loop()
        loop.set_task_factory(asyncio.eager_task_factory)
        self.addCleanup(loop.set_task_factory, None)
        speaker = network_device()
        # As zeroconf answers a cached service, without waiting
        self.known[f"speaker.{CAST_SERVICE}"] = speaker
        task = await self.start(listen=0.3)
        self.browsers[0].change(f"speaker.{CAST_SERVICE}", ServiceStateChange.Added)
        assert await asyncio.wait_for(task, 5) == [speaker]

    async def test_lookup_errors(self) -> None:
        """Services that can't be looked up are left out, and their lookups end cleanly."""
        tasks: list[asyncio.Task[object]] = []
        create_task = asyncio.create_task

        def track(coro: Coroutine[object, object, object]) -> asyncio.Task[object]:
            tasks.append(create_task(coro))
            return tasks[-1]

        speaker = network_device()
        self.failing[f"unreachable.{CAST_SERVICE}"] = OSError("Invented failure")
        with patch("asyncio.create_task", side_effect=track):
            task = await self.start(listen=0.3)
            # zeroconf reports aliases of other types, which can't be looked up
            self.browsers[0].change(
                "alias._other._tcp.local.", ServiceStateChange.Added
            )
            await self.change(f"unreachable.{CAST_SERVICE}", ServiceStateChange.Added)
            await self.change(f"speaker.{CAST_SERVICE}", ServiceStateChange.Added)
            self.lookups[-1].describe(speaker)
            assert await asyncio.wait_for(task, 5) == [speaker]
        # No lookup ends with an error that nothing would retrieve
        lookups = [task for task in tasks if task.get_coro().__name__ == "look_up"]  # type: ignore[union-attr]
        assert len(lookups) == 3
        assert all(
            not task.cancelled() and task.exception() is None for task in lookups
        )

    async def test_subtype_ignored(self) -> None:
        """Cast subtype services aren't looked up."""
        task = await self.start(listen=0.3)
        self.browsers[0].change(
            "Living room._sub._googlecast._tcp.local.", ServiceStateChange.Added
        )
        await asyncio.sleep(0)
        assert not self.lookups
        assert await asyncio.wait_for(task, 5) == []


class AsyncRequestTests(IsolatedAsyncioTestCase):
    """How one service is looked up before the discovery deadline."""

    async def test_retries_while_time_remains(self) -> None:
        """A service that doesn't answer is asked again, at most four times."""
        zc = mock.NonCallableMock(name="Zeroconf")
        service = FakeServiceInfo(CAST_SERVICE, f"speaker.{CAST_SERVICE}")
        service.misses = 2
        service.describe(network_device())
        assert await _async_request(service, zc, time.monotonic() + 60)  # type: ignore[arg-type]
        assert service.requests == [(zc, SERVICE_INFO_TIMEOUT)] * 3

        service = FakeServiceInfo(CAST_SERVICE, f"speaker.{CAST_SERVICE}")
        service.misses = 4
        assert not await _async_request(service, zc, time.monotonic() + 60)  # type: ignore[arg-type]
        assert len(service.requests) == 4

    async def test_deadline(self) -> None:
        """Lookups end by the deadline, then only zeroconf's cache answers."""
        zc = mock.NonCallableMock(name="Zeroconf")
        service = FakeServiceInfo(CAST_SERVICE, f"speaker.{CAST_SERVICE}")
        service.describe(network_device())
        assert await _async_request(service, zc, time.monotonic() + 1)  # type: ignore[arg-type]
        assert 900 < service.requests[0][1] <= 1000

        cached = network_device()
        service = FakeServiceInfo(CAST_SERVICE, f"speaker.{CAST_SERVICE}")
        service.cached = cached
        assert await _async_request(service, zc, time.monotonic())  # type: ignore[arg-type]
        assert not service.requests
        assert service.properties[b"cd"] == cached.unique_id.encode()
