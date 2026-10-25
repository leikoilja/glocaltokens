"""Client specific unittests."""

# pylint: disable=too-many-lines

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from http import HTTPStatus
import json
import logging
from typing import override
from unittest import TestCase, mock
from unittest.mock import NonCallableMock, patch
import warnings

from faker import Faker
from faker.providers import internet
import gpsoauth
import grpc
import pytest
import requests

from glocaltokens.client import LOGGER, Device, GLocalAuthenticationTokens
from glocaltokens.const import (
    ACCESS_TOKEN_APP_NAME,
    ACCESS_TOKEN_CLIENT_SIGNATURE,
    ACCESS_TOKEN_DURATION,
    ACCESS_TOKEN_SERVICE,
    ANDROID_ID_LENGTH,
    HOMEGRAPH_DURATION,
    REQUEST_TIMEOUT,
)
from glocaltokens.exceptions import AuthenticationError, HomegraphError
from glocaltokens.scanner import NetworkDevice
from tests.assertions import DeviceAssertions, TypeAssertions
from tests.factory.providers import HomegraphProvider, TokenProvider

faker = Faker()
faker.add_provider(TokenProvider)
faker.add_provider(HomegraphProvider)
faker.add_provider(internet)


def fake_rpc_error(code: grpc.StatusCode, details: str = "") -> grpc.RpcError:
    """Return a gRPC error with the given status code and details."""
    rpc_error = grpc.RpcError()
    rpc_error.code = mock.Mock(return_value=code)  # type: ignore[method-assign]
    rpc_error.details = mock.Mock(return_value=details)  # type: ignore[method-assign]
    return rpc_error


