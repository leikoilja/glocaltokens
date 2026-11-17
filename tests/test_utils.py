"""Utility tests."""

from unittest import TestCase

import pytest

from glocaltokens.const import MASTER_TOKEN_LENGTH
from glocaltokens.utils.logs import censor
from glocaltokens.utils.network import is_valid_ipv4_address
from glocaltokens.utils.token import (
    MASTER_TOKEN_LENGTH as COMPAT_MASTER_TOKEN_LENGTH,
    is_aas_et,
)


def test_historical_master_token_length_imports() -> None:
    """Keep the historical payload length available from both public paths."""
    assert MASTER_TOKEN_LENGTH == COMPAT_MASTER_TOKEN_LENGTH == 216


@pytest.mark.parametrize(
    ("total", "valid"),
    [(199, False), (200, True), (201, True), (223, True), (243, True), (317, True)],
)
def test_master_token_total_length(total: int, *, valid: bool) -> None:
    """Measure total length after stripping ASCII and Unicode padding."""
    token = "aas_et/" + "a" * (total - 7)
    assert is_aas_et(token) is valid
    assert is_aas_et(f"\u2003\t{token}\r\n\u00a0") is valid


@pytest.mark.parametrize(
    "token",
    [
        "",
        " \t",
        "aas_et/",
        "AAS_ET/" + "a" * 216,
        "oauth2/" + "a" * 216,
        "a" * 223,
        "\x00aas_et/" + "a" * 216,
    ],
)
def test_master_token_requires_exact_prefix(token: str) -> None:
    """Reject missing or damaged prefixes and empty payloads."""
    assert not is_aas_et(token)


@pytest.mark.parametrize("char", [" ", "\t", "\n", "\r", "\x00", "\x1b", "\x7f", "é"])
def test_master_token_rejects_damaged_payload(char: str) -> None:
    """Reject an invalid interior character in a sufficiently long token."""
    assert not is_aas_et("aas_et/" + "a" * 100 + char + "b" * 116)


def test_master_token_accepts_visible_punctuation() -> None:
    """Treat the visible ASCII payload as opaque."""
    assert is_aas_et("aas_et/" + "a" * 216 + "!-_/=~")
    assert not is_aas_et(b"aas_et/" + b"a" * 216)  # type: ignore[arg-type]


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
