"""Zeroconf based scanner."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import ipaddress
import logging
from threading import Event
import time
from typing import TYPE_CHECKING, override
import warnings

from .const import DISCOVERY_TIMEOUT, GOOGLE_CAST_GROUP, SERVICE_INFO_TIMEOUT

# Re-exported for code that imports it from here: "as NetworkDevice" marks it
# public for type checkers
from .types import NetworkDevice as NetworkDevice  # noqa: PLC0414  # pylint: disable=useless-import-alias

try:
    from zeroconf import (
        Error as ZeroconfError,
        EventLoopBlocked,
        ServiceInfo,
        ServiceListener,
        ServiceStateChange,
        Zeroconf,
    )
    from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf
except ModuleNotFoundError as error:
    # Only a missing zeroconf means the extra isn't installed: let other
    # errors, such as one inside zeroconf, through as they are
    if error.name != "zeroconf":
        raise
    raise ModuleNotFoundError(
        "Discovering devices needs zeroconf: install glocaltokens[discovery], "
        "or turn discovery off in the device methods with disable_discovery=True "
        "(discover=False in the async methods)",
        name="zeroconf",
    ) from error

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Coroutine, Iterable

LOGGER = logging.getLogger(__name__)

# How much longer than its timeout discover_devices() waits for discovery on
# the Zeroconf's event loop, in seconds, as zeroconf's own blocking calls do
_LOOP_ALLOWANCE = 10


def _is_reachable(address: str) -> bool:
    """Whether a discovered address can be used to reach the device.

    A link-local IPv6 address can't be, as it only works with its interface,
    which zeroconf's parsed_addresses() leaves out.
    """
    ip = ipaddress.ip_address(address)
    return ip.version == 4 or not ip.is_link_local


class CastListener(ServiceListener):
    """Zeroconf Cast Services collection.

    Discovery no longer uses it; it is kept for code that does.

    Credit (pychromecast):
    https://github.com/home-assistant-libs/pychromecast/.
    """

    def __init__(
        self,
        add_callback: Callable[[], None] | None = None,
        deadline: float | None = None,
    ):
        """Create cast listener.

        add_callback: called after a service is added or updated.
        deadline: time.monotonic() value after which service lookups stop.
        """
        self.devices: dict[str, NetworkDevice] = {}
        self.deadline = deadline
        self.add_callback = add_callback

    @property
    def count(self) -> int:
        """Number of discovered cast services."""
        return len(self.devices)

    @override
    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Add a service to the collection."""
        LOGGER.debug("add_service %s, %s", type_, name)
        self._add_update_service(zc, type_, name)

    @override
    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Update a service in the collection."""
        LOGGER.debug("update_service %s, %s", type_, name)
        self._add_update_service(zc, type_, name)

    @override
    def remove_service(self, _zc: Zeroconf, type_: str, name: str) -> None:
        """Remove a cast device when its mDNS info expires or the host is down."""
        LOGGER.debug("remove_service %s, %s", type_, name)
        if name in self.devices:
            del self.devices[name]

    def _add_update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Add or update a service."""
        if name.endswith("_sub._googlecast._tcp.local."):
            LOGGER.debug("_add_update_service ignoring %s, %s", type_, name)
            return
        service = None
        tries = 0
        while service is None and tries < 4:
            lookup_timeout = SERVICE_INFO_TIMEOUT
            if self.deadline is not None:
                lookup_timeout = min(
                    lookup_timeout, int((self.deadline - time.monotonic()) * 1000)
                )
                if lookup_timeout <= 0:
                    # Out of time: still use details zeroconf already has.
                    cached = ServiceInfo(type_, name)
                    if cached.load_from_cache(zc):
                        service = cached
                    break
            try:
                service = zc.get_service_info(type_, name, timeout=lookup_timeout)
            except OSError:
                # If the zeroconf fails to receive the necessary data we abort
                # adding the service
                break
            tries += 1

        if not service:
            LOGGER.debug("_add_update_service failed to add %s, %s", type_, name)
            return

        device = _network_device(service, name)
        if device is None:
            return
        self.devices[name] = device

        if self.add_callback:
            self.add_callback()

    @staticmethod
    def get_service_value(service: ServiceInfo, key: str) -> str | None:
        """Retrieve value and decode to UTF-8."""
        value: str | bytes | None = service.properties.get(key.encode("utf-8"))

        if value is None or isinstance(value, str):
            return value
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            LOGGER.debug("Service %s has an invalid %s value", service.name, key)
            return None


