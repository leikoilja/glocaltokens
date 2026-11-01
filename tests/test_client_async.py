"""Tests of the client's async methods, with invented data on loopback servers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import ssl
from typing import TYPE_CHECKING, TypedDict, Unpack, override
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, NonCallableMock, patch

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
from faker import Faker
from ghome_foyer_api.api_pb2 import HomeGraph  # pylint: disable=no-name-in-module
from google.protobuf.message import DecodeError
import grpc
import pytest
import requests
import trustme
from yarl import URL

from glocaltokens.client import (
    _GOOGLE_SSL_CONTEXT,
    GLocalAuthenticationTokens,
    _google_ssl_context,
)
from glocaltokens.const import (
    ACCESS_TOKEN_DURATION,
    GOOGLE_HOME_FOYER_API,
    HOMEGRAPH_DURATION,
)
from glocaltokens.exceptions import AuthenticationError, HomegraphError
from glocaltokens.scanner import NetworkDevice
from tests.factory.providers import HomegraphProvider

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

faker = Faker()
faker.add_provider(HomegraphProvider)


def text(body: str, status: int = 200) -> Callable[[], Awaitable[web.Response]]:
    """Return an answer of plain text, as Google's login service gives."""

    async def answer() -> web.Response:
        return web.Response(text=body, status=status)

    return answer


def user_info(email: str) -> Callable[[], Awaitable[web.Response]]:
    """Return a userinfo answer with a verified email address."""

    async def answer() -> web.Response:
        return web.json_response({"email": email, "email_verified": True})

    return answer


class Credentials(TypedDict, total=False):
    """The credentials of a client."""

    username: str
    password: str
    master_token: str
    oauth_token: str


@dataclass
class Received:
    """A request the fake Google received."""

    path: str
    headers: Mapping[str, str]
    body: bytes
    # The ALPN protocol agreed for an HTTPS request
    alpn: str | None


class FakeGoogle:
    """A loopback server answering as Google's login and userinfo endpoints.

    Each request gets the next answer queued for its path.
    """

    def __init__(self) -> None:
        """Create a server with no answers queued."""
        self.answers: dict[str, list[Callable[[], Awaitable[web.StreamResponse]]]] = {}
        self.received: list[Received] = []
        self.request_received = asyncio.Event()
        app = web.Application()
        app.router.add_route("*", "/{path:.*}", self._handle)
        self.server = TestServer(app, host="127.0.0.1")

    async def start(self, ssl_context: ssl.SSLContext | None = None) -> None:
        """Start listening, with TLS if a context is given."""
        await self.server.start_server(ssl=ssl_context)

    def url(self, path: str) -> str:
        """Return the URL of a path on this server."""
        return str(self.server.make_url(path))

    def queue(
        self, path: str, *answers: Callable[[], Awaitable[web.StreamResponse]]
    ) -> None:
        """Queue answers for the requests to a path."""
        self.answers.setdefault(path, []).extend(answers)

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        ssl_object = (
            request.transport.get_extra_info("ssl_object")
            if request.transport
            else None
        )
        self.received.append(
            Received(
                request.path,
                dict(request.headers),
                await request.read(),
                ssl_object.selected_alpn_protocol() if ssl_object else None,
            )
        )
        self.request_received.set()
        return await self.answers[request.path].pop(0)()

    @property
    def paths(self) -> list[str]:
        """Return the paths of the requests received, in order."""
        return [received.path for received in self.received]


class AsyncClientTestCase(IsolatedAsyncioTestCase):
    """Run each test with a fake Google in place of the real endpoints."""

    @override
    async def asyncSetUp(self) -> None:
        """Start the fake Google and a caller's session."""
        self.google = FakeGoogle()
        await self.google.start()
        self.addAsyncCleanup(self.google.server.close)
        self.session = aiohttp.ClientSession()
        self.addAsyncCleanup(self.session.close)
        for target, path in (
            ("gpsoauth.AUTH_URL", "/auth"),
            ("glocaltokens.client.USERINFO_URL", "/userinfo"),
        ):
            patcher = patch(target, self.google.url(path))
            patcher.start()
            self.addCleanup(patcher.stop)

    def client(
        self, android_id: str | None = None, **credentials: Unpack[Credentials]
    ) -> GLocalAuthenticationTokens:
        """Return a client that uses the caller's session."""
        return GLocalAuthenticationTokens(
            android_id=android_id, session=self.session, **credentials
        )


