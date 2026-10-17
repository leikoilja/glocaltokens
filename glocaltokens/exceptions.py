"""Errors raised by glocaltokens."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

if TYPE_CHECKING:
    import grpc


class GLocalTokensError(Exception):
    """Base class for the errors raised when Google gives no tokens or devices.

    A mistake in the call, such as creating the client without credentials,
    raises ValueError instead.
    """


class AuthenticationError(GLocalTokensError):
    """Google gave no master or access token, or there is no way to get one.

    error: Google's reason, such as "BadAuthentication" or "NeedsBrowser",
      or None when there isn't one.
    """

    def __init__(self, message: str, error: str | None = None) -> None:
        """Initialize with a message that says which token failed."""
        super().__init__(f"{message}: {error}" if error else message)
        self.error = error


class HomegraphError(GLocalTokensError):
    """Fetching the home graph failed.

    code: The gRPC status code of the failed request.
    details: The details Google gave, or None.
    """

    def __init__(self, code: grpc.StatusCode, details: str | None) -> None:
        """Initialize with the status code and details of the failed request."""
        # Keep the arguments in args, so the error can be copied and pickled
        super().__init__(code, details)
        self.code = code
        self.details = details

    @override
    def __str__(self) -> str:
        """Return the status code and details of the failed request."""
        message = f"Could not get the home graph: {self.code.name}"
        return f"{message} ({self.details})" if self.details else message