def _network_device(service: ServiceInfo, name: str) -> NetworkDevice | None:
    """Return the device a looked-up Cast service describes, if it is usable."""
    # zeroconf lists IPv4 addresses first
    ip_address = next(filter(_is_reachable, service.parsed_addresses()), None)

    model_name = CastListener.get_service_value(service, "md")
    friendly_name = CastListener.get_service_value(service, "fn")
    unique_id = CastListener.get_service_value(service, "cd")

    if not model_name or not friendly_name or not service.port or not unique_id:
        LOGGER.debug(
            "Discovered device %s has incomplete service info, skipping...",
            name,
        )
        return None

    if ip_address is None:
        LOGGER.debug(
            "Discovered device %s has no reachable IP address, skipping...", name
        )
        return None

    if not 0 <= service.port <= 65535:
        LOGGER.error("Port of discovered device is out of the valid range: [0,65535]")
        return None

    return NetworkDevice(
        name=friendly_name,
        ip_address=ip_address,
        port=service.port,
        model=model_name,
        unique_id=unique_id,
    )


def discover_devices(
    models_list: list[str] | None = None,
    max_devices: int | None = None,
    timeout: int = DISCOVERY_TIMEOUT,
    zeroconf_instance: Zeroconf | None = None,
    logging_level: int | None = None,
) -> list[NetworkDevice]:
    """Discover devices.

    Discovery runs on the event loop of zeroconf_instance, or of a Zeroconf
    created and closed for the call, while this thread waits. So
    zeroconf_instance can't run on this thread's event loop: RuntimeError is
    then raised before discovery, as it is if its loop isn't running. Use
    async_discover_devices() there, or run this call in an executor.

    If the loop of zeroconf_instance stalls, zeroconf's EventLoopBlocked is
    raised 10 seconds after the timeout, and discovery stops once the loop
    runs again. If that loop cancels discovery, for example as it shuts down,
    concurrent.futures.CancelledError is raised.
    """
    if logging_level is not None:
        warnings.warn(
            "logging_level is deprecated and ignored, set the level of the "
            "glocaltokens logger in your application instead",
            DeprecationWarning,
            stacklevel=2,
        )
    _check_sync_loop(zeroconf_instance)

    LOGGER.debug("Discovering devices...")
    if not zeroconf_instance:
        LOGGER.debug("Creating new Zeroconf instance")
        # On zeroconf's own loop thread, even if this thread runs a loop
        zc = Zeroconf(use_asyncio=False)
    else:
        LOGGER.debug("Using attribute Zeroconf instance")
        zc = zeroconf_instance
    try:
        return _discover_on_loop(zc, models_list, max_devices, timeout)
    finally:
        # A supplied instance belongs to the caller, who may still be using it.
        if not zeroconf_instance:
            zc.close()


def _discover_on_loop(
    zc: Zeroconf,
    models: list[str] | None,
    max_devices: int | None,
    timeout: float,
) -> list[NetworkDevice]:
    """Run discovery on the event loop of zc, and wait for it in this thread.

    If the loop stalls, raise EventLoopBlocked once the timeout and
    _LOOP_ALLOWANCE have passed, without waiting for discovery to stop: it
    stops when the loop runs again, and if it hasn't started by then, it
    doesn't browse. If the wait is interrupted, discovery is stopped and
    given up to _LOOP_ALLOWANCE to finish, then the interruption is raised.
    """
    loop = zc.loop
    if loop is None or not loop.is_running():
        # As zeroconf's ServiceBrowser
        msg = "The event loop is not running"
        raise RuntimeError(msg)
    abandoned = Event()
    discovery_complete = asyncio.Event()

    async def search() -> list[NetworkDevice]:
        if abandoned.is_set():
            return []
        return await _discover(zc, models, max_devices, timeout, discovery_complete)

    def abandon() -> None:
        abandoned.set()
        # A closed loop runs nothing more, so has no discovery to stop
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(discovery_complete.set)

    future = _submit(search(), loop)
    try:
        done, _ = concurrent.futures.wait([future], timeout + _LOOP_ALLOWANCE)
    except BaseException:
        abandon()
        concurrent.futures.wait([future], _LOOP_ALLOWANCE)
        raise
    if not done:
        abandon()
        msg = (
            f"Discovery didn't end {_LOOP_ALLOWANCE} seconds after its timeout: "
            "the Zeroconf's event loop is blocked or stopped. Discovery stops "
            "once the loop runs again"
        )
        raise EventLoopBlocked(msg)
    return future.result()


