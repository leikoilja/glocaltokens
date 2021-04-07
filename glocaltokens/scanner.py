"""Zeroconf based scanner"""
import logging
from threading import Event
from typing import List, Optional

from zeroconf import ServiceListener

from .const import DISCOVER_TIMEOUT
from .utils import network as net_utils, types as type_utils

LOGGER = logging.getLogger(__name__)


# pylint: disable=invalid-name
class CastListener(ServiceListener):
    """
    Zeroconf Cast Services collection.
    Credit (pychromecast):
    https://github.com/home-assistant-libs/pychromecast/
    """

    def __init__(self, add_callback=None, remove_callback=None, update_callback=None):
        self.devices = []
        self.add_callback = add_callback
        self.remove_callback = remove_callback
        self.update_callback = update_callback

    @property
    def count(self):
        """Number of discovered cast services."""
        return len(self.devices)

    def add_service(self, zc, type_, name):
        """ Add a service to the collection. """
        LOGGER.debug("add_service %s, %s", type_, name)
        self._add_update_service(zc, type_, name, self.add_callback)

    def update_service(self, zc, type_, name):
        """ Update a service in the collection. """
        LOGGER.debug("update_service %s, %s", type_, name)
        self._add_update_service(zc, type_, name, self.update_callback)

    def remove_service(self, _zconf, type_, name):
        """Called when a cast has beeen lost (mDNS info expired or host down)."""
        LOGGER.debug("remove_service %s, %s", type_, name)

    def _add_update_service(self, zc, type_, name, callback):
        """ Add or update a service. """
        service = None
        tries = 0
        if name.endswith("_sub._googlecast._tcp.local."):
            LOGGER.debug("_add_update_service ignoring %s, %s", type_, name)
            return
        while service is None and tries < 4:
            try:
                service = zc.get_service_info(type_, name)
            except IOError:
                # If the zeroconf fails to receive the necessary data we abort
                # adding the service
                break
            tries += 1

        if not service:
            LOGGER.debug("_add_update_service failed to add %s, %s", type_, name)
            return

        def get_value(key):
            """Retrieve value and decode to UTF-8."""
            value = service.properties.get(key.encode("utf-8"))

            if value is None or isinstance(value, str):
                return value
            return value.decode("utf-8")

        addresses = service.parsed_addresses()
        host = addresses[0] if addresses else service.server

        model_name = get_value("md")
        friendly_name = get_value("fn")

        self.devices.append((model_name, friendly_name, host, service.port))

        if callback:
            callback()


class GoogleDevice:
    """Discovered Google device representation"""

    def __init__(self, name: str, ip_address: str, port: int, model: str):
        LOGGER.debug("Initializing GoogleDevice...")
        if not net_utils.is_valid_ipv4_address(
            ip_address
        ) and not net_utils.is_valid_ipv6_address(ip_address):
            LOGGER.error("IP must be a valid IP address")
            return

        if not type_utils.is_integer(port):
            LOGGER.error("PORT must be an integer value")
            return

        self.name = name
        self.ip_address = ip_address
        self.port = port
        self.model = model
        LOGGER.debug(
            "Set self name to %s, IP to %s, PORT to %s and model to %s",
            name,
            ip_address,
            port,
            model,
        )

        if not 0 <= self.port <= 65535:
            LOGGER.error("Port is out of the valid range: [0,65535]")
            return

    def __str__(self) -> str:
        """Serializes the class into a str"""
        return (
            f"{{name:{self.name},ip:{self.ip_address},"
            f"port:{self.port},model:{self.model}}}"
        )


def discover_devices(
    models_list: Optional[List[str]] = None,
    max_devices: int = None,
    timeout: int = DISCOVER_TIMEOUT,
    zeroconf_instance=None,
    logging_level=logging.ERROR,
):
    """Discover devices"""
    LOGGER.setLevel(logging_level)

    LOGGER.debug("Discovering devices...")
    LOGGER.debug("Importing zeroconf...")
    # pylint: disable=import-outside-toplevel
    import zeroconf

    def callback():
        """Called when zeroconf has discovered a new chromecast."""
        if max_devices is not None and listener.count >= max_devices:
            discover_complete.set()

    LOGGER.debug("Creating new Event for discovery completion...")
    discover_complete = Event()
    LOGGER.debug("Creating new CastListener...")
    listener = CastListener(callback)
    if not zeroconf_instance:
        LOGGER.debug("Creating new Zeroconf instance")
        zc = zeroconf.Zeroconf()
    else:
        LOGGER.debug("Using attribute Zeroconf instance")
        zc = zeroconf_instance
    LOGGER.debug("Creating zeroconf service browser for _googlecast._tcp.local.")
    zeroconf.ServiceBrowser(zc, "_googlecast._tcp.local.", listener)

    # Wait for the timeout or the maximum number of devices
    LOGGER.debug("Waiting for discovery completion...")
    discover_complete.wait(timeout)

    devices = []
    LOGGER.debug("Got %s devices. Iterating...", len(listener.devices))
    for service in listener.devices:
        model = service[0]
        name = service[1]
        ip_address = service[2]
        access_port = service[3]
        if not models_list or model in models_list:
            LOGGER.debug(
                "Appending new device. name: %s, ip: %s, port: %s, model: %s",
                name,
                ip_address,
                access_port,
                model,
            )
            devices.append(GoogleDevice(name, ip_address, int(access_port), model))
        else:
            LOGGER.debug(
                'Won\'t add device since model "%s" is not in models_list', model
            )
    return devices
