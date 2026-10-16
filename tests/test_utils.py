"""Utility tests."""

from unittest import TestCase

from glocaltokens.utils.logs import censor


class UtilsTests(TestCase):
    """Utilities tests."""

    def test_censor(self) -> None:
        """Testing sensitive info censoring."""
        # With word
        assert censor("secret") == "s*****"

        # With empty string
        censored_string = censor("")
        assert censored_string == ""

        # Hide first letter
        assert censor("abc", hide_first_letter=True) == "***"

        # Hide length
        assert censor("abc", hide_length=True) == "a<redacted>"

        # Hide both
        assert censor("abc", hide_first_letter=True, hide_length=True) == "<redacted>"
