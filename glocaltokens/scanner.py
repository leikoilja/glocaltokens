"""Zeroconf based scanner."""

from __future__ import annotations

import ipaddress
import logging
from threading import Event
import time
from typing import TYPE_CHECKING, NamedTuple, override
import warnings

from zeroconf import ServiceBrowser, ServiceInfo, ServiceListener, Zeroconf

from .const import DISCOVERY_TIMEOUT, GOOGLE_CAST_GROUP, SERVICE_INFO_TIMEOUT

if TYPE_CHECKING:
    from collections.abc import Callable

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
        remove_callback: Callable[[], None] | None = None,
        update_callback: Callable[[], None] | None = None,
        deadline: float | None = None,
    ):
        """Create cast listener.

        deadline: time.monotonic() value after which service lookups stop.
        """
        self.devices: dict[str, NetworkDevice] = {}
        self.deadline = deadline
        self.add_callback = add_callback
        self.remove_callback = remove_callback
        self.update_callback = update_callback

    @property
    def count(self) -> int:
        """Number of discovered cast services."""
        return len(self.devices)

    @override
    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Add a service to the collection."""
        LOGGER.debug("add_service %s, %s", type_, name)
        self._add_update_service(zc, type_, name, self.add_callback)

    @override
    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Update a service in the collection."""
        LOGGER.debug("update_service %s, %s", type_, name)
        self._add_update_service(zc, type_, name, self.update_callback)

    @override
    def remove_service(self, _zc: Zeroconf, type_: str, name: str) -> None:
        """Remove a cast device when its mDNS info expires or the host is down."""
        LOGGER.debug("remove_service %s, %s", type_, name)
        if name in self.devices:
            del self.devices[name]
        if self.remove_callback:
            self.remove_callback()

    def _add_update_service(
        self,
        zc: Zeroconf,
        type_: str,
        name: str,
        callback: Callable[[], None] | None,
    ) -> None:
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

        # zeroconf lists IPv4 addresses first
        ip_address = next(filter(_is_reachable, service.parsed_addresses()), None)

        model_name = self.get_service_value(service, "md")
        friendly_name = self.get_service_value(service, "fn")
        unique_id = self.get_service_value(service, "cd")

        if not model_name or not friendly_name or not service.port or not unique_id:
            LOGGER.debug(
                "Discovered device %s has incomplete service info, skipping...",
                name,
            )
            return

        if ip_address is None:
            LOGGER.debug(
                "Discovered device %s has no reachable IP address, skipping...", name
            )
            return

        if not 0 <= service.port <= 65535:
            LOGGER.error(
                "Port of discovered device is out of the valid range: [0,65535]"
            )
            return

        self.devices[name] = NetworkDevice(
            name=friendly_name,
            ip_address=ip_address,
            port=service.port,
            model=model_name,
            unique_id=unique_id,
        )

        if callback:
            callback()

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

    def is_wanted(device: NetworkDevice) -> bool:
        return device.model != GOOGLE_CAST_GROUP and (
            not models_list or device.model in models_list
        )

    def callback() -> None:
        """Handle the event when zeroconf discovers a new device."""
        if max_devices is not None and (
            sum(map(is_wanted, listener.devices.values())) >= max_devices
        ):
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

    devices: list[NetworkDevice] = []
    LOGGER.debug("Got %d devices. Iterating...", listener.count)
    for device in listener.devices.values():
        if not is_wanted(device):
            LOGGER.debug(
                'Skip discovered device "%s" with model "%s"', device.name, device.model
            )
            continue
        LOGGER.debug("Add discovered device: %s", device)
        devices.append(device)
    return devices