class SignInTests(AsyncClientTestCase):
    """Getting master and access tokens and the email address."""

    async def test_requests_match_gpsoauth(self) -> None:
        """Each async exchange sends Google the request that gpsoauth sends.

        gpsoauth is the reference for these requests, as Google refuses logins
        whose requests differ in ways it doesn't document.
        """
        # A plus sign, which is escaped, and base64 with "-", "_" and "="
        username = "first.last+home@example.com"
        signature = b"AFcb4K-x_y=="
        android_id = faker.hexify("^" * 16)
        master_token = faker.master_token()
        credentials: dict[str, Credentials] = {
            "password": {"username": username, "password": faker.password()},
            "oauth_token": {"username": username, "oauth_token": "oauth2_4/invented"},
            "access token": {"master_token": master_token},
            "email": {"master_token": master_token},
        }
        token_answers = {
            "password": f"Token={master_token}\n",
            "oauth_token": f"Token={master_token}\n",
            "access token": "Auth=ya29.invented\n",
            "email": "Auth=ya29.invented\n",
        }
        for case, kwargs in credentials.items():
            with self.subTest(case=case):
                response = requests.Response()
                response.status_code = 200
                # pylint: disable-next=protected-access
                response._content = token_answers[case].encode()  # noqa: SLF001
                response.encoding = "utf-8"
                with (
                    patch(
                        "gpsoauth.google.construct_signature", return_value=signature
                    ),
                    patch(
                        "requests.adapters.HTTPAdapter.send", return_value=response
                    ) as m_send,
                ):
                    sync_client = GLocalAuthenticationTokens(
                        android_id=android_id, **kwargs
                    )
                    # Only the token exchange; the userinfo request comes after it
                    if case == "email":
                        with patch("glocaltokens.client.requests.get") as m_get:
                            m_get.return_value.ok = False
                            sync_client.get_email()
                    elif case == "access token":
                        sync_client.get_access_token()
                    else:
                        sync_client.get_master_token()
                sent = m_send.call_args_list[0].args[0]

                self.google.received.clear()
                self.google.queue("/auth", text(token_answers[case]))
                self.google.queue("/userinfo", text("", status=401))
                with patch(
                    "gpsoauth.google.construct_signature", return_value=signature
                ):
                    client = self.client(android_id=android_id, **kwargs)
                    if case == "email":
                        await client.async_get_email()
                    elif case == "access token":
                        await client.async_get_access_token()
                    else:
                        await client.async_get_master_token()
                received = self.google.received[0]

                assert received.body == sent.body.encode()
                for header in ("Content-Type", "User-Agent", "Accept-Encoding"):
                    assert received.headers[header] == sent.headers[header]

    async def test_get_master_token(self) -> None:
        """A master token comes from the oauth_token, else from the password."""
        master_token = faker.master_token()
        email = faker.email()
        both = {
            "username": faker.email(),
            "password": faker.password(),
            "oauth_token": "oauth2_4/invented",
        }
        self.google.queue("/auth", text(f"Token={master_token}\nEmail={email}\n"))
        client = self.client(**both)
        assert await client.async_get_master_token() == master_token
        assert client.master_token == master_token
        assert client.email == email
        assert b"Token=oauth2_4%2Finvented" in self.google.received[0].body
        assert b"EncryptedPasswd" not in self.google.received[0].body

        # A stored master token needs no request
        assert await client.async_get_master_token() == master_token
        assert len(self.google.received) == 1

        # Without an oauth_token, the password
        self.google.queue("/auth", text(f"Token={master_token}\n"))
        client = self.client(username=both["username"], password=both["password"])
        assert await client.async_get_master_token() == master_token
        assert b"EncryptedPasswd=" in self.google.received[1].body
        assert client.email is None

    async def test_get_master_token__refused(self) -> None:
        """Google's reason for giving no master token is kept."""
        self.google.queue("/auth", text("Error=BadAuthentication\n", status=403))
        client = self.client(oauth_token="oauth2_4/invented")
        with pytest.raises(AuthenticationError, match="no master token") as exc_info:
            await client.async_get_master_token()
        assert exc_info.value.error == "BadAuthentication"
        assert client.master_token is None

    async def test_get_master_token__no_request_possible(self) -> None:
        """Without a way to get a master token, or with too long a password, nothing is sent."""
        client = self.client(master_token=faker.master_token())
        client.invalidate_master_token()
        with pytest.raises(AuthenticationError, match="No master token"):
            await client.async_get_master_token()

        # gpsoauth's RSA key encrypts at most 86 bytes of username and password
        client = self.client(username=faker.email(), password="p" * 200)
        with pytest.raises(AuthenticationError, match="too long together") as exc_info:
            await client.async_get_master_token()
        assert isinstance(exc_info.value.__cause__, ValueError)
        assert not self.google.received

    async def test_get_access_token(self) -> None:
        """An access token is fetched once an hour with the master token."""
        self.google.queue(
            "/auth", text("Auth=ya29.first\n"), text("Auth=ya29.second\n")
        )
        client = self.client(master_token=faker.master_token())
        assert await client.async_get_access_token() == "ya29.first"
        assert client.access_token_date is not None

        # Just before expiry, the stored one
        client.access_token_date = datetime.now(UTC) - timedelta(
            seconds=ACCESS_TOKEN_DURATION - 1
        )
        assert await client.async_get_access_token() == "ya29.first"
        assert len(self.google.received) == 1

        # Just after expiry, a new one
        client.access_token_date = datetime.now(UTC) - timedelta(
            seconds=ACCESS_TOKEN_DURATION + 1
        )
        assert await client.async_get_access_token() == "ya29.second"
        assert len(self.google.received) == 2

        # Google giving none
        client.invalidate_access_token()
        self.google.queue("/auth", text("Error=BadAuthentication\n", status=403))
        with pytest.raises(AuthenticationError, match="no access token"):
            await client.async_get_access_token()

    async def test_get_email(self) -> None:
        """The userinfo endpoint gives the verified address of a master token's account."""
        email = faker.email()
        self.google.queue("/auth", text("Auth=ya29.email\n"))
        self.google.queue("/userinfo", user_info(email))
        client = self.client(master_token=faker.master_token())
        assert await client.async_get_email() == email
        assert self.google.received[1].headers["Authorization"] == "Bearer ya29.email"

        # An address Google hasn't verified
        async def unverified() -> web.Response:
            return web.json_response({"email": email, "email_verified": "false"})

        self.google.queue("/auth", text("Auth=ya29.email\n"))
        self.google.queue("/userinfo", unverified)
        assert await client.async_get_email() is None

        # No access token for the address
        self.google.queue("/auth", text("Error=BadAuthentication\n", status=403))
        assert await client.async_get_email() is None
        assert self.google.paths[-1] == "/auth"

    async def test_get_email__from_master_token_answer(self) -> None:
        """The address Google gave with the master token needs no request."""
        email = faker.email()
        self.google.queue(
            "/auth", text(f"Token={faker.master_token()}\nEmail={email}\n")
        )
        client = self.client(oauth_token="oauth2_4/invented")
        assert await client.async_get_email() == email
        assert self.google.paths == ["/auth"]

    async def test_get_email__userinfo_not_json(self) -> None:
        """Userinfo answers that aren't JSON raise the decoding error."""

        async def malformed() -> web.Response:
            return web.Response(text='{"email": ', content_type="application/json")

        self.google.queue("/auth", text("Auth=ya29.email\n"))
        self.google.queue("/userinfo", malformed)
        client = self.client(master_token=faker.master_token())
        with pytest.raises(json.JSONDecodeError):
            await client.async_get_email()

        async def html() -> web.Response:
            return web.Response(text="<html></html>", content_type="text/html")

        self.google.queue("/auth", text("Auth=ya29.email\n"))
        self.google.queue("/userinfo", html)
        with pytest.raises(aiohttp.ContentTypeError):
            await client.async_get_email()


