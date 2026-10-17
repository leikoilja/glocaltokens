"""Exception specific unittests."""

import copy
import pickle
from unittest import TestCase

import grpc

from glocaltokens.exceptions import AuthenticationError, HomegraphError


class ExceptionsTests(TestCase):
    """Exception specific unittests."""

    def test_copy_and_pickle(self) -> None:
        """Test the errors keep their message and attributes when copied or pickled."""
        errors = (
            AuthenticationError("Google gave no master token", "BadAuthentication"),
            HomegraphError(grpc.StatusCode.UNAVAILABLE, "failed to connect"),
            HomegraphError(grpc.StatusCode.DEADLINE_EXCEEDED, None),
        )
        for error in errors:
            for clone in (copy.copy(error), pickle.loads(pickle.dumps(error))):
                with self.subTest(clone=clone):
                    assert type(clone) is type(error)
                    assert str(clone) == str(error)
                    assert vars(clone) == vars(error)
