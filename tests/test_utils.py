from unittest import TestCase

from faker import Faker

from glocaltokens.utils.logs import censor

faker = Faker()


class UtilsTests(TestCase):
    def setUp(self):
        """Setup method run before every test"""
        pass

    def tearDown(self):
        """Teardown method run after every test"""
        pass

    def test_logs(self):
        secret_string = faker.word()
        self.assertNotEqual(secret_string, censor(secret_string))