class SessionTests(AsyncClientTestCase):
    """How the async methods use the caller's session, or their own."""

    async def test_answers_read_whatever_the_session_raises_for(self) -> None:
        """A session that raises for error statuses doesn't change what callers get."""

        async def raise_any(response: aiohttp.ClientResponse) -> None:
            raise AssertionError(f"Session callback ran for {response.status}")

        for raise_for_status in (True, raise_any):
            with self.subTest(raise_for_status=raise_for_status):
                async with aiohttp.ClientSession(
                    raise_for_status=raise_for_status
                ) as session:
                    # 403 is Google refusing the login, read as an answer
                    self.google.queue(
                        "/auth", text("Error=BadAuthentication\n", status=403)
                    )
                    client = GLocalAuthenticationTokens(
                        oauth_token="oauth2_4/invented", session=session
                    )
                    with pytest.raises(AuthenticationError) as exc_info:
                        await client.async_get_master_token()
                    assert exc_info.value.error == "BadAuthentication"

                    # 5xx and 429 mean "try later"
                    for status in (503, 429):
                        self.google.queue("/auth", text("<html>Busy</html>", status))
                        with pytest.raises(aiohttp.ClientResponseError) as busy:
                            await client.async_get_master_token()
                        assert busy.value.status == status

                    # A refused userinfo request gives no address
                    client.master_token = faker.master_token()
                    self.google.queue("/auth", text("Auth=ya29.email\n"))
                    self.google.queue("/userinfo", text("", status=401))
                    assert await client.async_get_email() is None

    async def test_caller_middleware_applies(self) -> None:
        """The caller's middleware sees the requests, such as a redirect it blocks."""

        class RedirectBlockedError(aiohttp.ClientError):
            """The invented middleware blocked a redirect."""

        async def block_redirects(
            request: aiohttp.ClientRequest, handler: aiohttp.ClientHandlerType
        ) -> aiohttp.ClientResponse:
            response = await handler(request)
            if 300 <= response.status < 400:
                response.close()
                raise RedirectBlockedError(response.headers["Location"])
            return response

        async def redirect() -> web.StreamResponse:
            return web.Response(
                status=307, headers={"Location": self.google.url("/elsewhere")}
            )

        self.google.queue("/auth", redirect)
        async with aiohttp.ClientSession(middlewares=(block_redirects,)) as session:
            client = GLocalAuthenticationTokens(
                oauth_token="oauth2_4/invented", session=session
            )
            with pytest.raises(RedirectBlockedError):
                await client.async_get_master_token()
        assert self.google.paths == ["/auth"]

        # Without the middleware, the redirect is followed, as requests does
        master_token = faker.master_token()
        self.google.queue("/auth", redirect)
        self.google.queue("/elsewhere", text(f"Token={master_token}\n"))
        client = self.client(oauth_token="oauth2_4/invented")
        assert await client.async_get_master_token() == master_token
        assert self.google.paths == ["/auth", "/auth", "/elsewhere"]

    async def test_caller_session_stays_open(self) -> None:
        """The caller's session is open after answers, errors and cancellation."""
        client = self.client(oauth_token="oauth2_4/invented")
        self.google.queue("/auth", text("<html>Busy</html>", 503))
        with pytest.raises(aiohttp.ClientResponseError):
            await client.async_get_master_token()
        assert not self.session.closed

        await self._cancel_while_google_answers(client)
        assert not self.session.closed

        master_token = faker.master_token()
        self.google.queue("/auth", text(f"Token={master_token}\n"))
        assert await client.async_get_master_token() == master_token
        assert not self.session.closed

    async def test_own_session_closed(self) -> None:
        """Without a session, each request has its own, closed when it ends."""
        sessions: list[aiohttp.ClientSession] = []
        new_session = aiohttp.ClientSession

        def track(*, trust_env: bool) -> aiohttp.ClientSession:
            session = new_session(trust_env=trust_env)
            sessions.append(session)
            return session

        client = GLocalAuthenticationTokens(oauth_token="oauth2_4/invented")
        with patch("aiohttp.ClientSession", side_effect=track) as m_session:
            self.google.queue("/auth", text("<html>Busy</html>", 503))
            with pytest.raises(aiohttp.ClientResponseError):
                await client.async_get_master_token()
            await self._cancel_while_google_answers(client)
            self.google.queue("/auth", text(f"Token={faker.master_token()}\n"))
            await client.async_get_master_token()
        assert len(sessions) == 3
        assert all(session.closed for session in sessions)
        # Like requests, it follows the proxy environment variables
        assert all(
            call.kwargs == {"trust_env": True} for call in m_session.call_args_list
        )

    async def _cancel_while_google_answers(
        self, client: GLocalAuthenticationTokens
    ) -> None:
        """Cancel getting the master token while Google is answering."""
        never = asyncio.Event()

        async def hang() -> web.StreamResponse:
            await never.wait()
            raise AssertionError("never answers")

        self.google.queue("/auth", hang)
        self.google.request_received.clear()
        task = asyncio.create_task(client.async_get_master_token())
        await self.google.request_received.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert client.master_token is None

    async def test_cookies_shared_with_caller_jar(self) -> None:
        """The caller's cookies go with the requests, and Google's are kept in its jar.

        This records what the caller's session does; glocaltokens doesn't
        change the jar.
        """
        jar = aiohttp.CookieJar(unsafe=True)
        jar.update_cookies({"seeded": "invented-a"}, URL(self.google.url("/")))

        async def set_cookie() -> web.StreamResponse:
            response = web.Response(text=f"Token={faker.master_token()}\n")
            response.set_cookie("fresh", "invented-b")
            return response

        self.google.queue("/auth", set_cookie)
        async with aiohttp.ClientSession(cookie_jar=jar) as session:
            client = GLocalAuthenticationTokens(
                oauth_token="oauth2_4/invented", session=session
            )
            await client.async_get_master_token()
        assert self.google.received[0].headers["Cookie"] == "seeded=invented-a"
        assert {cookie.key for cookie in jar} == {"seeded", "fresh"}


