"""Test factory providers"""
from __future__ import annotations

from faker import Faker
from faker.providers import BaseProvider
from ghome_foyer_api.api_pb2 import (  # pylint: disable=no-name-in-module
    GetHomeGraphResponse,
)

from glocaltokens.const import (
    ACCESS_TOKEN_LENGTH,
    LOCAL_AUTH_TOKEN_LENGTH,
    MASTER_TOKEN_LENGTH,
)
from glocaltokens.utils.token import generate as generate_token

faker = Faker()


class UtilsProvider(BaseProvider):
    """Utility provider"""

    def version(self) -> str:
        """Generates random version"""
        return f"{faker.pyint()}.{faker.pyint()}.{faker.pyint()}"


class TokenProvider(BaseProvider):
    """Token provider"""

    def master_token(self) -> str:
        """Generates random master token"""
        return generate_token(MASTER_TOKEN_LENGTH, prefix="aas_et/")

    def access_token(self) -> str:
        """Generates random access token"""
        return generate_token(ACCESS_TOKEN_LENGTH, prefix="ya29.")

    def local_auth_token(self) -> str:
        """Generates random local_auth_token token"""
        return generate_token(LOCAL_AUTH_TOKEN_LENGTH)


class HomegraphProvider(TokenProvider):
    """Homegraph provider"""

    def homegraph_device(
        self, device_name: str | None = None
    ) -> GetHomeGraphResponse.Home.Device:
        """Using the content from test requests as reference"""
        device_name = device_name if device_name else faker.word()

        return GetHomeGraphResponse.Home.Device(
            local_auth_token=self.local_auth_token(),
            device_info=GetHomeGraphResponse.Home.Device.DeviceInfo(
                device_id=str(faker.uuid4)
            ),
            device_name=device_name,
            hardware=GetHomeGraphResponse.Home.Device.Hardware(model=faker.word()),
        )

    def homegraph_devices(
        self, min_devices: int = 1, max_devices: int = 10, count: int | None = None
    ) -> list[GetHomeGraphResponse.Home.Device]:
        """
        Generates a random amount of devices, in the range specified.

        min_devices:
          The number minimum of devices to generate. Should be greater than 0
        max_devices:
          The maximum number of devices to generate. Must be greater than min_devices
        count:
          If not None, min_devices and max_devices are ignored,
          and a count amount of devices will be generated
        """
        return [
            self.homegraph_device()
            for n in range(
                count if count else faker.random.randint(min_devices, max_devices)
            )
        ]
