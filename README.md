[![GitHub Workflow Status][workflow-shield]][workflow]
[![PyPI][pypi-shield]][pypi]
[![Downloads][pepy-shield]][pepy]
[![Pre-commit][pre-commit-shield]][pre-commit]
[![GitHub Activity][commits-shield]][commits]

# Google Home local authentication token extraction

Python package to extract Google Home devices local authentication tokens from Google servers.
These local authentication tokens are needed to control Google Home devices
(See [@rithvikvibhu](https://github.com/rithvikvibhu)'s [Google Home (2.0) API](https://rithvikvibhu.github.io/GHLocalApi/)).

## How it works

glocaltokens gets three kinds of tokens, each from the one before:

1. **Master token**: starts with `aas_et/` and is long lived. You get it once with your Google username and password, or with a browser sign-in (see "If logging in with a password fails" below).
2. **Access token**: lives 1 hour. glocaltokens gets a new one from the master token when it expires.
3. **Local authentication tokens**: one per device, used to send requests to that device. They only live about 1 day, so you will need to get new ones regularly.

Store the master token, not your password: with the master token alone, glocaltokens can get the other tokens whenever you need them.

## Installation

glocaltokens requires Python 3.12 or newer.

Using uv:

```console
$ uv add glocaltokens
```

Using pip:

```console
$ pip install glocaltokens
```

## Quickstart

```python
from glocaltokens.client import GLocalAuthenticationTokens

client = GLocalAuthenticationTokens(
    username="<YOUR_GOOGLE_USERNAME>", password="<YOUR_GOOGLE_PASSWORD>"
)

# Get master token, then store it (see "Authentication" below)
print("[*] Master token", client.get_master_token())

# Get Google device local authentication tokens (live about 1 day)
print(client.get_google_devices_json())
```

See [`example/get_tokens.py`](example/get_tokens.py) for a complete script that reads your credentials from environment variables.

## Authentication

### Logging in with a password

Log in with the password only once, then store the master token and use it instead.
If you log in too often, Google will disconnect your Android devices and other weird things will happen.

If your Google account uses 2-Step Verification, create an [app password](https://myaccount.google.com/apppasswords)
and use it instead of your regular password.

### Reusing the master token

Never store the user's password nor username in plain text, if storage is necessary, generate a master token and store it.
The master token gives access to the Google account, so protect it like a password.

```python
from glocaltokens.client import GLocalAuthenticationTokens

# Using Google username and password first, and only once
client = GLocalAuthenticationTokens(
    username="<YOUR_GOOGLE_USERNAME>", password="<YOUR_GOOGLE_PASSWORD>"
)
master_token = client.get_master_token()

"""Now store master_token somewhere"""

# Later, use the stored master token instead of the username and password
client = GLocalAuthenticationTokens(master_token=master_token)
```

### If logging in with a password fails

Logging in with a password does not work for every account. If `get_master_token()` raises `AuthenticationError` (see [Errors](#errors)),
or your account uses a passkey, sign in with a browser instead and let glocaltokens exchange that sign-in for a master token.
This uses [gpsoauth's alternative flow](https://github.com/simon-weber/gpsoauth#alternative-flow):

1. Open https://accounts.google.com/EmbeddedSetup and sign in to your Google account.
2. Click "I agree" when asked. The page may keep loading forever; you can ignore that.
3. Copy the value of the `oauth_token` cookie, for example from the cookies list in your browser's developer tools.
4. Pass it to the client, then get the master token and store it:

```python
client = GLocalAuthenticationTokens(oauth_token="<YOUR_OAUTH_TOKEN_COOKIE>")
master_token = client.get_master_token()
email = client.get_email()
```

Treat the `oauth_token` cookie like a password. If the exchange fails, sign in again to get a new cookie.
After that, use the stored master token as shown above.

### Finding the account of a master token

A master token doesn't say which Google account it belongs to. `get_email()` returns the account's email address,
or `None` if Google doesn't give one. If the client got the master token itself, `get_email()` returns the address Google sent with it.
Otherwise it asks Google, and returns the address only if Google has verified it:

```python
client = GLocalAuthenticationTokens(master_token="<YOUR_MASTER_TOKEN>")
print(client.get_email())
```

## Getting device tokens

`get_google_devices()` returns a list of `Device` objects, and `get_google_devices_json()` returns the same list as a JSON string:

```json
[
  {
    "device_id": "...",
    "device_name": "Living Room speaker",
    "network_device": {
      "ip": "192.168.1.10",
      "port": 8009
    },
    "hardware": "Google Nest Mini",
    "cloud_device_id": "...",
    "home_id": "...",
    "home_name": "Home",
    "local_auth_token": "..."
  }
]
```

`device_name` is the name in the Google Home app. A speaker pair is found on the network at its leading speaker, but keeps the pair's name.
The JSON doesn't include the name a device announces on the network. For a `Device` object found there, it is in `network_device.name`.

`cloud_device_id` is the ID Google gives the device, or `null` if Google gives none.
To match a device at an address you know, request `https://<ip>:8443/setup/eureka_info?params=device_info` and compare `cloud_device_id` with `device_info.cloud_device_id` in the response, ignoring case.
The device's certificate is self-signed, so turn off certificate verification for this request.

`home_id` and `home_name` are the ID and name of the home the device is in, in the Google Home app.
If your account has several homes, pass a `home_id` to get only that home's devices.
To list every home, including homes without devices, use `get_home_graph()`: each entry of its `homes` has an `id` and a `display_name`.

The client caches the tokens it gets from Google for 24 hours. Pass `force_homegraph_reload=True` to fetch new ones sooner.

### Selecting models

By default you get all devices with valid local authentication tokens, without filtering by model. To get only some models, pass a list of model names as `models_list`.
The names are the `hardware` values in the output above.

`GOOGLE_HOME_MODELS` in [`const.py`](glocaltokens/const.py) lists some common models:

- Google Home
- Google Home Mini
- Google Nest Mini
- Lenovo Smart Clock

```python
from glocaltokens.const import GOOGLE_HOME_MODELS

google_devices = client.get_google_devices_json(GOOGLE_HOME_MODELS)

# Or your own list
google_devices = client.get_google_devices_json(["Google Home", "Google Nest Mini"])
```

The list is not complete. If your model is missing, use your own list, or add it to `GOOGLE_HOME_MODELS` with a pull request.

### Finding devices on your network

To fill in `ip` and `port`, glocaltokens looks for devices on your local network with mDNS (zeroconf),
so it must run on the same network as your devices. Devices it does not find have `null` for both.

If discovery does not work on your network, turn it off and give the IPv4 address of each device, using its name in the Google Home app:

```python
google_devices = client.get_google_devices_json(
    disable_discovery=True,
    addresses={"Living Room speaker": "192.168.1.10"},
)
```

Only IPv4 addresses are supported. If any entry is not a valid IPv4 address, the device methods raise `ValueError`.

### Options

Both `get_google_devices()` and `get_google_devices_json()` accept these arguments:

| Argument                 | Default | Description                                                                                  |
| ------------------------ | ------- | -------------------------------------------------------------------------------------------- |
| `models_list`            | `None`  | Only return these models. `None` returns all devices with valid local authentication tokens. |
| `disable_discovery`      | `False` | Do not search the local network for device IP addresses and ports.                           |
| `addresses`              | `None`  | `{"device name": "IPv4 address"}`, used when discovery is disabled or finds nothing.         |
| `zeroconf_instance`      | `None`  | An existing `zeroconf.Zeroconf` instance to use for discovery. glocaltokens leaves it open.  |
| `force_homegraph_reload` | `False` | Fetch new tokens from Google even if the cached ones are less than 24 hours old.             |
| `discovery_timeout`      | `2`     | How long to search the local network, in seconds.                                            |
| `home_id`                | `None`  | Only return the devices of the home with this ID. `None` returns the devices of every home.  |

`get_google_devices_json()` also accepts `indent` for the JSON output (default `2`).
`async_get_google_devices()` and `async_get_google_devices_and_home_graph()` take these options with clearer names (see [Async device options](#async-device-options)).

## Using asyncio

The methods that ask Google have async counterparts: `async_get_master_token()`, `async_get_access_token()`, `async_get_email()`,
`async_get_home_graph()` and `async_get_google_devices()`.
They return the same results and raise the same glocaltokens errors, and they wait for Google and the network without blocking your event loop.
Two methods have no async counterpart. Instead of `get_homegraph()`, which merges every home into one, use `async_get_home_graph()`.
Instead of `get_google_devices_json()`, use `json.dumps([device.as_dict() for device in devices])`.

To use your application's aiohttp session, pass it as `session`. glocaltokens never closes it. Without one, each request uses a new session that is closed afterwards.

```python
import aiohttp

from glocaltokens.client import GLocalAuthenticationTokens


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        client = GLocalAuthenticationTokens(
            master_token="<YOUR_MASTER_TOKEN>", session=session
        )
        devices, home_graph = await client.async_get_google_devices_and_home_graph()
```

`async_get_google_devices_and_home_graph()` returns the device list and the home graph it came from, with every device of every home,
including those the list leaves out, such as devices without a local authentication token.
Use it rather than reading the home graph separately: another call can replace the cached home graph while discovery runs.

The sync and async methods share the cached tokens and home graph. Don't use one client from several threads at once.

How your session affects the requests to Google:

- The home graph, which has the device tokens, comes over gRPC, not through your session. The other requests go through it.
- They check Google's certificate even if your session doesn't check certificates. Like the sync sign-in requests, they trust the system's certificate
  authorities and those in the bundle `requests` uses, which is certifi's unless the `REQUESTS_CA_BUNDLE` or `CURL_CA_BUNDLE` environment variable names
  another file or directory. glocaltokens reads these variables when it's imported. If it can't load that bundle, the async requests raise `OSError`,
  as `requests` does.
- Your session's middlewares apply to them. An exception a middleware raises reaches your code.
- Your session's `raise_for_status` setting doesn't apply to them: glocaltokens handles each answer itself, as described in [Errors](#errors).
- Cookies in your session's cookie jar for Google's addresses are sent with them, and cookies Google sets are kept in the jar.
- Your session's default headers are sent with them, except those glocaltokens sets itself, such as `User-Agent`.
- They use your session's proxy settings. A session that glocaltokens creates follows the `HTTP_PROXY`, `HTTPS_PROXY` and `NO_PROXY` environment variables,
  but aiohttp ignores proxy addresses there that start with `https://`.
- Don't pass a session with default `auth` credentials: they would be sent to Google.

### Async device options

`async_get_google_devices()` and `async_get_google_devices_and_home_graph()` take the [options](#options) of `get_google_devices()` by name only,
with clearer names for three of them:

| Option              | Default | Sync option              | Description                                                                                                                      |
| ------------------- | ------- | ------------------------ | -------------------------------------------------------------------------------------------------------------------------------- |
| `models`            | `None`  | `models_list`            | Only return these models. `None` returns all devices with valid local authentication tokens.                                     |
| `home_id`           | `None`  | `home_id`                | Only return the devices of the home with this ID. `None` returns the devices of every home.                                      |
| `discover`          | `True`  | `disable_discovery`      | Search the local network for device IP addresses and ports. `discover=False` is `disable_discovery=True`.                        |
| `zeroconf_instance` | `None`  | `zeroconf_instance`      | A `zeroconf.Zeroconf` that runs on your event loop, such as Home Assistant's shared instance or an `AsyncZeroconf`'s `zeroconf`. |
| `discovery_timeout` | `2`     | `discovery_timeout`      | How long to search the local network, in seconds.                                                                                |
| `addresses`         | `None`  | `addresses`              | `{"device name": "IPv4 address"}`, used when discovery is off or finds nothing.                                                  |
| `reload_home_graph` | `False` | `force_homegraph_reload` | Fetch new tokens from Google even if the cached ones are less than 24 hours old.                                                 |

Without a `zeroconf_instance`, glocaltokens creates its own for discovery and closes it afterwards. It leaves yours open.

## Troubleshooting

If you get no devices or an error, turn on debug logs for glocaltokens to see each step:

```python
import logging

logging.basicConfig()
logging.getLogger("glocaltokens").setLevel(logging.DEBUG)
```

glocaltokens doesn't set log levels, so it follows your application's logging configuration.
The client's `verbose` argument and the `logging_level` argument of `discover_devices()` are deprecated: they only emit a `DeprecationWarning`.
glocaltokens masks your password and tokens in its logs, but they also include Google's responses to failed requests, so check them before you share them, for example in an issue.

### Errors

The token and device methods raise an error when they can't get what you asked for. They don't return `None` or an empty list instead.
An account without devices is not an error: `get_google_devices()` returns an empty list and `get_google_devices_json()` returns `"[]"`.
`get_email()` returns `None` if Google gives no email address, including when Google refuses the request for it.

glocaltokens raises these errors when Google gives no tokens or devices. They are in `glocaltokens.exceptions` and are subclasses of `GLocalTokensError`, so you can catch both at once:

- `AuthenticationError`: Google gave no master token or access token, the username and password are too long together to log in with,
  or the client has no master token and neither an `oauth_token` nor a username and password to get one with.
  This usually means you need to sign in again (see [Authentication](#authentication)).
  Its `error` attribute is the reason Google gave, such as `BadAuthentication` or `NeedsBrowser`, or `None` if there isn't one.
  `get_master_token()`, `get_access_token()`, `get_email()` and the device methods raise it.
- `HomegraphError`: Google didn't return your devices. The device methods raise it.
  Its `code` attribute is the [gRPC status code](https://grpc.github.io/grpc/core/md_doc_statuscodes.html) of the failed request as a `grpc.StatusCode`.
  For example, `UNAVAILABLE` and `DEADLINE_EXCEEDED` mean Google is unavailable or did not reply within 10 seconds: try again later.
  `UNAUTHENTICATED` means Google kept rejecting the access token, even after glocaltokens got a new one. If that keeps happening, sign in again.

These errors from the libraries glocaltokens uses also reach your code:

- `requests.RequestException` when a request to Google fails, for example without an internet connection or when Google does not reply within 10 seconds.
  A request for a token also raises it when Google answers that you should try later (HTTP 5xx or 429).
  `get_master_token()`, `get_access_token()`, `get_email()` and the device methods raise it. Try again later.
- `OSError` when network discovery cannot start, for example because no network interface is available.
  Pass `disable_discovery=True` if you do not need IP addresses and ports.
- `OSError` when the certificate bundle that `REQUESTS_CA_BUNDLE` or `CURL_CA_BUNDLE` names can't be loaded. Each request for a token or the email address
  raises it; the home graph request, which uses gRPC's own certificates, doesn't. Correct or unset the variable.

A mistake in your call raises `ValueError`: creating the client without credentials or with a `master_token` that doesn't start with `aas_et/`,
or passing `addresses` that aren't a dictionary of IPv4 addresses to the device methods.

The async methods raise aiohttp's errors instead of `requests` errors:

- `aiohttp.ClientResponseError` when Google answers a request for a token that you should try later (HTTP 5xx or 429). Its `status` attribute is the HTTP status.
- `aiohttp.ClientError` or `TimeoutError` when a request to Google fails, for example without an internet connection or when Google does not reply within 10 seconds.
- `async_get_email()` raises `json.JSONDecodeError`, or `aiohttp.ContentTypeError`, if Google's answer with the email address isn't JSON.
  `get_email()` raises `requests.RequestException` for it.

This example tells "sign in again" from "try again later". To keep it simple, it treats every `HomegraphError` as temporary;
check its `code` to also handle `UNAUTHENTICATED` that keeps happening:

```python
import requests

from glocaltokens.client import GLocalAuthenticationTokens
from glocaltokens.exceptions import AuthenticationError, HomegraphError

client = GLocalAuthenticationTokens(master_token="<YOUR_MASTER_TOKEN>")
try:
    devices = client.get_google_devices()
except AuthenticationError as err:
    print(f"Sign in again to get a new master token: {err}")
except (HomegraphError, requests.RequestException) as err:
    print(f"Try again later: {err}")
```

## Contributing

See [Contributing guidelines](CONTRIBUTING.md).
This is an open-source project and all contributions are highly welcomed.

## Credits

Much credit goes to [@rithvikvibhu](https://github.com/rithvikvibhu) for doing most of the heavy work like finding a way to
extract master and access tokens
(See the gist [here](https://gist.github.com/rithvikvibhu/952f83ea656c6782fbd0f1645059055d)).

Also, thank you very much to the guys at `pychromecast` which provided the code required to scan devices in the network.

[workflow-shield]: https://img.shields.io/github/actions/workflow/status/leikoilja/glocaltokens/linting-and-testing.yaml?branch=master
[workflow]: https://github.com/leikoilja/glocaltokens/actions
[pypi-shield]: https://img.shields.io/pypi/v/glocaltokens
[pypi]: https://pypi.org/project/glocaltokens/
[pepy-shield]: https://pepy.tech/badge/glocaltokens
[pepy]: https://pepy.tech/project/glocaltokens
[commits-shield]: https://img.shields.io/github/commit-activity/y/leikoilja/glocaltokens
[commits]: https://github.com/leikoilja/glocaltokens/commits/master
[pre-commit-shield]: https://img.shields.io/badge/pre--commit-enabled-brightgreen
[pre-commit]: https://pre-commit.com/
