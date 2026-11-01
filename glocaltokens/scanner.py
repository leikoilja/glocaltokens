"""Zeroconf based scanner."""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
from threading import Event
import time
from typing import TYPE_CHECKING, NamedTuple, override
import warnings

from zeroconf import (
    ServiceBrowser,
    ServiceInfo,
    ServiceListener,
    ServiceStateChange,
    Zeroconf,
)
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

from .const import DISCOVERY_TIMEOUT, GOOGLE_CAST_GROUP, SERVICE_INFO_TIMEOUT

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable

LOGGER = logging.getLogger(__name__)


def _is_reachable(address: str) -> bool:
    """Whether a discovered address can be used to reach the device.

    A link-local IPv6 address can't be, as it only works with its interface,
    which zeroconf's parsed_addresses() leaves out.
    """
    ip = ipaddress.ip_address(address)
    return ip.version == 4 or not ip.is_link_local


class NetworkDevice(NamedTuple):
    """Discovered Google device representation."""

    name: str
    ip_address: str
    port: int
    model: str
    unique_id: str


class CastListener(ServiceListener):
    """Zeroconf Cast Services collection.

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
    """Discover devices."""
    if logging_level is not None:
        warnings.warn(
            "logging_level is deprecated and ignored, set the level of the "
            "glocaltokens logger in your application instead",
            DeprecationWarning,
            stacklevel=2,
        )

    LOGGER.debug("Discovering devices...")

    def callback() -> None:
        """Handle zeroconf adding or updating a device."""
        if _found_enough(listener.devices.values(), models_list, max_devices):
            discovery_complete.set()

    LOGGER.debug("Creating new Event for discovery completion...")
    discovery_complete = Event()
    LOGGER.debug("Creating new CastListener...")
    listener = CastListener(add_callback=callback, deadline=time.monotonic() + timeout)
    if not zeroconf_instance:
        LOGGER.debug("Creating new Zeroconf instance")
        zc = Zeroconf()
    else:
        LOGGER.debug("Using attribute Zeroconf instance")
        zc = zeroconf_instance
    try:
        LOGGER.debug("Creating zeroconf service browser for _googlecast._tcp.local.")
        service_browser = ServiceBrowser(zc, "_googlecast._tcp.local.", listener)
        try:
            # Wait for the timeout or the maximum number of devices
            LOGGER.debug("Waiting for discovery completion...")
            discovery_complete.wait(timeout)
        finally:
            # Stop discovery
            service_browser.cancel()
    finally:
        # A supplied instance belongs to the caller, who may still be using it.
        if not zeroconf_instance:
            zc.close()

    return _wanted_devices(listener.devices.values(), models_list)


async def async_discover_devices(
    models_list: list[str] | None = None,
    max_devices: int | None = None,
    # How long to listen, as in discover_devices(), not a limit on the call
    timeout: float = DISCOVERY_TIMEOUT,  # noqa: ASYNC109
    zeroconf_instance: Zeroconf | None = None,
) -> list[NetworkDevice]:
    """Discover devices without blocking the event loop.

    zeroconf_instance must run on the calling event loop, as Home Assistant's
    shared instance does. Without one, an AsyncZeroconf is created and closed.
    """
    LOGGER.debug("Discovering devices...")
    deadline = time.monotonic() + timeout
    devices: dict[str, NetworkDevice] = {}
    # The lookup whose result is kept, by service name
    owners: dict[str, asyncio.Task[None]] = {}
    # Every lookup that hasn't finished, including ones whose result is no
    # longer kept, so that none outlives discovery
    pending: set[asyncio.Task[None]] = set()
    discovery_complete = asyncio.Event()

    async def look_up(zc: Zeroconf, type_: str, name: str) -> None:
        service = AsyncServiceInfo(type_, name)
        lookup_timeout = min(
            SERVICE_INFO_TIMEOUT, int((deadline - time.monotonic()) * 1000)
        )
        try:
            if lookup_timeout > 0:
                found = await service.async_request(zc, lookup_timeout)
            else:
                # Out of time: still use details zeroconf already has.
                found = service.load_from_cache(zc)
        except OSError:
            # As discover_devices(): give up on this service
            found = False
        # A later update or removal of the service replaced this lookup
        if owners.get(name) is not asyncio.current_task():
            return
        device = _network_device(service, name) if found else None
        if device is None:
            LOGGER.debug("Discovery failed to add %s, %s", type_, name)
            return
        devices[name] = device
        if _found_enough(devices.values(), models_list, max_devices):
            discovery_complete.set()

    def on_change(
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        LOGGER.debug("%s %s, %s", state_change.name, service_type, name)
        if owner := owners.pop(name, None):
            _cancel_once(owner)
        if state_change is ServiceStateChange.Removed:
            devices.pop(name, None)
            return
        if name.endswith("_sub._googlecast._tcp.local."):
            return
        task = asyncio.create_task(look_up(zeroconf, service_type, name))
        owners[name] = task
        pending.add(task)
        task.add_done_callback(pending.discard)

    own_zeroconf: AsyncZeroconf | None = None
    if zeroconf_instance is None:
        LOGGER.debug("Creating new Zeroconf instance")
        own_zeroconf = AsyncZeroconf()
        zc = own_zeroconf.zeroconf
    else:
        zc = zeroconf_instance
    try:
        browser = AsyncServiceBrowser(
            zc, "_googlecast._tcp.local.", handlers=[on_change]
        )
        try:
            # Wait for the timeout or the maximum number of devices
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(discovery_complete.wait(), timeout)
        finally:
            await browser.async_cancel()
            for task in pending:
                _cancel_once(task)
            await asyncio.gather(*pending, return_exceptions=True)
    finally:
        # A supplied instance belongs to the caller, who may still be using it.
        if own_zeroconf is not None:
            await own_zeroconf.async_close()

    return _wanted_devices(devices.values(), models_list)


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