class TLSTests(IsolatedAsyncioTestCase):
    """The TLS settings of the requests to Google."""

    def test_settings(self) -> None:
        """Google's certificate is checked, and session tickets are allowed."""
        assert _GOOGLE_SSL_CONTEXT.verify_mode == ssl.CERT_REQUIRED
        assert _GOOGLE_SSL_CONTEXT.check_hostname
        assert not _GOOGLE_SSL_CONTEXT.options & ssl.OP_NO_TICKET  # pylint: disable=no-member

    async def test_certificate_checked_on_unchecked_session(self) -> None:
        """A session that checks no certificates still gets Google's checked.

        With a certificate the settings trust, the login offers no ALPN, which
        gpsoauth found Google refuses logins for.
        """
        ca = trustme.CA()
        server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ca.issue_cert("127.0.0.1").configure_cert(server_context)
        server_context.set_alpn_protocols(["http/1.1"])
        google = FakeGoogle()
        await google.start(server_context)
        self.addAsyncCleanup(google.server.close)
        master_token = faker.master_token()
        google.queue("/auth", text(f"Token={master_token}\n"))

        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=False)
        ) as session:
            client = GLocalAuthenticationTokens(
                oauth_token="oauth2_4/invented", session=session
            )
            with patch("gpsoauth.AUTH_URL", google.url("/auth")):
                # An invented CA isn't trusted, whatever the session checks
                with pytest.raises(aiohttp.ClientConnectorCertificateError):
                    await client.async_get_master_token()
                assert not google.received

                trusting = _google_ssl_context()
                ca.configure_trust(trusting)
                with patch("glocaltokens.client._GOOGLE_SSL_CONTEXT", trusting):
                    assert await client.async_get_master_token() == master_token
        assert google.received[0].alpn is None


