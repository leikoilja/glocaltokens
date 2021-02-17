import logging
from threading import Event
from typing import Optional

import zeroconf

from .utils import network as net_utils
from .utils import type as type_utils

DISCOVER_TIMEOUT = 5
GOOGLE_HOME_MODELS = [
    "Google Home",
    "Google Home Mini",
    "Google Nest Mini",
    "Lenovo Smart Clock",
]

_LOGGER = logging.getLogger(__name__)


class CastListener:
    """
    Zeroconf Cast Services collection.
    Credit (pychromecast): https://github.com/home-assistant-libs/pychromecast/blob/master/pychromecast/discovery.py
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

    def update_service(self, zconf, typ, name):
        """ Update a service in the collection. """
        _LOGGER.debug("update_service %s, %s", typ, name)
        self._add_update_service(zconf, typ, name, self.update_callback)

    def add_service(self, zconf, typ, name):
        """ Add a service to the collection. """
        _LOGGER.debug("add_service %s, %s", typ, name)
        self._add_update_service(zconf, typ, name, self.add_callback)

    def _add_update_service(self, zconf, typ, name, callback):
        """ Add or update a service. """
        service = None
        tries = 0
        if name.endswith("_sub._googlecast._tcp.local."):
            _LOGGER.debug("_add_update_service ignoring %s, %s", typ, name)
            return
        while service is None and tries < 4:
            try:
                service = zconf.get_service_info(typ, name)
            except IOError:
                # If the zeroconf fails to receive the necessary data we abort
                # adding the service
                break
            tries += 1

        if not service:
            _LOGGER.debug("_add_update_service failed to add %s, %s", typ, name)
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
    def __init__(self, name: str, ip: str, port: int, model: str):
        if not net_utils.is_valid_ipv4_address(
            ip
        ) and not net_utils.is_valid_ipv6_address(ip):
            _LOGGER.error("ip must be a valid IP address")
            return

        if not type_utils.is_integer(port):
            _LOGGER.error("port must be an integer value")
            return

        self.name = name
        self.ip = ip
        self.port = port
        self.model = model

        if not 0 <= self.port <= 65535:
            _LOGGER.error("Port is out of the valid range: [0,65535]")
            return


def discover_devices(models_list, max_devices=None, timeout=DISCOVER_TIMEOUT):
    # pylint: disable=unused-argument
    def callback():
        """Called when zeroconf has discovered a new chromecast."""
        if max_devices is not None and listener.count >= max_devices:
            discover_complete.set()

    discover_complete = Event()
    listener = CastListener(callback)
    zconf = zeroconf.Zeroconf()
    zeroconf.ServiceBrowser(zconf, "_googlecast._tcp.local.", listener)

    # Wait for the timeout or the maximum number of devices
    discover_complete.wait(timeout)

    devices = []
    for service in listener.devices:
        model = service[0]
        name = service[1]
        ip = service[2]
        access_port = service[3]
        if not models_list or model in models_list:
            devices.append(GoogleDevice(name, ip, int(access_port), model))
    return devices
