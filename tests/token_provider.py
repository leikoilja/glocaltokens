import random
import string
from faker import Faker
from faker.providers import BaseProvider

fake = Faker()


class AASETProvider(BaseProvider):
    def aas_et(self):
        # 9 alphanumeric + "-"
        # 49 alphanumeric + "-"
        "aas_et/".join(random.choice(string.ascii_letters) for x in range(216))
        pass