class HomeGraphServer:
    """An in-process gRPC server answering the home graph request with invented data."""

    def __init__(self) -> None:
        """Create a server with no answers queued."""
        self.answers: list[
            Callable[[grpc.aio.ServicerContext[bytes, bytes]], Awaitable[bytes]]
        ] = []
        self.calls = 0
        self.call_received = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.channels: list[grpc.aio.Channel] = []
        self.port = 0
        self.server = grpc.aio.server()

    async def start(self) -> None:
        """Start listening on loopback."""
        handler = grpc.method_handlers_generic_handler(
            "google.internal.home.foyer.v1.StructuresService",
            {"GetHomeGraph": grpc.unary_unary_rpc_method_handler(self._handle)},
        )
        self.server.add_generic_rpc_handlers((handler,))
        self.port = self.server.add_insecure_port("127.0.0.1:0")
        await self.server.start()

    def queue(self, *answers: HomeGraph | bytes | grpc.StatusCode) -> None:
        """Queue a home graph, raw bytes or an error code for the next calls."""
        for answer in answers:
            self.answers.append(self._answer(answer))

    @staticmethod
    def _answer(
        answer: HomeGraph | bytes | grpc.StatusCode,
    ) -> Callable[[grpc.aio.ServicerContext[bytes, bytes]], Awaitable[bytes]]:
        async def respond(context: grpc.aio.ServicerContext[bytes, bytes]) -> bytes:
            if isinstance(answer, grpc.StatusCode):
                await context.abort(answer, f"Invented {answer.name}")
            if isinstance(answer, HomeGraph):
                return answer.SerializeToString()
            assert isinstance(answer, bytes)
            return answer

        return respond

    def hold(self) -> None:
        """Make the next call wait until it is cancelled."""

        async def wait(_context: grpc.aio.ServicerContext[bytes, bytes]) -> bytes:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
            raise AssertionError("never answers")

        self.answers.append(wait)

    def secure_channel(
        self, _target: str, _credentials: grpc.ChannelCredentials
    ) -> grpc.aio.Channel:
        """Return a channel to this server, in place of Google's secure one."""
        channel = grpc.aio.insecure_channel(f"127.0.0.1:{self.port}")
        self.channels.append(channel)
        return channel

    async def _handle(
        self, _request: bytes, context: grpc.aio.ServicerContext[bytes, bytes]
    ) -> bytes:
        self.calls += 1
        self.call_received.set()
        return await self.answers.pop(0)(context)


