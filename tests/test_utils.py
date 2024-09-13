"""Utility tests"""

from unittest import TestCase

from faker import Faker

from glocaltokens.utils.logs import censor

faker = Faker()


class UtilsTests(TestCase):
    """Utilities tests"""

    def test_censor(self) -> None:
        """Testing sensitive info censoring"""
        # With word
        secret_string = faker.word()
        censored_string = censor(secret_string)
        self.assertNotEqual(secret_string, censored_string)
        self.assertTrue(censored_string.startswith(secret_string[0]))
        self.assertEqual(
            censored_string, f"{secret_string[0]}{(len(secret_string) - 1) * '*'}"
        )

        # With empty string
        censored_string = censor("")
        self.assertEqual(censored_string, "")

        # Hide first letter
        self.assertEqual(censor("abc", hide_first_letter=True), "***")

        # Hide length
        self.assertEqual(censor("abc", hide_length=True), "a<redacted>")

        # Hide both
        self.assertEqual(
            censor("abc", hide_first_letter=True, hide_length=True), "<redacted>"
        )
