from typing import Optional

from faker import Faker
from faker.providers import BaseProvider

from glocaltokens.const import (
    ACCESS_TOKEN_LENGTH,
    LOCAL_AUTH_TOKEN_LENGTH,
    MASTER_TOKEN_LENGTH,
)
from glocaltokens.utils.token import generate as generate_token
from glocaltokens.utils.types import Struct

fake = Faker()


class UtilsProvider(BaseProvider):
    def version(self):
        return "{}.{}.{}".format(fake.pyint(), fake.pyint(), fake.pyint())


class TokenProvider(BaseProvider):
    def master_token(self):
        return generate_token(MASTER_TOKEN_LENGTH, prefix="aas_et/")

    def access_token(self):
        return generate_token(ACCESS_TOKEN_LENGTH, prefix="ya29.")

    def local_auth_token(self):
        return generate_token(LOCAL_AUTH_TOKEN_LENGTH)


class HomegraphProvider(TokenProvider):
    def homegraph_device(self):
        """
        Not sure from where did I get this structure from. Just using the content from client.py as reference.
        """
        return Struct(
            **{
                "local_auth_token": self.local_auth_token(),
                "device_name": fake.word(),
                "hardware": Struct(**{"model": fake.word()}),
            }
        )

    def homegraph_devices(
        self, min_devices: int = 1, max_devices: int = 10, count: Optional[int] = None
    ):
        """
        Generates a random amount of devices, in the range specified.

        min_devices: The number minimum of devices to generate. Should be greater than 0
        max_devices: The maximum number of devices to generate. Must be greater than min_devices
        count: If not None, min_devices and max_devices are ignored, and a count amount of devices will be generated
        """
        return [
            self.homegraph_device()
            for n in range(
                count if count else fake.random.randint(min_devices, max_devices)
            )
        ]