class HomeGraphTestCase(IsolatedAsyncioTestCase):
    """Run each test with a home graph server in place of Google's."""

    @override
    async def asyncSetUp(self) -> None:
        """Start the home graph server, and give the client invented access tokens."""
        self.google = HomeGraphServer()
        await self.google.start()
        self.addAsyncCleanup(self.google.server.stop, None)
        channel_patcher = patch(
            "grpc.aio.secure_channel", side_effect=self.google.secure_channel
        )
        self.m_secure_channel = channel_patcher.start()
        self.addCleanup(channel_patcher.stop)
        self.access_tokens = [f"ya29.invented-{n}" for n in range(5)]
        self.client = GLocalAuthenticationTokens(master_token=faker.master_token())
        token_patcher = patch.object(
            self.client, "async_get_access_token", side_effect=self.access_tokens
        )
        self.m_access_token: AsyncMock = token_patcher.start()
        self.addCleanup(token_patcher.stop)


class HomeGraphTests(HomeGraphTestCase):
    """Fetching the home graph over grpc.aio."""

    async def test_get_home_graph(self) -> None:
        """One request gives both forms, and the sync methods share them."""
        home_device = faker.homegraph_device()
        office_device = faker.homegraph_device()
        graph = HomeGraph(
            homes=[
                HomeGraph.Home(id="home-1", display_name="Home", devices=[home_device]),
                HomeGraph.Home(
                    id="home-2", display_name="Office", devices=[office_device]
                ),
            ]
        )
        self.google.queue(graph)
        with patch(
            "grpc.access_token_call_credentials",
            wraps=grpc.access_token_call_credentials,
        ) as m_token_credentials:
            assert await self.client.async_get_home_graph() == graph
        self.m_secure_channel.assert_called_once()
        assert self.m_secure_channel.call_args.args[0] == GOOGLE_HOME_FOYER_API
        m_token_credentials.assert_called_once_with(self.access_tokens[0])

        # The merged form has the last home's name with every home's devices
        homegraph = await self.client.async_get_homegraph()
        assert homegraph.home.home_name == "Office"
        assert len(homegraph.home.devices) == 2
        assert self.client.get_home_graph() is self.client.home_graph
        assert self.google.calls == 1

        # A day later, a new one
        self.client.homegraph_date = datetime.now(UTC) - timedelta(
            seconds=HOMEGRAPH_DURATION + 1
        )
        self.google.queue(HomeGraph())
        assert await self.client.async_get_home_graph() == HomeGraph()
        assert self.google.calls == 2

    async def test_get_home_graph__new_access_token(self) -> None:
        """A rejected access token is replaced, up to auth_attempts times."""
        graph = HomeGraph(homes=[HomeGraph.Home(display_name="Home")])
        self.google.queue(grpc.StatusCode.UNAUTHENTICATED, graph)
        assert await self.client.async_get_home_graph() == graph
        assert self.m_access_token.await_count == 2

        self.client.invalidate_homegraph()
        self.google.queue(*[grpc.StatusCode.UNAUTHENTICATED] * 3)
        with pytest.raises(HomegraphError, match="UNAUTHENTICATED") as exc_info:
            await self.client.async_get_home_graph()
        assert exc_info.value.code == grpc.StatusCode.UNAUTHENTICATED
        assert isinstance(exc_info.value.__cause__, grpc.RpcError)
        assert self.google.calls == 5
        assert self.client.home_graph is None

    async def test_get_home_graph__errors(self) -> None:
        """Other failures raise HomegraphError with their code, without a retry."""
        self.google.queue(grpc.StatusCode.UNAVAILABLE)
        with pytest.raises(HomegraphError) as exc_info:
            await self.client.async_get_home_graph()
        assert exc_info.value.code == grpc.StatusCode.UNAVAILABLE
        assert exc_info.value.details == "Invented UNAVAILABLE"

        # A string with bad UTF-8, in a field only HomeGraph names
        self.google.queue(b"\x12\x07\x1a\x05\x3a\x03\x32\x01\xff")
        with pytest.raises(HomegraphError) as exc_info:
            await self.client.async_get_home_graph()
        assert exc_info.value.code == grpc.StatusCode.INTERNAL
        assert isinstance(exc_info.value.__cause__, DecodeError)

        # No answer in time
        self.google.hold()
        with (
            patch("glocaltokens.client.REQUEST_TIMEOUT", 0.2),
            pytest.raises(HomegraphError) as exc_info,
        ):
            await self.client.async_get_home_graph()
        assert exc_info.value.code == grpc.StatusCode.DEADLINE_EXCEEDED
        assert self.google.calls == 3
        assert self.m_access_token.await_count == 3
        assert self.client.home_graph is None

    async def test_get_home_graph__cancelled(self) -> None:
        """Cancelling cancels the request and closes its channel, storing nothing."""
        self.google.hold()
        task = asyncio.create_task(self.client.async_get_home_graph())
        await self.google.call_received.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(self.google.cancelled.wait(), 5)
        # Its channel takes no more calls
        call: grpc.aio.UnaryUnaryMultiCallable[bytes, bytes] = self.google.channels[
            0
        ].unary_unary("/test.Svc/Call")
        with pytest.raises(grpc.aio.UsageError):
            await call(b"")
        assert self.client.home_graph is None
        assert self.client.homegraph is None


