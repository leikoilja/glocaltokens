"""Test factory providers."""

from __future__ import annotations

from faker import Faker
from faker.providers import BaseProvider
from ghome_foyer_api.api_pb2 import HomeGraph  # pylint: disable=no-name-in-module

from glocaltokens.const import LOCAL_AUTH_TOKEN_LENGTH, MASTER_TOKEN_LENGTH

ACCESS_TOKEN_LENGTH = 315

faker = Faker()


class UtilsProvider(BaseProvider):
    """Utility provider."""

    def version(self) -> str:
        """Generate random version."""
        return f"{faker.pyint()}.{faker.pyint()}.{faker.pyint()}"


class TokenProvider(BaseProvider):
    """Token provider."""

    def master_token(self) -> str:
        """Generate random master token."""
        return "aas_et/" + self.lexify("?" * MASTER_TOKEN_LENGTH)

    def access_token(self) -> str:
        """Generate random access token."""
        return "ya29." + self.lexify("?" * ACCESS_TOKEN_LENGTH)

    def local_auth_token(self) -> str:
        """Generate random local_auth_token token."""
        return self.lexify("?" * LOCAL_AUTH_TOKEN_LENGTH)


class HomegraphProvider(TokenProvider):
    """Homegraph provider."""

    def homegraph_device(self, device_name: str | None = None) -> HomeGraph.Device:
        """Create and return a mocked HomeGraph device object."""
        device_name = device_name or faker.word()

        return HomeGraph.Device(
            local_auth_token=self.local_auth_token(),
            id=HomeGraph.DeviceId(
                device_id=str(faker.uuid4()),
                agent_info=HomeGraph.DeviceId.AgentInfo(
                    unique_id=faker.hexify("^" * 32)
                ),
            ),
            display_name=device_name,
            hardware=HomeGraph.Device.Hardware(model=faker.word()),
        )

    def homegraph_devices(
        self, min_devices: int = 1, max_devices: int = 10, count: int | None = None
    ) -> list[HomeGraph.Device]:
        """Generate a random amount of devices, in the range specified.

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
            for n in range(count or faker.random.randint(min_devices, max_devices))
        ]