def _submit(
    coro: Coroutine[object, object, list[NetworkDevice]],
    loop: asyncio.AbstractEventLoop,
) -> concurrent.futures.Future[list[NetworkDevice]]:
    """Run a coroutine on another thread's event loop.

    If the loop has closed meanwhile, close the coroutine, which then never
    runs, and raise RuntimeError. Otherwise only the loop keeps it.
    """
    try:
        return asyncio.run_coroutine_threadsafe(coro, loop)
    except RuntimeError:
        coro.close()
        raise


async def async_discover_devices(
    *,
    models: list[str] | None = None,
    max_devices: int | None = None,
    # How long to listen, as in discover_devices(), not a limit on the call
    timeout: float = DISCOVERY_TIMEOUT,  # noqa: ASYNC109
    zeroconf_instance: Zeroconf | None = None,
) -> list[NetworkDevice]:
    """Discover devices without blocking the event loop, as discover_devices().

    The options are those of discover_devices(), by name only, with models for
    models_list and no logging_level. zeroconf_instance must run on the calling
    event loop, as Home Assistant's shared instance does, or ValueError is
    raised. Without one, an AsyncZeroconf is created and closed.
    """
    _check_loop(zeroconf_instance)
    LOGGER.debug("Discovering devices...")
    own_zeroconf: AsyncZeroconf | None = None
    if zeroconf_instance is None:
        LOGGER.debug("Creating new Zeroconf instance")
        own_zeroconf = AsyncZeroconf()
        zc = own_zeroconf.zeroconf
    else:
        zc = zeroconf_instance
    try:
        return await _discover(zc, models, max_devices, timeout, asyncio.Event())
    finally:
        # A supplied instance belongs to the caller, who may still be using it.
        if own_zeroconf is not None:
            await _close(own_zeroconf)