class DevicesTests(HomeGraphTestCase):
    """The device list and the home graph it comes from."""

    async def test_full_membership(self) -> None:
        """Devices left out of the list are still in the home graph returned with it."""
        listed = faker.homegraph_device()
        no_token = faker.homegraph_device()
        no_token.local_auth_token = ""
        # Such as a Google Wifi router, whose token isn't a Cast device's
        router = faker.homegraph_device()
        router.local_auth_token = "invented-router-token"
        speaker_group = faker.homegraph_device()
        graph = HomeGraph(
            homes=[
                HomeGraph.Home(
                    id="home-1", display_name="Home", devices=[listed, no_token]
                ),
                HomeGraph.Home(id="home-2", display_name="Office", devices=[router]),
            ],
            unassigned_devices=[speaker_group],
        )
        self.google.queue(graph)
        devices, home_graph = await self.client.async_get_google_devices_and_home_graph(
            disable_discovery=True
        )
        assert [device.device_id for device in devices] == [listed.id.device_id]
        assert (devices[0].home_id, devices[0].home_name) == ("home-1", "Home")
        assert home_graph == graph
        assert home_graph is self.client.home_graph

        # The stored home graph is used for a day, unless a new one is asked for
        assert await self.client.async_get_google_devices(disable_discovery=True)
        assert self.google.calls == 1
        self.google.queue(HomeGraph())
        assert not await self.client.async_get_google_devices(
            disable_discovery=True, force_homegraph_reload=True
        )
        assert self.google.calls == 2

    async def test_home_filter(self) -> None:
        """Only the devices of the home asked for, and the whole home graph."""
        home_device = faker.homegraph_device()
        office_device = faker.homegraph_device()
        graph = HomeGraph(
            homes=[
                HomeGraph.Home(id="home-1", display_name="Home", devices=[home_device]),
                HomeGraph.Home(
                    id="home-2", display_name="Office", devices=[office_device]
                ),
            ]
        )
        self.google.queue(graph)
        devices, home_graph = await self.client.async_get_google_devices_and_home_graph(
            disable_discovery=True, home_id="home-2"
        )
        assert [device.device_id for device in devices] == [office_device.id.device_id]
        assert home_graph == graph

    async def test_discovery(self) -> None:
        """Discovery runs with the caller's arguments and gives devices their addresses."""
        device = faker.homegraph_device()
        self.google.queue(HomeGraph(homes=[HomeGraph.Home(devices=[device])]))
        found = NetworkDevice(
            name=device.display_name,
            ip_address="192.0.2.10",
            port=8009,
            model=device.hardware.model,
            unique_id=device.id.agent_info.unique_id,
        )
        zeroconf_instance = NonCallableMock(name="Zeroconf")
        with patch(
            "glocaltokens.client.async_discover_devices", return_value=[found]
        ) as m_discover:
            devices = await self.client.async_get_google_devices(
                models_list=[device.hardware.model],
                zeroconf_instance=zeroconf_instance,
                discovery_timeout=1.5,
            )
        m_discover.assert_awaited_once_with(
            [device.hardware.model], timeout=1.5, zeroconf_instance=zeroconf_instance
        )
        assert (devices[0].ip_address, devices[0].port) == ("192.0.2.10", 8009)

    async def test_invalid_addresses(self) -> None:
        """Addresses that aren't IPv4 are refused before any request."""
        with pytest.raises(ValueError, match="Invalid dictionary structure"):
            await self.client.async_get_google_devices(addresses={"Kitchen": "kitchen"})
        assert self.google.calls == 0

    async def test_home_graph_replaced_during_discovery(self) -> None:
        """The home graph returned is the list's, whatever replaces the stored one meanwhile."""
        graph_b = HomeGraph(homes=[HomeGraph.Home(devices=[faker.homegraph_device()])])

        async def replace() -> None:
            self.google.queue(graph_b)
            await self.client.async_get_google_devices_and_home_graph(
                disable_discovery=True, force_homegraph_reload=True
            )

        async def drop() -> None:
            self.client.invalidate_homegraph()

        for meanwhile, stored in ((replace, graph_b), (drop, None)):
            with self.subTest(meanwhile=meanwhile.__name__):
                await self._check_list_keeps_its_graph(meanwhile, stored)

    async def _check_list_keeps_its_graph(
        self, meanwhile: Callable[[], Awaitable[None]], stored: HomeGraph | None
    ) -> None:
        """Run meanwhile() while a device list is being discovered, and check its graph."""
        self.client.invalidate_homegraph()
        graph_a = HomeGraph(homes=[HomeGraph.Home(devices=[faker.homegraph_device()])])
        self.google.queue(graph_a)
        discovering = asyncio.Event()
        release = asyncio.Event()

        async def discover(*_args: object, **_kwargs: object) -> list[NetworkDevice]:
            discovering.set()
            await release.wait()
            return []

        with patch("glocaltokens.client.async_discover_devices", side_effect=discover):
            first = asyncio.create_task(
                self.client.async_get_google_devices_and_home_graph()
            )
            await discovering.wait()
            await meanwhile()
            release.set()
            devices, home_graph = await first
        assert [device.device_id for device in devices] == [
            graph_a.homes[0].devices[0].id.device_id
        ]
        assert home_graph == graph_a
        assert self.client.home_graph == stored