class GLocalAuthenticationTokensClientTests(DeviceAssertions, TypeAssertions, TestCase):
    """GLocalAuthenticationTokens clien specific unittests."""

    @override
    def setUp(self) -> None:
        """Set up the test client before each test."""
        self.client = GLocalAuthenticationTokens(
            username=faker.word(), password=faker.word()
        )

    def test_initialization(self) -> None:
        """Valid initialization tests."""
        username = faker.word()
        password = faker.word()
        master_token = faker.master_token()
        android_id = faker.word()

        client = GLocalAuthenticationTokens(
            username=username,
            password=password,
            master_token=master_token,
            android_id=android_id,
        )
        assert username == client.username
        assert password == client.password
        assert master_token == client.master_token
        assert android_id == client.android_id

        assert client.access_token is None
        assert client.homegraph is None
        assert client.access_token_date is None
        assert client.homegraph_date is None

        assert client.master_token is not None
        self.assertIsAasEt(client.master_token)

    def test_initialization__valid(self) -> None:
        """Valid initialization tests."""
        # With username and password
        GLocalAuthenticationTokens(username=faker.word(), password=faker.word())

        # With master_token
        GLocalAuthenticationTokens(master_token=faker.master_token())

        # With oauth_token
        GLocalAuthenticationTokens(oauth_token=faker.word())

        # With a master_token of another length than today's
        GLocalAuthenticationTokens(master_token=f"aas_et/{faker.word()}")

    @patch("glocaltokens.client.logging.basicConfig")
    def test_initialization__verbose_deprecated(
        self, m_basic_config: NonCallableMock
    ) -> None:
        """The verbose argument warns and leaves logging to the application."""
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            GLocalAuthenticationTokens(master_token=faker.master_token())

        for verbose in (True, False):
            with pytest.warns(
                DeprecationWarning, match="verbose is deprecated"
            ) as record:
                GLocalAuthenticationTokens(
                    master_token=faker.master_token(), verbose=verbose
                )
            assert record[0].filename == __file__
            assert LOGGER.level == logging.NOTSET
        m_basic_config.assert_not_called()

    def test_initialization__keeps_application_log_level(self) -> None:
        """The client keeps the level the application set."""
        package_logger = logging.getLogger("glocaltokens")
        package_logger.setLevel(logging.DEBUG)
        try:
            GLocalAuthenticationTokens(username=faker.word(), password=faker.word())
            assert LOGGER.getEffectiveLevel() == logging.DEBUG
        finally:
            package_logger.setLevel(logging.NOTSET)

    def test_initialization__invalid(self) -> None:
        """Invalid initialization tests."""
        no_credentials = "You must either provide"
        # Without username
        with pytest.raises(ValueError, match=no_credentials):
            GLocalAuthenticationTokens(password=faker.word())

        # Without password
        with pytest.raises(ValueError, match=no_credentials):
            GLocalAuthenticationTokens(username=faker.word())

        # Without username and password
        with pytest.raises(ValueError, match=no_credentials):
            GLocalAuthenticationTokens()

        # With invalid master_token
        master_token = faker.password(length=40, special_chars=False)
        with pytest.raises(ValueError, match="AAS_ET format") as exc_info:
            GLocalAuthenticationTokens(
                username=faker.word(), password=faker.word(), master_token=master_token
            )
        assert master_token not in str(exc_info.value)

    def test_get_android_id(self) -> None:
        """Test getting android id."""
        android_id = self.client.get_android_id()
        assert len(android_id) == ANDROID_ID_LENGTH

        # Make sure we get the same ID when called further
        assert android_id == self.client.get_android_id()

    # pylint: disable=protected-access
    def test_generate_android_id(self) -> None:
        """Test generating mac string."""
        android_id = GLocalAuthenticationTokens._generate_android_id()
        assert len(android_id) == ANDROID_ID_LENGTH

        # Make sure we get different generated mac string
        assert android_id != GLocalAuthenticationTokens._generate_android_id()

    def test_has_expired(self) -> None:
        """Test expiry method."""
        duration_sec = 60
        now = datetime.now(UTC)
        token_dt_expired = now - timedelta(seconds=duration_sec + 1)
        token_dt_non_expired = now - timedelta(seconds=duration_sec - 1)

        # Expired
        assert GLocalAuthenticationTokens._has_expired(token_dt_expired, duration_sec)

        # Non expired
        assert not GLocalAuthenticationTokens._has_expired(
            token_dt_non_expired, duration_sec
        )

    @patch("glocaltokens.client.perform_master_login")
    def test_get_master_token(self, m_perform_master_login: NonCallableMock) -> None:
        """Test getting master token."""
        # No token in response
        m_perform_master_login.return_value = {"Error": "BadAuthentication"}
        with pytest.raises(AuthenticationError, match="no master token") as exc_info:
            self.client.get_master_token()
        assert exc_info.value.error == "BadAuthentication"
        m_perform_master_login.assert_called_once_with(
            self.client.username, self.client.password, self.client.get_android_id()
        )

        # No token and no reason in response, or an empty token
        for response in ({}, {"Token": ""}):
            m_perform_master_login.return_value = response
            with pytest.raises(AuthenticationError) as exc_info:
                self.client.get_master_token()
            assert exc_info.value.error is None
        assert self.client.master_token is None

        # Reset mocks
        m_perform_master_login.reset_mock()

        # With token in response
        expected_master_token = faker.master_token()
        email = faker.email()
        m_perform_master_login.return_value = {
            "Token": expected_master_token,
            "Email": email,
        }
        master_token = self.client.get_master_token()
        m_perform_master_login.assert_called_once_with(
            self.client.username, self.client.password, self.client.get_android_id()
        )
        assert expected_master_token == master_token
        assert self.client.email == email

        # Another request - must return the same token all the time
        master_token = self.client.get_master_token()
        assert expected_master_token == master_token

    @patch("glocaltokens.client.perform_master_login")
    def test_get_master_token__password_too_long(
        self, m_perform_master_login: NonCallableMock
    ) -> None:
        """Test a password gpsoauth can't encrypt raises AuthenticationError."""
        password = faker.password(length=600)
        client = GLocalAuthenticationTokens(username=faker.email(), password=password)
        m_perform_master_login.side_effect = ValueError("Plaintext is too long.")

        with pytest.raises(AuthenticationError, match="too long") as exc_info:
            client.get_master_token()
        assert exc_info.value.error is None
        assert isinstance(exc_info.value.__cause__, ValueError)
        assert password not in str(exc_info.value)

    @patch("glocaltokens.client.perform_master_login")
    def test_get_master_token__invalid_proxy(
        self, m_perform_master_login: NonCallableMock
    ) -> None:
        """Test a requests error that is a ValueError too isn't taken for a password."""
        m_perform_master_login.side_effect = requests.exceptions.InvalidProxyURL()
        with pytest.raises(requests.exceptions.InvalidProxyURL):
            self.client.get_master_token()

    @patch("requests.adapters.HTTPAdapter.close")
    @patch("requests.adapters.HTTPAdapter.send")
    def test_get_master_token__server_error(
        self, m_send: NonCallableMock, m_close: NonCallableMock
    ) -> None:
        """Test an answer that means "try later" raises HTTPError.

        gpsoauth reads any answer as a login response, so it would look like
        Google refusing the credentials.
        """

        def response(status: HTTPStatus, text: str) -> requests.Response:
            response = requests.Response()
            response.status_code = status
            response._content = text.encode()  # pylint: disable=protected-access
            response.encoding = "utf-8"
            return response

        body = "<html>Unavailable</html>"
        for status in (HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.TOO_MANY_REQUESTS):
            with self.subTest(status=status):
                m_send.return_value = response(status, body)
                with pytest.raises(
                    requests.HTTPError, match=str(int(status))
                ) as http_error:
                    self.client.get_master_token()
                # The error keeps Google's answer, but not the connection
                assert http_error.value.response is not None
                assert http_error.value.response.text == body
                m_close.assert_called_once()
                m_close.reset_mock()
                # Other gpsoauth users still get gpsoauth's own result
                assert gpsoauth.perform_oauth(
                    faker.email(), faker.master_token(), faker.word(), "s", "a", "c"
                ) == {body: ""}

        # Google refusing the credentials is still an AuthenticationError
        m_send.return_value = response(
            HTTPStatus.FORBIDDEN, "Error=BadAuthentication\n"
        )
        with pytest.raises(AuthenticationError) as exc_info:
            self.client.get_master_token()
        assert exc_info.value.error == "BadAuthentication"

    @patch("glocaltokens.client.requests.get")
    @patch("glocaltokens.client.exchange_token")
    @patch("glocaltokens.client.perform_master_login")
    @patch("glocaltokens.client.perform_oauth")
    def test_get_master_token__no_credentials(
        self,
        m_perform_oauth: NonCallableMock,
        m_perform_master_login: NonCallableMock,
        m_exchange_token: NonCallableMock,
        m_get: NonCallableMock,
    ) -> None:
        """Test a client with only a master token can't get a new one."""
        client = GLocalAuthenticationTokens(master_token=faker.master_token())
        client.invalidate_master_token()

        with pytest.raises(AuthenticationError, match="No master token") as exc_info:
            client.get_master_token()
        assert exc_info.value.error is None
        # Nor can one with an empty username and password
        empty = GLocalAuthenticationTokens(
            username="", password="", master_token=faker.master_token()
        )
        empty.invalidate_master_token()
        with pytest.raises(AuthenticationError, match="No master token"):
            empty.get_master_token()
        # The methods that need a master token raise the same error
        with pytest.raises(AuthenticationError, match="No master token"):
            client.get_access_token()
        with pytest.raises(AuthenticationError, match="No master token"):
            client.get_email()
        with pytest.raises(AuthenticationError, match="No master token"):
            client.get_google_devices(disable_discovery=True)
        m_perform_master_login.assert_not_called()
        m_exchange_token.assert_not_called()
        m_perform_oauth.assert_not_called()
        m_get.assert_not_called()

    @patch("glocaltokens.client.perform_oauth")
    @patch("glocaltokens.client.exchange_token")
    def test_authentication_error__no_secrets_in_message(
        self, m_exchange_token: NonCallableMock, m_perform_oauth: NonCallableMock
    ) -> None:
        """Test the error message has Google's reason, but no token or password."""
        password = faker.password(length=20)
        oauth_token = faker.password(length=40, special_chars=False)
        url = faker.url() + faker.password(length=40, special_chars=False)
        m_exchange_token.return_value = {"Error": "NeedsBrowser", "Url": url}
        client = GLocalAuthenticationTokens(
            username=faker.email(), password=password, oauth_token=oauth_token
        )

        with pytest.raises(AuthenticationError) as exc_info:
            client.get_master_token()
        message = str(exc_info.value)
        assert message == "Google gave no master token: NeedsBrowser"
        assert password not in message
        assert oauth_token not in message
        assert url not in message

        master_token = faker.master_token()
        m_perform_oauth.return_value = {"Error": "BadAuthentication"}
        client = GLocalAuthenticationTokens(master_token=master_token)
        with pytest.raises(AuthenticationError) as exc_info:
            client.get_access_token()
        message = str(exc_info.value)
        assert message == "Google gave no access token: BadAuthentication"
        assert master_token not in message

    @patch("glocaltokens.client.perform_master_login")
    @patch("glocaltokens.client.exchange_token")
    def test_get_master_token__oauth_token(
        self,
        m_exchange_token: NonCallableMock,
        m_perform_master_login: NonCallableMock,
    ) -> None:
        """Test getting a master token by exchanging an oauth_token cookie."""
        oauth_token = faker.word()
        client = GLocalAuthenticationTokens(
            username=faker.word(), password=faker.word(), oauth_token=oauth_token
        )

        # Failed exchange
        m_exchange_token.return_value = {"Error": "BadAuthentication"}
        with pytest.raises(AuthenticationError) as exc_info:
            client.get_master_token()
        assert exc_info.value.error == "BadAuthentication"

        # Successful exchange, preferred over the password
        expected_master_token = faker.master_token()
        m_exchange_token.return_value = {"Token": expected_master_token}
        assert client.get_master_token() == expected_master_token
        m_exchange_token.assert_called_with(
            client.username, oauth_token, client.get_android_id()
        )
        m_perform_master_login.assert_not_called()

        # The stored master token is used from now on
        m_exchange_token.reset_mock()
        assert client.get_master_token() == expected_master_token
        m_exchange_token.assert_not_called()

    @patch("glocaltokens.client.perform_oauth")
    @patch("glocaltokens.client.exchange_token")
    def test_get_master_token__oauth_token_without_username(
        self, m_exchange_token: NonCallableMock, m_perform_oauth: NonCallableMock
    ) -> None:
        """Test an oauth_token alone is enough, and Google's email is kept."""
        oauth_token = faker.word()
        client = GLocalAuthenticationTokens(oauth_token=oauth_token)

        master_token = faker.master_token()
        email = faker.email()
        m_exchange_token.return_value = {"Token": master_token, "Email": email}
        assert client.get_master_token() == master_token
        m_exchange_token.assert_called_once_with(
            "", oauth_token, client.get_android_id()
        )
        assert client.email == email
        assert client.username is None

        # get_email() needs no further request
        assert client.get_email() == email
        m_perform_oauth.assert_not_called()

        client.invalidate_master_token()
        assert client.email is None

    @patch("requests.adapters.HTTPAdapter.send")
    def test_get_master_token__oauth_token_request_timeout(
        self, m_send: NonCallableMock
    ) -> None:
        """Test the oauth_token exchange made through gpsoauth has a timeout."""
        m_send.side_effect = requests.ConnectionError("No network")
        client = GLocalAuthenticationTokens(
            username=faker.word(), oauth_token=faker.word()
        )
        with pytest.raises(requests.ConnectionError, match="No network"):
            client.get_master_token()
        m_send.assert_called_once()
        assert m_send.call_args.kwargs["timeout"] == REQUEST_TIMEOUT

    @patch("glocaltokens.client.perform_master_login")
    def test_get_master_token__stored_without_password(
        self, m_perform_master_login: NonCallableMock
    ) -> None:
        """Test a stored master token is returned without a password."""
        master_token = faker.master_token()
        client = GLocalAuthenticationTokens(
            username=faker.word(), master_token=master_token
        )
        assert client.get_master_token() == master_token
        m_perform_master_login.assert_not_called()

    @patch("glocaltokens.client.perform_oauth")
    def test_get_access_token__without_username(
        self, m_perform_oauth: NonCallableMock
    ) -> None:
        """Test a master token alone is enough to get an access token."""
        access_token = faker.access_token()
        m_perform_oauth.return_value = {"Auth": access_token}
        master_token = faker.master_token()
        client = GLocalAuthenticationTokens(master_token=master_token)

        assert client.get_access_token() == access_token
        assert m_perform_oauth.call_args.args == (
            "",
            master_token,
            client.get_android_id(),
        )

    @patch("requests.adapters.HTTPAdapter.send")
    def test_get_master_token__request_timeout(self, m_send: NonCallableMock) -> None:
        """Test requests to Google made through gpsoauth have a timeout."""
        m_send.side_effect = requests.ConnectionError("No network")
        with pytest.raises(requests.ConnectionError, match="No network"):
            self.client.get_master_token()
        m_send.assert_called_once()
        assert m_send.call_args.kwargs["timeout"] == REQUEST_TIMEOUT

    @patch("requests.adapters.HTTPAdapter.send")
    def test_get_access_token__request_timeout(self, m_send: NonCallableMock) -> None:
        """Test the access token request made through gpsoauth has a timeout."""
        m_send.side_effect = requests.ConnectionError("No network")
        client = GLocalAuthenticationTokens(
            username=faker.word(), master_token=faker.master_token()
        )
        with pytest.raises(requests.ConnectionError, match="No network"):
            client.get_access_token()
        m_send.assert_called_once()
        assert m_send.call_args.kwargs["timeout"] == REQUEST_TIMEOUT

    @patch("requests.adapters.HTTPAdapter.send")
    def test_gpsoauth_timeout__not_applied_to_other_callers(
        self, m_send: NonCallableMock
    ) -> None:
        """Test gpsoauth requests made outside glocaltokens keep their timeout."""
        m_send.side_effect = requests.ConnectionError("No network")
        with pytest.raises(requests.ConnectionError, match="No network"):
            gpsoauth.perform_oauth(
                faker.email(),
                faker.master_token(),
                faker.word(),
                "service",
                "app",
                "sig",
            )
        m_send.assert_called_once()
        assert m_send.call_args.kwargs["timeout"] is None

    @patch("glocaltokens.client.requests.get")
    @patch("glocaltokens.client.perform_oauth")
    def test_get_email(
        self, m_perform_oauth: NonCallableMock, m_get: NonCallableMock
    ) -> None:
        """Test the email address is read with a token that may only read it."""
        email = faker.email()
        access_token = faker.access_token()
        m_perform_oauth.return_value = {"Auth": access_token}
        m_get.return_value.ok = True
        m_get.return_value.json.return_value = {
            "email": email,
            "email_verified": True,
        }
        client = GLocalAuthenticationTokens(master_token=faker.master_token())

        assert client.get_email() == email
        assert m_perform_oauth.call_args.kwargs["service"] == (
            "oauth2:https://www.googleapis.com/auth/userinfo.email"
        )
        assert m_get.call_args.kwargs["headers"] == {
            "Authorization": f"Bearer {access_token}"
        }
        assert m_get.call_args.kwargs["timeout"] == REQUEST_TIMEOUT

    @patch("glocaltokens.client.requests.get")
    @patch("glocaltokens.client.perform_oauth")
    def test_get_email__unverified(
        self, m_perform_oauth: NonCallableMock, m_get: NonCallableMock
    ) -> None:
        """Test an email address that Google hasn't verified is not returned."""
        m_perform_oauth.return_value = {"Auth": faker.access_token()}
        m_get.return_value.ok = True
        m_get.return_value.json.return_value = {
            "email": faker.email(),
            "email_verified": False,
        }
        client = GLocalAuthenticationTokens(master_token=faker.master_token())

        assert client.get_email() is None

    @patch("glocaltokens.client.requests.get")
    @patch("glocaltokens.client.perform_oauth")
    def test_get_email__http_error(
        self, m_perform_oauth: NonCallableMock, m_get: NonCallableMock
    ) -> None:
        """Test an error response from Google gives no email address."""
        m_perform_oauth.return_value = {"Auth": faker.access_token()}
        m_get.return_value.ok = False
        m_get.return_value.status_code = 401
        client = GLocalAuthenticationTokens(master_token=faker.master_token())

        assert client.get_email() is None
        m_get.return_value.json.assert_not_called()

    @patch("requests.adapters.HTTPAdapter.send")
    @patch("glocaltokens.client.perform_oauth")
    def test_get_email__token_not_in_url_or_logs(
        self, m_perform_oauth: NonCallableMock, m_send: NonCallableMock
    ) -> None:
        """Test the access token is sent in a header, never in the URL or logs.

        Requests and urllib3 put the URL in debug logs and in connection errors.
        """
        access_token = faker.access_token()
        email = faker.email()
        m_perform_oauth.return_value = {"Auth": access_token}
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(  # pylint: disable=protected-access
            {"email": email, "email_verified": True}
        ).encode()
        m_send.return_value = response
        client = GLocalAuthenticationTokens(master_token=faker.master_token())

        with self.assertLogs(level=logging.DEBUG) as logs:
            assert client.get_email() == email

        request = m_send.call_args.args[0]
        assert access_token not in request.url
        assert request.headers["Authorization"] == f"Bearer {access_token}"
        assert not any(access_token in line for line in logs.output)

    @patch("glocaltokens.client.requests.get")
    @patch("glocaltokens.client.perform_oauth")
    def test_get_email__no_access_token(
        self, m_perform_oauth: NonCallableMock, m_get: NonCallableMock
    ) -> None:
        """Test nothing is asked about the email address when Google refuses the token."""
        m_perform_oauth.return_value = {"Error": "BadAuthentication"}
        client = GLocalAuthenticationTokens(master_token=faker.master_token())

        assert client.get_email() is None
        m_get.assert_not_called()

    @patch("glocaltokens.client.perform_oauth")
    @patch("glocaltokens.client.perform_master_login")
    def test_get_email__no_master_token(
        self, m_perform_master_login: NonCallableMock, m_perform_oauth: NonCallableMock
    ) -> None:
        """Test get_email() raises the error Google gives for the master token."""
        m_perform_master_login.return_value = {"Error": "BadAuthentication"}

        with pytest.raises(AuthenticationError) as exc_info:
            self.client.get_email()
        assert exc_info.value.error == "BadAuthentication"
        m_perform_oauth.assert_not_called()

    @patch("requests.adapters.HTTPAdapter.send")
    def test_get_email__request_timeout(self, m_send: NonCallableMock) -> None:
        """Test the access token request for the email address has a timeout."""
        m_send.side_effect = requests.ConnectionError("No network")
        client = GLocalAuthenticationTokens(master_token=faker.master_token())
        with pytest.raises(requests.ConnectionError, match="No network"):
            client.get_email()
        m_send.assert_called_once()
        assert m_send.call_args.kwargs["timeout"] == REQUEST_TIMEOUT

    @patch("glocaltokens.client.perform_master_login")
    @patch("glocaltokens.client.perform_oauth")
    def test_get_access_token(
        self, m_perform_oauth: NonCallableMock, m_get_master_token: NonCallableMock
    ) -> None:
        """Test getting access token."""
        master_token = faker.master_token()
        m_get_master_token.return_value = {"Token": master_token}

        # No token in response
        m_perform_oauth.return_value = {"Error": "BadAuthentication"}
        with pytest.raises(AuthenticationError, match="no access token") as exc_info:
            self.client.get_access_token()
        assert exc_info.value.error == "BadAuthentication"
        assert self.client.access_token is None
        m_perform_oauth.assert_called_once_with(
            self.client.username,
            master_token,
            self.client.get_android_id(),
            app=ACCESS_TOKEN_APP_NAME,
            service=ACCESS_TOKEN_SERVICE,
            client_sig=ACCESS_TOKEN_CLIENT_SIGNATURE,
        )

        # An empty token in response
        m_perform_oauth.return_value = {"Auth": ""}
        with pytest.raises(AuthenticationError, match="no access token"):
            self.client.get_access_token()
        assert self.client.access_token is None

        # Reset mocks
        m_perform_oauth.reset_mock()

        # With token in response
        expected_access_token = faker.access_token()
        m_perform_oauth.return_value = {"Auth": expected_access_token}
        access_token = self.client.get_access_token()
        m_perform_oauth.assert_called_once_with(
            self.client.username,
            master_token,
            self.client.get_android_id(),
            app=ACCESS_TOKEN_APP_NAME,
            service=ACCESS_TOKEN_SERVICE,
            client_sig=ACCESS_TOKEN_CLIENT_SIGNATURE,
        )
        assert expected_access_token == access_token

        # Reset mocks
        m_perform_oauth.reset_mock()

        # Another request with non expired token must return the same token
        # (no new requests)
        access_token = self.client.get_access_token()
        assert expected_access_token == access_token
        assert m_perform_oauth.call_count == 0

        # Just before expiry the token is still used (no new request)
        self.client.access_token_date = datetime.now(UTC) - timedelta(
            seconds=ACCESS_TOKEN_DURATION - 1
        )
        self.client.get_access_token()
        assert m_perform_oauth.call_count == 0

        # Just after expiry a new token is requested
        self.client.access_token_date = datetime.now(UTC) - timedelta(
            seconds=ACCESS_TOKEN_DURATION + 1
        )
        self.client.get_access_token()
        assert m_perform_oauth.call_count == 1

    @patch("glocaltokens.client.grpc.ssl_channel_credentials")
    @patch("glocaltokens.client.grpc.access_token_call_credentials")
    @patch("glocaltokens.client.grpc.composite_channel_credentials")
    @patch("glocaltokens.client.grpc.secure_channel")
    @patch("glocaltokens.client.StructuresServiceStub")
    @patch("glocaltokens.client.GetHomeGraphRequest")
    @patch("glocaltokens.client.GLocalAuthenticationTokens.get_access_token")
    def test_get_homegraph(
        self,
        m_get_access_token: NonCallableMock,
        m_get_home_graph_request: NonCallableMock,
        m_structure_service_stub: NonCallableMock,
        m_secure_channel: NonCallableMock,
        m_composite_channel_credentials: NonCallableMock,
        m_access_token_call_credentials: NonCallableMock,
        m_ssl_channel_credentials: NonCallableMock,
    ) -> None:
        """Test getting homegraph."""
        # New homegraph
        self.client.get_homegraph()
        assert m_ssl_channel_credentials.call_count == 1
        assert m_access_token_call_credentials.call_count == 1
        assert m_composite_channel_credentials.call_count == 1
        assert m_secure_channel.call_count == 1
        assert m_structure_service_stub.call_count == 1
        assert m_get_home_graph_request.call_count == 1
        assert m_get_access_token.call_count == 1
        m_structure_service_stub.return_value.GetHomeGraph.assert_called_once_with(
            m_get_home_graph_request.return_value, timeout=REQUEST_TIMEOUT
        )

        # Another request with non expired homegraph must return the same homegraph
        # (no new requests)
        self.client.get_homegraph()
        assert m_ssl_channel_credentials.call_count == 1
        assert m_access_token_call_credentials.call_count == 1
        assert m_composite_channel_credentials.call_count == 1
        assert m_secure_channel.call_count == 1
        assert m_structure_service_stub.call_count == 1
        assert m_get_home_graph_request.call_count == 1
        assert m_get_access_token.call_count == 1

        # Just before expiry the homegraph is still used (no new requests)
        self.client.homegraph_date = datetime.now(UTC) - timedelta(
            seconds=HOMEGRAPH_DURATION - 1
        )
        self.client.get_homegraph()
        assert m_secure_channel.call_count == 1

        # Just after expiry a new homegraph is requested
        self.client.homegraph_date = datetime.now(UTC) - timedelta(
            seconds=HOMEGRAPH_DURATION + 1
        )
        self.client.get_homegraph()
        assert m_ssl_channel_credentials.call_count == 2
        assert m_access_token_call_credentials.call_count == 2
        assert m_composite_channel_credentials.call_count == 2
        assert m_secure_channel.call_count == 2
        assert m_structure_service_stub.call_count == 2
        assert m_get_home_graph_request.call_count == 2
        assert m_get_access_token.call_count == 2

    @patch("glocaltokens.client.GLocalAuthenticationTokens.get_access_token")
    @patch("glocaltokens.client.StructuresServiceStub")
    def test_get_homegraph_retries(
        self,
        m_structure_service_stub: NonCallableMock,
        m_get_access_token: NonCallableMock,
    ) -> None:
        """Test get_homegraph() gets a new access token when Google rejects it."""
        m_get_access_token.return_value = faker.word()
        rpc_error = fake_rpc_error(grpc.StatusCode.UNAUTHENTICATED)
        m_structure_service_stub.return_value.GetHomeGraph.side_effect = [
            rpc_error,
            mock.sentinel.homegraph,
        ]
        assert self.client.get_homegraph() is mock.sentinel.homegraph
        assert m_structure_service_stub.return_value.GetHomeGraph.call_count == 2
        assert m_get_access_token.call_count == 2

        # Google keeps rejecting the access token
        self.client.invalidate_homegraph()
        m_structure_service_stub.reset_mock()
        m_structure_service_stub.return_value.GetHomeGraph.side_effect = rpc_error
        with pytest.raises(HomegraphError, match="UNAUTHENTICATED") as exc_info:
            self.client.get_homegraph()
        assert exc_info.value.code == grpc.StatusCode.UNAUTHENTICATED
        assert exc_info.value.__cause__ is rpc_error
        assert m_structure_service_stub.return_value.GetHomeGraph.call_count == 3

        # The access token rejected on the last attempt isn't kept either
        self.client.access_token = faker.word()
        with pytest.raises(HomegraphError):
            self.client.get_homegraph(auth_attempts=1)
        assert self.client.access_token is None

    @patch("glocaltokens.client.GLocalAuthenticationTokens.get_access_token")
    @patch("glocaltokens.client.StructuresServiceStub")
    def test_get_homegraph__rpc_error(
        self,
        m_structure_service_stub: NonCallableMock,
        m_get_access_token: NonCallableMock,
    ) -> None:
        """Test other gRPC errors raise HomegraphError without a retry."""
        m_get_access_token.return_value = faker.word()
        for code in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
            with self.subTest(code=code):
                m_structure_service_stub.reset_mock()
                details = faker.sentence()
                rpc_error = fake_rpc_error(code, details)
                get_home_graph = m_structure_service_stub.return_value.GetHomeGraph
                get_home_graph.side_effect = rpc_error

                with pytest.raises(HomegraphError) as exc_info:
                    self.client.get_homegraph()
                assert exc_info.value.code == code
                assert exc_info.value.__cause__ is rpc_error
                assert str(exc_info.value) == (
                    f"Could not get the home graph: {code.name} ({details})"
                )
                assert get_home_graph.call_count == 1
                assert self.client.homegraph is None

    @patch("glocaltokens.client.GLocalAuthenticationTokens.get_homegraph")
    @patch("glocaltokens.client.LOGGER.warning")
    def test_get_google_devices(
        self, m_warning: NonCallableMock, m_get_homegraph: NonCallableMock
    ) -> None:
        """Test getting google devices."""
        # With just one device returned from homegraph
        fake_device_name = faker.word()
        fake_ip_address = faker.ipv4()
        homegraph_device = faker.homegraph_device(device_name=fake_device_name)
        m_get_homegraph.return_value.home.devices = [homegraph_device]

        # With no discover_devices, with no model_list
        google_devices = self.client.get_google_devices(
            disable_discovery=True,
            addresses={fake_device_name: fake_ip_address},
        )
        assert len(google_devices) == 1

        google_device = google_devices[0]
        self.assertDevice(google_device, homegraph_device)
        assert google_device.network_device is not None
        if google_device.network_device is not None:
            assert google_device.network_device.ip_address == fake_ip_address

        # With two devices returned from homegraph
        # but one device having the invalid token
        homegraph_device_valid = faker.homegraph_device(device_name=fake_device_name)
        homegraph_device_invalid = faker.homegraph_device()
        homegraph_device_invalid.local_auth_token = (
            faker.word()
        )  # setting invalid token intentionally
        # Note that we initialize the list with homegraph_device_invalid
        # which should be ignored
        m_get_homegraph.return_value.home.devices = [
            homegraph_device_invalid,
            homegraph_device_valid,
        ]
        google_devices = self.client.get_google_devices(
            disable_discovery=True,
            addresses={fake_device_name: fake_ip_address},
        )
        assert len(google_devices) == 1
        self.assertDevice(google_devices[0], homegraph_device_valid)
        # Devices without a Cast token, like Google Wifi and Nest Wifi routers,
        # are skipped quietly
        m_warning.assert_not_called()
        assert google_devices[0].network_device is not None
        if google_devices[0].network_device is not None:
            assert google_devices[0].network_device.ip_address == fake_ip_address

        # A device without a cloud device ID, manufacturer or software version
        # in the home graph
        homegraph_device.device_info.ClearField("agent_info")
        homegraph_device.hardware.ClearField("manufacturer")
        homegraph_device.hardware.ClearField("sw_version")
        m_get_homegraph.return_value.home.devices = [homegraph_device]
        google_devices = self.client.get_google_devices(
            disable_discovery=True,
            addresses={fake_device_name: fake_ip_address},
        )
        assert len(google_devices) == 1
        self.assertDevice(google_devices[0], homegraph_device)
        assert google_devices[0].as_dict()["cloud_device_id"] is None
        assert google_devices[0].as_dict()["manufacturer"] is None
        assert google_devices[0].as_dict()["software_version"] is None

    @patch("glocaltokens.client.discover_devices")
    @patch("glocaltokens.client.GLocalAuthenticationTokens.get_homegraph")
    def test_get_google_devices__homegraph_error(
        self, m_get_homegraph: NonCallableMock, m_discover_devices: NonCallableMock
    ) -> None:
        """Test the device methods raise the error of get_homegraph()."""
        m_get_homegraph.side_effect = HomegraphError(
            grpc.StatusCode.UNAVAILABLE, faker.sentence()
        )
        with pytest.raises(HomegraphError):
            self.client.get_google_devices()
        with pytest.raises(HomegraphError):
            self.client.get_google_devices_json()
        m_discover_devices.assert_not_called()

    @patch("glocaltokens.client.GLocalAuthenticationTokens.get_homegraph")
    def test_get_google_devices__invalid_addresses(
        self, m_get_homegraph: NonCallableMock
    ) -> None:
        """Test addresses that aren't a dict of IPv4 addresses raise ValueError."""
        for addresses in (
            {faker.word(): faker.ipv6()},
            {faker.word(): faker.word()},
            [faker.ipv4()],
        ):
            with self.subTest(addresses), pytest.raises(ValueError, match="addresses"):
                self.client.get_google_devices(
                    disable_discovery=True,
                    addresses=addresses,  # type: ignore[arg-type]
                )
        m_get_homegraph.assert_not_called()

    @patch("glocaltokens.client.GLocalAuthenticationTokens.get_homegraph")
    def test_get_google_devices__no_devices(
        self, m_get_homegraph: NonCallableMock
    ) -> None:
        """Test an account without devices gives an empty list."""
        m_get_homegraph.return_value.home.devices = []
        assert not self.client.get_google_devices(disable_discovery=True)
        assert self.client.get_google_devices_json(disable_discovery=True) == "[]"

    @patch("glocaltokens.client.discover_devices")
    @patch("glocaltokens.client.GLocalAuthenticationTokens.get_homegraph")
    def test_get_google_devices_discovered(
        self, m_get_homegraph: NonCallableMock, m_discover_devices: NonCallableMock
    ) -> None:
        """Test that a discovered device keeps its name from the home graph."""
        homegraph_device = faker.homegraph_device(device_name="Den speakers")
        m_get_homegraph.return_value.home.devices = [homegraph_device]
        # A speaker pair announces the name of its leading speaker
        network_device = NetworkDevice(
            "Den speaker left",
            faker.ipv4(),
            8009,
            homegraph_device.hardware.model,
            homegraph_device.device_info.agent_info.unique_id,
        )
        m_discover_devices.return_value = [network_device]

        google_devices = self.client.get_google_devices()
        assert len(google_devices) == 1
        self.assertDevice(google_devices[0], homegraph_device)
        assert google_devices[0].network_device == network_device
        assert google_devices[0].ip_address == network_device.ip_address

    @patch("glocaltokens.client.discover_devices")
    @patch("glocaltokens.client.GLocalAuthenticationTokens.get_homegraph")
    @patch("glocaltokens.client.LOGGER.warning")
    def test_get_google_devices__discovered_invalid_token(
        self,
        m_warning: NonCallableMock,
        m_get_homegraph: NonCallableMock,
        m_discover_devices: NonCallableMock,
    ) -> None:
        """Test that a discovered device with an invalid token is skipped with a warning."""
        homegraph_device = faker.homegraph_device()
        homegraph_device.local_auth_token = faker.word()
        m_get_homegraph.return_value.home.devices = [homegraph_device]
        m_discover_devices.return_value = [
            NetworkDevice(
                homegraph_device.device_name,
                faker.ipv4(),
                8009,
                homegraph_device.hardware.model,
                homegraph_device.device_info.agent_info.unique_id,
            )
        ]

        assert not self.client.get_google_devices()
        m_warning.assert_called_once()
        assert "local_auth_token isn't" in m_warning.call_args.args[0]

    @patch("glocaltokens.client.GLocalAuthenticationTokens.get_homegraph")
    @patch("glocaltokens.client.LOGGER.error")
    def test_get_google_devices__empty_device_name(
        self, m_error: NonCallableMock, m_get_homegraph: NonCallableMock
    ) -> None:
        """Test that a device without a name is skipped with an error."""
        homegraph_device = faker.homegraph_device()
        homegraph_device.device_name = ""
        m_get_homegraph.return_value.home.devices = [homegraph_device]

        assert not self.client.get_google_devices(disable_discovery=True)
        m_error.assert_called_once()
        assert "device_name must be provided" in m_error.call_args.args[0]

    @patch("glocaltokens.client.GLocalAuthenticationTokens.get_google_devices")
    def test_get_google_devices_json(
        self, m_get_google_devices: NonCallableMock
    ) -> None:
        """Test getting google devices as JSON."""
        device_id = str(faker.uuid4())
        device_name = faker.word()
        local_auth_token = faker.local_auth_token()
        ip_address = faker.ipv4()
        port = faker.port_number()
        hardware = faker.word()
        manufacturer = faker.word()
        software_version = faker.numerify("#.#.#")
        unique_id = faker.word()
        google_device = Device(
            device_id=device_id,
            device_name=device_name,
            local_auth_token=local_auth_token,
            network_device=NetworkDevice(
                device_name, ip_address, port, hardware, unique_id
            ),
            hardware=hardware,
            manufacturer=manufacturer,
            software_version=software_version,
            cloud_device_id=unique_id,
        )
        m_get_google_devices.return_value = [google_device]

        json_string = self.client.get_google_devices_json(
            disable_discovery=True, discovery_timeout=5
        )
        assert m_get_google_devices.call_count == 1
        assert m_get_google_devices.call_args.kwargs["discovery_timeout"] == 5
        received_json = json.loads(json_string)
        received_device = received_json[0]
        assert received_device["device_name"] == device_name
        assert received_device["hardware"] == hardware
        assert received_device["manufacturer"] == manufacturer
        assert received_device["software_version"] == software_version
        assert received_device["cloud_device_id"] == unique_id
        assert received_device["local_auth_token"] == local_auth_token
        assert received_device["network_device"]["port"] == port
        assert received_device["network_device"]["ip"] == ip_address

    def test_username_escaping(self) -> None:
        """Test that plus sign is escaped."""
        assert self.client._escape_username("login@domain.com") == "login@domain.com"
        assert (
            self.client._escape_username("login+tag@domain.com")
            == "login%2Btag@domain.com"
        )
        assert self.client._escape_username("login") == "login"
        # Such account should be impossible to create.
        assert self.client._escape_username("login+tag") == "login%2Btag"


