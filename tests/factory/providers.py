import random
import string
from faker import Faker
from faker.providers import BaseProvider

fake = Faker()


class TokenProvider(BaseProvider):
    def aas_et(self):
        return "aas_et/" + "".join(random.choice(string.ascii_letters) for x in range(216))

    def local_auth_token(self):
        return "".join(random.choice(string.ascii_letters) for x in range(108))
