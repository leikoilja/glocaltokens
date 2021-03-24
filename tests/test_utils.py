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
        # With word
        secret_string = faker.word()
        censored_string = censor(secret_string)
        self.assertNotEqual(secret_string, censored_string)
        self.assertTrue(censored_string.startswith(secret_string[0]))
        self.assertEqual(
            censored_string, f"{secret_string[0]}{(len(secret_string)-1)*'*'}"
        )

        # With different censor character
        secret_string = faker.word()
        censored_string = censor(secret_string, "&")
        self.assertNotEqual(secret_string, censored_string)
        self.assertTrue(censored_string.startswith(secret_string[0]))
        self.assertEqual(
            censored_string, f"{secret_string[0]}{(len(secret_string)-1)*'&'}"
        )

        # With empty string
        censored_string = censor("")
        self.assertEqual(censored_string, "")
