from faker import Faker
from faker.providers import BaseProvider

from glocaltokens.const import (
    ACCESS_TOKEN_LENGTH,
    LOCAL_AUTH_TOKEN_LENGTH,
    MASTER_TOKEN_LENGTH,
)
from glocaltokens.utils.token import generate as generate_token
from glocaltokens.utils.type import Struct

from .const import SMART_HOME_DEVICE_TYPES

fake = Faker()


class TokenProvider(BaseProvider):
    def master_token(self):
        return generate_token(MASTER_TOKEN_LENGTH, prefix="aas_et/")

    def access_token(self):
        return generate_token(ACCESS_TOKEN_LENGTH, prefix="ya29.")

    def local_auth_token(self):
        return generate_token(LOCAL_AUTH_TOKEN_LENGTH)


class HomegraphProvider(BaseProvider):
    def home_devices(self):
        pass
