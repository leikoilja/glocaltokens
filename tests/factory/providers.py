from faker import Faker
from faker.providers import BaseProvider

from glocaltokens.utils.token import generate as generate_token

fake = Faker()


class TokenProvider(BaseProvider):
    def master_token(self):
        return generate_token(216, prefix="aas_et/")

    def access_token(self):
        return generate_token(315, prefix="ya29.")

    def local_auth_token(self):
        return generate_token(108)


class HomegraphProvider(BaseProvider):
    def home_devices(self):
        pass
