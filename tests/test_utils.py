"""Utility tests."""

from unittest import TestCase

from glocaltokens.utils.logs import censor
from glocaltokens.utils.network import is_valid_ipv4_address


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

    def test_ip_address_validation(self) -> None:
        """Testing IPv4 address validation."""
        assert is_valid_ipv4_address("192.168.1.10")
        for address in ("192.168.1", "192.168.1.256", "01.1.1.1", "::1", "", "host"):
            assert not is_valid_ipv4_address(address), address
