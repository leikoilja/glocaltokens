from faker import Faker
from faker.providers import BaseProvider
from glocaltokens.utils.token import generate as generate_token

fake = Faker()


class TokenProvider(BaseProvider):
    def aas_et(self):
        return generate_token(216, prefix="aas_et/")

    def local_auth_token(self):
        return generate_token(108)
