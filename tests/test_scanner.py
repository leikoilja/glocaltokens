"""Scanner specific tests."""

# pylint: disable=too-many-lines

from __future__ import annotations

import asyncio
import concurrent.futures
import gc
import importlib
import logging
import pickle
import sys
import threading
import time
from typing import TYPE_CHECKING, Protocol, override
from unittest import IsolatedAsyncioTestCase, TestCase, mock
from unittest.mock import NonCallableMock, patch
import warnings

from faker import Faker
from faker.providers import internet as internet_provider, python as python_provider
import pytest
from zeroconf import BadTypeInNameException, EventLoopBlocked, ServiceStateChange

from glocaltokens import types as glocaltokens_types
from glocaltokens.const import GOOGLE_CAST_GROUP, SERVICE_INFO_TIMEOUT
from glocaltokens.scanner import (
    LOGGER,
    CastListener,
    NetworkDevice,
    _async_request,
    async_discover_devices,
    discover_devices,
)
from tests import without_zeroconf

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine

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

    def test_unpickle_from_scanner(self) -> None:
        """A device pickled when NetworkDevice was defined in scanner still loads."""
        # pickle.dumps(NetworkDevice("Kitchen speaker", "192.0.2.10", 8009,
        # "Google Home", "invented-unique-id"), protocol=4) with glocaltokens
        # 1.2.0, which names the class glocaltokens.scanner.NetworkDevice
        data = (
            b"\x80\x04\x95t\x00\x00\x00\x00\x00\x00\x00\x8c\x14glocaltokens.scanner"
            b"\x94\x8c\rNetworkDevice\x94\x93\x94(\x8c\x0fKitchen speaker\x94\x8c\n"
            b"192.0.2.10\x94MI\x1f\x8c\x0bGoogle Home\x94\x8c\x12invented-unique-id"
            b"\x94t\x94\x81\x94."
        )
        device = pickle.loads(data)  # noqa: S301
        assert isinstance(device, glocaltokens_types.NetworkDevice)
        assert device == (
            "Kitchen speaker",
            "192.0.2.10",
            8009,
            "Google Home",
            "invented-unique-id",
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


class WithoutZeroconfTests(TestCase):
    """Importing the scanner without zeroconf."""

    def test_import(self) -> None:
        """Without the discovery extra, the error says how to install it."""
        with without_zeroconf(), pytest.raises(ModuleNotFoundError) as exc_info:
            importlib.import_module("glocaltokens.scanner")
        assert "glocaltokens[discovery]" in str(exc_info.value)
        assert exc_info.value.name == "zeroconf"
        assert isinstance(exc_info.value.__cause__, ModuleNotFoundError)

    def test_import_inside_zeroconf(self) -> None:
        """A module missing inside zeroconf isn't blamed on the extra."""
        with patch.dict(sys.modules, {"zeroconf.asyncio": None}):
            del sys.modules["glocaltokens.scanner"]
            with pytest.raises(ModuleNotFoundError) as exc_info:
                importlib.import_module("glocaltokens.scanner")
        assert exc_info.value.name == "zeroconf.asyncio"
        assert "glocaltokens[discovery]" not in str(exc_info.value)


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
    raise error if it is set. A lookup waits at most 10 seconds for the test.
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
            await self.wait_for_test(self.answer, "an answer or cancellation")
        except asyncio.CancelledError:
            self.cancelled.set()
            if self.on_cancel == "raise":
                raise
            await self.wait_for_test(self.finish_cleanup, "finish_cleanup")
            if self.on_cancel == "hold":
                raise
        return True

    async def wait_for_test(self, event: asyncio.Event, what: str) -> None:
        """Wait until the test sets event, and fail after 10 seconds.

        Discovery waits for every lookup to end, even when it is cancelled, so
        a lookup left waiting would hang the test instead of failing it. The
        tests' own waits are shorter, so they report what didn't happen.
        """
        try:
            await asyncio.wait_for(event.wait(), 10)
        except TimeoutError:
            # TimeoutError is an OSError, which discovery takes for a failed lookup
            msg = f"The lookup of {self.name} waited 10 seconds for {what}"
            raise AssertionError(msg) from None


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


class DiscoveryTestCase(IsolatedAsyncioTestCase):
    """Discovery with a fake browser and lookups, on this test's event loop."""

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
        caller_zeroconf = mock.NonCallableMock(name="Zeroconf")
        caller_zeroconf.loop = asyncio.get_running_loop()
        self.caller_zeroconf: Zeroconf = caller_zeroconf

    @staticmethod
    async def until(condition: Callable[[], object]) -> None:
        """Let the event loop run until a condition holds, for up to 5 seconds."""
        deadline = time.monotonic() + 5
        while not condition():
            if time.monotonic() > deadline:
                raise AssertionError("condition never held")
            await asyncio.sleep(0)

    async def change(self, name: str, state_change: ServiceStateChange) -> None:
        """Report a change, and let a lookup it starts begin."""
        count = len(self.lookups)
        self.browsers[0].change(name, state_change)
        if state_change is not ServiceStateChange.Removed:
            await self.until(lambda: len(self.lookups) > count)


class AsyncDiscoveryTests(DiscoveryTestCase):
    """async_discover_devices() with a fake browser and lookups."""

    async def start(
        self,
        listen: float = 10,
        max_devices: int | None = None,
        zeroconf_instance: Zeroconf | None = None,
        models: list[str] | None = None,
    ) -> asyncio.Task[list[NetworkDevice]]:
        """Start discovery for listen seconds, and wait until it browses."""
        task = asyncio.create_task(
            async_discover_devices(
                models=models,
                timeout=listen,
                max_devices=max_devices,
                zeroconf_instance=zeroconf_instance,
            )
        )
        await self.until(lambda: bool(self.browsers))
        return task

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

    async def test_models(self) -> None:
        """Only the models asked for are returned, and only they count towards max_devices."""
        mini = network_device(model="Google Home Mini")
        home = network_device(model="Google Home")
        task = await self.start(max_devices=1, models=["Google Home"])
        await self.change(f"mini.{CAST_SERVICE}", ServiceStateChange.Added)
        self.lookups[0].describe(mini)
        await self.until(lambda: self.lookups[0].task and self.lookups[0].task.done())
        assert not task.done()
        await self.change(f"home.{CAST_SERVICE}", ServiceStateChange.Added)
        self.lookups[1].describe(home)
        assert await asyncio.wait_for(task, 5) == [home]

    async def test_zeroconf_on_another_loop(self) -> None:
        """A Zeroconf running on another event loop is refused before browsing."""
        other_loop = asyncio.new_event_loop()
        self.addCleanup(other_loop.close)
        zeroconf_instance = mock.NonCallableMock(name="Zeroconf")
        zeroconf_instance.loop = other_loop
        with pytest.raises(ValueError, match="calling event loop"):
            await async_discover_devices(zeroconf_instance=zeroconf_instance)
        assert not self.browsers

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
        await asyncio.wait_for(lookup.cancelled.wait(), 5)
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
                await asyncio.wait_for(retired.cancelled.wait(), 5)
                if retire is ServiceStateChange.Updated:
                    self.lookups[1].describe(speaker)

                # Past the timeout, discovery stops browsing, then waits
                await asyncio.wait_for(self.browsers[0].cancelled.wait(), 5)
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
            await asyncio.wait_for(self.lookups[0].cancelled.wait(), 5)
            task.cancel()

        async def cancel_after_timeout(task: asyncio.Task[list[NetworkDevice]]) -> None:
            # A lookup that an update retired, then cancelled while it waits
            await self.change(f"speaker.{CAST_SERVICE}", ServiceStateChange.Updated)
            await asyncio.wait_for(self.lookups[0].cancelled.wait(), 5)
            await asyncio.wait_for(self.browsers[0].cancelled.wait(), 5)
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
        await asyncio.wait_for(own.closing.wait(), 5)
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done()
        assert not own.closed

        own.release_close.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        assert own.closed

    async def test_close_error_raised(self) -> None:
        """An error closing the own Zeroconf reaches the caller, unless it was cancelled."""
        task = await self.start(listen=0.3)
        self.own_zeroconfs[0].close_error = OSError("Invented failure")
        with pytest.raises(OSError, match="Invented failure"):
            await asyncio.wait_for(task, 5)

        # Cancelled while closing: the cancellation goes on, and the error is logged
        self.browsers.clear()
        task = await self.start()
        own = self.own_zeroconfs[-1]
        own.hold_close = True
        own.close_error = OSError("Invented failure")
        task.cancel()
        await asyncio.wait_for(own.closing.wait(), 5)
        task.cancel()
        with self.assertLogs(LOGGER, logging.DEBUG) as logs:
            own.release_close.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
        assert any("Invented failure" in message for message in logs.output)

    async def test_cancelled(self) -> None:
        """Cancelling discovery stops browsing and the lookups, and closes its own Zeroconf."""
        task = await self.start()
        await self.change(f"speaker.{CAST_SERVICE}", ServiceStateChange.Added)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
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


# Lowered from zeroconf's 10 seconds, to keep stalled-loop tests short
ALLOWANCE = 0.2

# What discover_devices() returns or raises in another thread
type Outcome = concurrent.futures.Future[list[NetworkDevice]]


class DiscoverDevicesTests(DiscoveryTestCase):
    """discover_devices() from another thread, as an executor runs it.

    The supplied Zeroconf, and the own one discovery creates, run on this
    test's event loop, so discovery runs there with the fakes.
    """

    @override
    async def asyncSetUp(self) -> None:
        """Also replace the Zeroconf that discover_devices() creates."""
        await super().asyncSetUp()
        patcher = patch("glocaltokens.scanner.Zeroconf")
        self.own_zeroconf = patcher.start()
        self.addCleanup(patcher.stop)
        self.own_zeroconf.return_value.loop = asyncio.get_running_loop()

    @staticmethod
    def discover(**options: object) -> Outcome:
        """Run discover_devices() in another thread, and return its outcome."""
        outcome: Outcome = concurrent.futures.Future()

        def run() -> None:
            try:
                outcome.set_result(discover_devices(**options))  # type: ignore[arg-type]
            except BaseException as error:  # noqa: BLE001  # pylint: disable=broad-exception-caught
                outcome.set_exception(error)

        # A daemon thread can't keep the tests from ending if discovery hangs
        threading.Thread(target=run, daemon=True).start()
        return outcome

    async def run_both(
        self,
        scenario: Callable[[], Awaitable[list[NetworkDevice]]],
        listen: float,
        models: list[str] | None = None,
        max_devices: int | None = None,
    ) -> None:
        """Run a scenario through both discovery functions, with fresh services each time.

        The scenario reports and answers services, and returns the devices
        discovery should find.
        """
        runs: dict[str, Callable[[], Awaitable[list[NetworkDevice]]]] = {
            "async_discover_devices": lambda: asyncio.ensure_future(
                async_discover_devices(
                    models=models, max_devices=max_devices, timeout=listen
                )
            ),
            "discover_devices": lambda: asyncio.wrap_future(
                self.discover(
                    models_list=models, max_devices=max_devices, timeout=listen
                )
            ),
        }
        for name, start in runs.items():
            with self.subTest(name):
                self.browsers.clear()
                self.lookups.clear()
                self.failing.clear()
                discovery = start()
                await self.until(lambda: bool(self.browsers))
                expected = await scenario()
                assert await asyncio.wait_for(discovery, 5) == expected
                # No lookup outlives discovery
                assert all(
                    lookup.task is not None and lookup.task.done()
                    for lookup in self.lookups
                )
        self.own_zeroconf.assert_called_once_with(use_asyncio=False)
        self.own_zeroconf.return_value.close.assert_called_once_with()

    async def report_until_timeout(self) -> list[NetworkDevice]:
        """Report services of every kind, one at a time, without enough to stop early."""
        speaker, group = network_device(), network_device(GOOGLE_CAST_GROUP)
        earlier, later = network_device(), network_device()
        self.failing[f"failing.{CAST_SERVICE}"] = OSError("Invented failure")

        await self.change(f"speaker.{CAST_SERVICE}", ServiceStateChange.Added)
        self.lookups[-1].describe(speaker)
        await self.change(f"group.{CAST_SERVICE}", ServiceStateChange.Added)
        self.lookups[-1].describe(group)
        self.browsers[0].change(
            f"Living room._sub.{CAST_SERVICE}", ServiceStateChange.Added
        )
        await self.change(f"unanswered.{CAST_SERVICE}", ServiceStateChange.Added)
        await self.change(f"failing.{CAST_SERVICE}", ServiceStateChange.Added)

        await self.change(f"removed.{CAST_SERVICE}", ServiceStateChange.Added)
        found = self.lookups[-1]
        found.describe(network_device())
        await self.until(lambda: found.task is not None and found.task.done())
        await self.change(f"removed.{CAST_SERVICE}", ServiceStateChange.Removed)

        await self.change(f"updated.{CAST_SERVICE}", ServiceStateChange.Added)
        first = self.lookups[-1]
        first.on_cancel = "complete"
        await self.change(f"updated.{CAST_SERVICE}", ServiceStateChange.Updated)
        second = self.lookups[-1]
        second.describe(later)
        await self.until(lambda: second.task is not None and second.task.done())
        # The earlier lookup answers last, and its answer isn't kept
        first.describe(earlier)
        first.finish_cleanup.set()

        assert not [lookup for lookup in self.lookups if "._sub." in lookup.name]
        # The group is found but not returned
        return [speaker, later]

    async def report_until_enough(self) -> list[NetworkDevice]:
        """Report a model not asked for, then one asked for that is usable once updated."""
        mini = network_device(model="Google Home Mini")
        home = network_device(model="Google Home")

        await self.change(f"mini.{CAST_SERVICE}", ServiceStateChange.Added)
        self.lookups[-1].describe(mini)
        await self.change(f"home.{CAST_SERVICE}", ServiceStateChange.Added)
        # Only a link-local IPv6 address, which can't be used
        first = self.lookups[-1]
        first.describe(home._replace(ip_address="fe80::1"))
        await self.until(lambda: first.task is not None and first.task.done())
        # zeroconf reports an update when an IPv4 address arrives
        await self.change(f"home.{CAST_SERVICE}", ServiceStateChange.Updated)
        self.lookups[-1].describe(home)
        return [home]

    async def test_same_devices_as_async(self) -> None:
        """discover_devices() finds what async_discover_devices() finds, in the same way."""
        await self.run_both(self.report_until_timeout, listen=0.5)

    async def test_stops_when_enough_found(self) -> None:
        """Both stop before the timeout once enough wanted devices are found.

        A model not asked for doesn't count, and a device first usable on an
        update does. Not stopping would exceed the 5-second wait for discovery.
        """
        await self.run_both(
            self.report_until_enough,
            listen=10,
            models=["Google Home"],
            max_devices=1,
        )

    async def test_lookups_overlap(self) -> None:
        """Lookups run at the same time, each asked for at most the time left.

        No lookup answers until all four have been asked. Looked up one after
        another, the first would wait until the timeout, and the rest would
        never be asked.
        """
        devices = [network_device() for _ in range(4)]
        outcome = self.discover(
            max_devices=4, timeout=2, zeroconf_instance=self.caller_zeroconf
        )
        await self.until(lambda: bool(self.browsers))
        for index in range(4):
            await self.change(
                f"speaker{index}.{CAST_SERVICE}", ServiceStateChange.Added
            )
        await self.until(lambda: all(lookup.requests for lookup in self.lookups))
        assert not any(lookup.answer.is_set() for lookup in self.lookups)

        for lookup, device in zip(self.lookups, devices, strict=True):
            lookup.describe(device)
        found = await asyncio.wait_for(asyncio.wrap_future(outcome), 5)
        assert sorted(found) == sorted(devices)
        assert all(
            0 < timeout <= 2000
            for lookup in self.lookups
            for _, timeout in lookup.requests
        )
        assert not self.caller_zeroconf.mock_calls  # type: ignore[attr-defined]
        self.own_zeroconf.assert_not_called()

    async def test_error(self) -> None:
        """An error from discovery is raised once the own Zeroconf is closed."""
        with patch(
            "glocaltokens.scanner.AsyncServiceBrowser",
            side_effect=OSError("No network"),
        ):
            outcome = self.discover(timeout=10)
            with pytest.raises(OSError, match="No network"):
                await asyncio.wait_for(asyncio.wrap_future(outcome), 5)
        self.own_zeroconf.return_value.close.assert_called_once_with()

    async def test_keeps_application_log_level(self) -> None:
        """Discovery leaves the level to the application."""
        package_logger = logging.getLogger("glocaltokens")
        package_logger.setLevel(logging.CRITICAL)
        self.addCleanup(package_logger.setLevel, logging.NOTSET)
        await asyncio.wait_for(asyncio.wrap_future(self.discover(timeout=0)), 5)
        package_logger.setLevel(logging.DEBUG)
        assert LOGGER.level == logging.NOTSET
        assert LOGGER.getEffectiveLevel() == logging.DEBUG

        with pytest.warns(DeprecationWarning, match="logging_level is deprecated"):
            await asyncio.wait_for(
                asyncio.wrap_future(
                    self.discover(timeout=0, logging_level=logging.ERROR)
                ),
                5,
            )
        assert LOGGER.level == logging.NOTSET

    @patch("glocaltokens.scanner._LOOP_ALLOWANCE", ALLOWANCE)
    async def test_stalled_loop(self) -> None:
        """A stalled loop gets EventLoopBlocked once the allowance has passed.

        Discovery, frozen with the loop, stops when the loop runs again.
        """
        started = time.monotonic()
        outcome = self.discover(zeroconf_instance=self.caller_zeroconf, timeout=0.2)
        await self.until(lambda: bool(self.browsers))
        await self.change(f"speaker.{CAST_SERVICE}", ServiceStateChange.Added)
        # Blocks this test's loop until the call has raised
        error = outcome.exception(timeout=5)
        assert isinstance(error, EventLoopBlocked)
        assert time.monotonic() - started >= 0.2 + ALLOWANCE
        assert not self.caller_zeroconf.mock_calls  # type: ignore[attr-defined]

        await asyncio.wait_for(self.browsers[0].cancelled.wait(), 5)
        await self.until(lambda: asyncio.all_tasks() == {asyncio.current_task()})
        assert self.lookups[0].task is not None
        assert self.lookups[0].task.cancelled()

    @patch("glocaltokens.scanner._LOOP_ALLOWANCE", ALLOWANCE)
    async def test_stalled_before_discovery(self) -> None:
        """Discovery that a stalled loop starts only after the call has raised doesn't browse."""
        # Blocks this test's loop from before the call until it has raised
        outcome = self.discover(zeroconf_instance=self.caller_zeroconf, timeout=0.2)
        assert isinstance(outcome.exception(timeout=5), EventLoopBlocked)
        await asyncio.sleep(0.05)
        assert not self.browsers
        assert asyncio.all_tasks() == {asyncio.current_task()}

    async def test_gives_up_on_running_discovery(self) -> None:
        """Discovery still running when the call raises EventLoopBlocked stops at once.

        It doesn't go on until its own timeout. That happens when a slow loop
        starts discovery late and the call then gives up waiting for it.
        """
        give_up = threading.Event()

        def wait_given_up(futures: list[Outcome], _timeout: float) -> object:
            give_up.wait(5)
            return set(), set(futures)

        with patch("concurrent.futures.wait", side_effect=wait_given_up):
            outcome = self.discover(zeroconf_instance=self.caller_zeroconf, timeout=10)
            await self.until(lambda: bool(self.browsers))
            await self.change(f"speaker.{CAST_SERVICE}", ServiceStateChange.Added)
            give_up.set()
            await self.until(outcome.done)
        assert isinstance(outcome.exception(), EventLoopBlocked)
        await asyncio.wait_for(self.browsers[0].cancelled.wait(), 5)
        await self.until(lambda: asyncio.all_tasks() == {asyncio.current_task()})
        assert self.lookups[0].task is not None
        assert self.lookups[0].task.cancelled()

    async def test_cancelled_on_loop(self) -> None:
        """Discovery that its loop cancels, as when the loop shuts down, raises CancelledError."""
        outcome = self.discover(zeroconf_instance=self.caller_zeroconf, timeout=10)
        await self.until(lambda: bool(self.browsers))
        for task in asyncio.all_tasks() - {asyncio.current_task()}:
            task.cancel()
        await self.until(outcome.done)
        assert isinstance(outcome.exception(), concurrent.futures.CancelledError)
        assert self.browsers[0].cancelled.is_set()

    async def test_interrupted(self) -> None:
        """An interrupted wait stops discovery, and is raised once discovery has stopped."""
        interrupt = threading.Event()
        wait = concurrent.futures.wait
        waits: list[float] = []

        def wait_interrupted(futures: list[Outcome], timeout: float) -> object:
            waits.append(timeout)
            if len(waits) == 1:
                interrupt.wait(5)
                raise KeyboardInterrupt
            return wait(futures, timeout)

        with patch("concurrent.futures.wait", side_effect=wait_interrupted):
            outcome = self.discover(timeout=10)
            await self.until(lambda: bool(self.browsers))
            await self.change(f"speaker.{CAST_SERVICE}", ServiceStateChange.Added)
            held = self.lookups[0]
            held.on_cancel = "hold"
            # Teardown would otherwise wait 10 seconds on a lookup left uncancelled
            self.addCleanup(held.finish_cleanup.set)
            interrupt.set()
            await asyncio.wait_for(held.cancelled.wait(), 5)
            await asyncio.sleep(0.01)
            assert not outcome.done()
            self.own_zeroconf.return_value.close.assert_not_called()

            held.finish_cleanup.set()
            await self.until(outcome.done)
        assert isinstance(outcome.exception(), KeyboardInterrupt)
        assert self.browsers[0].cancelled.is_set()
        self.own_zeroconf.return_value.close.assert_called_once_with()

    @patch("glocaltokens.scanner._LOOP_ALLOWANCE", ALLOWANCE)
    async def test_interrupted_while_stalled(self) -> None:
        """An interrupted wait on a stalled loop is raised once the allowance has passed."""
        wait = concurrent.futures.wait
        waits: list[float] = []

        def wait_interrupted(futures: list[Outcome], timeout: float) -> object:
            waits.append(timeout)
            if len(waits) == 1:
                raise KeyboardInterrupt
            return wait(futures, timeout)

        with patch("concurrent.futures.wait", side_effect=wait_interrupted):
            # Blocks this test's loop from before the call until it has raised
            outcome = self.discover(zeroconf_instance=self.caller_zeroconf, timeout=10)
            assert isinstance(outcome.exception(timeout=5), KeyboardInterrupt)
        assert waits == [10 + ALLOWANCE, ALLOWANCE]
        await asyncio.sleep(0.05)
        assert not self.browsers
        assert not self.caller_zeroconf.mock_calls  # type: ignore[attr-defined]

    async def test_zeroconf_on_this_loop(self) -> None:
        """A Zeroconf on the calling thread's event loop is refused, as the call would block it."""
        with pytest.raises(RuntimeError, match="this thread's event loop"):
            discover_devices(zeroconf_instance=self.caller_zeroconf)
        assert not self.browsers
        assert not self.caller_zeroconf.mock_calls  # type: ignore[attr-defined]
        self.own_zeroconf.assert_not_called()

    async def test_loop_not_running(self) -> None:
        """A Zeroconf whose loop isn't running is refused, as zeroconf's ServiceBrowser does."""
        loop = asyncio.new_event_loop()
        self.addCleanup(loop.close)
        zeroconf_instance = NonCallableMock(name="Zeroconf", loop=loop)
        with pytest.raises(RuntimeError, match="The event loop is not running"):
            discover_devices(zeroconf_instance=zeroconf_instance)
        assert not self.browsers

    async def test_loop_closed_before_discovery(self) -> None:
        """A loop that closes as discovery is submitted refuses it, leaving nothing unawaited."""
        loop = asyncio.new_event_loop()
        loop.close()
        zeroconf_instance = NonCallableMock(name="Zeroconf", loop=loop)
        with (
            patch.object(loop, "is_running", return_value=True),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter("always")
            with pytest.raises(RuntimeError, match="Event loop is closed"):
                discover_devices(zeroconf_instance=zeroconf_instance)
            gc.collect()
        assert not caught

    @patch("glocaltokens.scanner._LOOP_ALLOWANCE", ALLOWANCE)
    async def test_loop_closed_during_discovery(self) -> None:
        """A loop closed before it runs discovery gives EventLoopBlocked, not RuntimeError."""
        loop = asyncio.new_event_loop()
        blocking, submitted = threading.Event(), threading.Event()

        def block() -> None:
            blocking.set()
            submitted.wait(5)
            # Stops before running discovery, which was submitted meanwhile
            loop.stop()

        submit = asyncio.run_coroutine_threadsafe

        def submit_and_tell(
            coro: Coroutine[object, object, object], loop: asyncio.AbstractEventLoop
        ) -> concurrent.futures.Future[object]:
            future = submit(coro, loop)
            submitted.set()
            return future

        loop.call_soon(block)
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        blocking.wait(5)
        # Not a mock, which would keep the coroutine it is called with
        with patch("asyncio.run_coroutine_threadsafe", submit_and_tell):
            outcome = self.discover(
                zeroconf_instance=NonCallableMock(name="Zeroconf", loop=loop),
                timeout=0.2,
            )
            thread.join(5)
        # As asyncio warns of any coroutine that a closed loop never ran
        with pytest.warns(RuntimeWarning, match="never awaited"):
            loop.close()
        with pytest.raises(EventLoopBlocked):
            await asyncio.wait_for(asyncio.wrap_future(outcome), 5)

    async def test_from_thread_with_event_loop(self) -> None:
        """Called on a thread that runs an event loop, discovery runs on another one.

        That is the own Zeroconf's loop, or the loop of a supplied Zeroconf.
        """
        other_loop = asyncio.new_event_loop()
        running = threading.Event()
        other_loop.call_soon(running.set)
        thread = threading.Thread(target=other_loop.run_forever, daemon=True)
        thread.start()
        self.addCleanup(other_loop.close)
        self.addCleanup(thread.join, 5)
        self.addCleanup(other_loop.call_soon_threadsafe, other_loop.stop)
        running.wait(5)

        # Called on this test's loop, which waits meanwhile
        supplied = NonCallableMock(name="Zeroconf", loop=other_loop)
        assert discover_devices(zeroconf_instance=supplied, timeout=0) == []
        assert self.browsers[0].zc is supplied
        self.own_zeroconf.return_value.loop = other_loop
        assert discover_devices(timeout=0) == []
        assert self.browsers[1].zc is self.own_zeroconf.return_value
        self.own_zeroconf.assert_called_once_with(use_asyncio=False)


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
