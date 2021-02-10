from typing import List

import pychromecast

GOOGLE_HOME_MODELS = [
    "Google Home",
    "Google Home Mini",
    "Lenovo Smart Clock"
]


class GoogleDevice:
    def __init__(self, name: str, ip: str, port: int, model: str):
        self.name: str = name
        self.ip: str = ip
        self.port: int = port
        self.model: str = model


def discover_devices(models_list) -> List[GoogleDevice]:
    services, browser = pychromecast.discovery.discover_chromecasts()
    devices = []
    for service in services:
        model = service[2]
        name = service[3]
        ip = service[4]
        access_port = service[5]
        if model in models_list:
            devices.append(
                GoogleDevice(name, ip, int(access_port), model)
            )
    return devices