async def _discover(
    zc: Zeroconf,
    models: list[str] | None,
    max_devices: int | None,
    listen: float,
    discovery_complete: asyncio.Event,
) -> list[NetworkDevice]:
    """Discover devices with zc, which runs on this event loop.

    Discovery ends after listening for listen seconds, once enough devices are
    found, or when discovery_complete is set.
    """
    deadline = time.monotonic() + listen
    devices: dict[str, NetworkDevice] = {}
    # How many changes each service has had: only a lookup started for the
    # latest one may keep its answer
    changes: dict[str, int] = {}
    # The latest lookup of each service, to cancel when the service changes
    owners: dict[str, asyncio.Task[None]] = {}
    # Every lookup that hasn't finished, including ones whose answer is no
    # longer kept, so that none outlives discovery
    pending: set[asyncio.Task[None]] = set()

    async def look_up(zc: Zeroconf, type_: str, name: str, change: int) -> None:
        try:
            service = AsyncServiceInfo(type_, name)
            found = await _async_request(service, zc, deadline)
        except (OSError, ZeroconfError):
            # Give up on this service
            LOGGER.debug("Failed to look up %s, %s", type_, name, exc_info=True)
            return
        # A later update or removal of the service replaced this lookup
        if changes[name] != change:
            return
        device = _network_device(service, name) if found else None
        if device is None:
            LOGGER.debug("Discovery failed to add %s, %s", type_, name)
            return
        devices[name] = device
        if _found_enough(devices.values(), models, max_devices):
            discovery_complete.set()

    def on_change(
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        LOGGER.debug("%s %s, %s", state_change.name, service_type, name)
        change = changes[name] = changes.get(name, 0) + 1
        if owner := owners.pop(name, None):
            _cancel_once(owner)
        if state_change is ServiceStateChange.Removed:
            devices.pop(name, None)
            return
        if name.endswith("_sub._googlecast._tcp.local."):
            return
        # An eager task factory can run the lookup before this returns
        task = asyncio.create_task(look_up(zeroconf, service_type, name, change))
        owners[name] = task
        pending.add(task)
        task.add_done_callback(pending.discard)

    browser = AsyncServiceBrowser(zc, "_googlecast._tcp.local.", handlers=[on_change])
    try:
        # Wait for the timeout or the maximum number of devices
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(discovery_complete.wait(), listen)
    finally:
        await browser.async_cancel()
        for task in pending:
            _cancel_once(task)
        # Every lookup finishes its cleanup before the own Zeroconf closes
        # or discovery ends, even if discovery is cancelled meanwhile
        await _finish(pending)

    return _wanted_devices(devices.values(), models)


def _check_loop(zeroconf_instance: Zeroconf | None) -> None:
    """Raise ValueError if the caller's Zeroconf runs on another event loop.

    It would call discovery back on its own loop's thread, so discovery would
    start, cancel and wait for its lookups, and change its state, from two
    threads at once, which asyncio doesn't support.
    """
    if (
        zeroconf_instance is not None
        and zeroconf_instance.loop is not asyncio.get_running_loop()
    ):
        msg = "zeroconf_instance must run on the calling event loop"
        raise ValueError(msg)


def _check_sync_loop(zeroconf_instance: Zeroconf | None) -> None:
    """Raise RuntimeError if discovery can't run on the loop of the caller's Zeroconf.

    Discovery runs on that loop, so it must be running, and must not be this
    thread's, which a blocking call blocks.
    """
    if zeroconf_instance is None:
        return
    if zeroconf_instance.loop is None or not zeroconf_instance.loop.is_running():
        # As zeroconf's ServiceBrowser
        msg = "The event loop is not running"
        raise RuntimeError(msg)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if zeroconf_instance.loop is loop:
        msg = (
            "zeroconf_instance runs on this thread's event loop, which a "
            "blocking call would block: use the async version, or run this "
            "call in an executor"
        )
        raise RuntimeError(msg)


async def _async_request(
    service: AsyncServiceInfo, zc: Zeroconf, deadline: float
) -> bool:
    """Look a service up until the deadline, as CastListener does."""
    for _ in range(4):
        lookup_timeout = min(
            SERVICE_INFO_TIMEOUT, int((deadline - time.monotonic()) * 1000)
        )
        if lookup_timeout <= 0:
            # Out of time: still use details zeroconf already has.
            return service.load_from_cache(zc)
        if await service.async_request(zc, lookup_timeout):
            return True
    return False


async def _close(zeroconf: AsyncZeroconf) -> None:
    """Close an own Zeroconf, finishing even if the caller is cancelled meanwhile.

    A cancellation is raised once it has closed, and an error from closing is
    then only logged. Otherwise an error from closing is raised.
    """
    closing = asyncio.create_task(zeroconf.async_close())
    try:
        await _finish({closing})
    except asyncio.CancelledError:
        if not closing.cancelled() and (error := closing.exception()):
            LOGGER.debug("Failed to close the own Zeroconf: %s", error)
        raise
    closing.result()


async def _finish(tasks: set[asyncio.Task[None]]) -> None:
    """Wait until every task has finished, then raise any cancellation of the wait.

    Unlike asyncio.gather(), cancelling the wait doesn't cancel the tasks again,
    which would cut their cleanup short.
    """
    cancelled: asyncio.CancelledError | None = None
    while unfinished := [task for task in tasks if not task.done()]:
        try:
            await asyncio.wait(unfinished)
        except asyncio.CancelledError as error:
            cancelled = error
    if cancelled is not None:
        raise cancelled


def _cancel_once(task: asyncio.Task[None]) -> None:
    """Cancel a task, unless it has finished or is being cancelled.

    Cancelling again would interrupt the cleanup of the first cancellation.
    """
    if not task.done() and task.cancelling() == 0:
        task.cancel()


def _is_wanted(device: NetworkDevice, models_list: list[str] | None) -> bool:
    """Return whether a discovered device is one of the models asked for."""
    return device.model != GOOGLE_CAST_GROUP and (
        not models_list or device.model in models_list
    )


def _found_enough(
    devices: Iterable[NetworkDevice],
    models_list: list[str] | None,
    max_devices: int | None,
) -> bool:
    """Return whether discovery has found the most devices asked for."""
    return max_devices is not None and (
        sum(_is_wanted(device, models_list) for device in devices) >= max_devices
    )


def _wanted_devices(
    devices: Collection[NetworkDevice], models_list: list[str] | None
) -> list[NetworkDevice]:
    """Return the discovered devices of the models asked for."""
    wanted: list[NetworkDevice] = []
    LOGGER.debug("Got %d devices. Iterating...", len(devices))
    for device in devices:
        if not _is_wanted(device, models_list):
            LOGGER.debug(
                'Skip discovered device "%s" with model "%s"', device.name, device.model
            )
            continue
        LOGGER.debug("Add discovered device: %s", device)
        wanted.append(device)
    return wanted