class DeviceClientTests(TypeAssertions, TestCase):
    """Device specific unittests."""

    def test_initialization(self) -> None:
        """Test that a Device stores its arguments as given."""
        device_id = str(faker.uuid4())
        device_name = faker.word()
        local_auth_token = faker.local_auth_token()
        network_device = NetworkDevice(
            faker.word(), faker.ipv4(), faker.port_number(), faker.word(), faker.word()
        )
        hardware = faker.word()
        manufacturer = faker.word()
        software_version = faker.numerify("#.#.#")
        cloud_device_id = faker.word()

        device = Device(
            device_id=device_id,
            device_name=device_name,
            local_auth_token=local_auth_token,
            network_device=network_device,
            hardware=hardware,
            manufacturer=manufacturer,
            software_version=software_version,
            cloud_device_id=cloud_device_id,
        )
        assert device.device_id == device_id
        assert device.device_name == device_name
        assert device.local_auth_token == local_auth_token
        assert device.network_device == network_device
        assert device.hardware == hardware
        assert device.manufacturer == manufacturer
        assert device.software_version == software_version
        assert device.cloud_device_id == cloud_device_id
        assert device.ip_address == network_device.ip_address
        assert device.port == network_device.port

        # Without a network device, and with a token get_google_devices() skips
        local_auth_token = faker.word()
        device = Device(
            device_id=device_id,
            device_name=device_name,
            local_auth_token=local_auth_token,
        )
        assert device.local_auth_token == local_auth_token
        assert device.as_dict()["network_device"] == {"ip": None, "port": None}
