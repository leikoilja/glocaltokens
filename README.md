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

Logging in with a password does not work for every account. If `get_master_token()` returns `None`,
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
    "local_auth_token": "..."
  }
]
```

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

Only IPv4 addresses are supported. If any entry is not a valid IPv4 address, glocaltokens logs an error and returns no devices at all.

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

`get_google_devices_json()` also accepts `indent` for the JSON output (default `2`).

## Troubleshooting

If you get no devices or no tokens, turn on debug logs for glocaltokens to see each step:

```python
import logging

logging.basicConfig()
logging.getLogger("glocaltokens").setLevel(logging.DEBUG)
```

glocaltokens doesn't set log levels, so it follows your application's logging configuration.
The client's `verbose` argument and the `logging_level` argument of `discover_devices()` are deprecated: they only emit a `DeprecationWarning`.
glocaltokens masks your password and tokens in its logs, but they also include Google's responses to failed requests, so check them before you share them, for example in an issue.

### Errors

Most failures are logged and return `None` from the token methods, or no devices from the device methods:
an empty list from `get_google_devices()` and `"[]"` from `get_google_devices_json()`.
Check the result before you use it.

Some errors are raised instead, and your code should handle them:

- `requests.RequestException` when glocaltokens cannot get a master or access token from Google,
  for example without an internet connection or when Google does not reply within 10 seconds.
  The device methods raise it too when they need a new access token first, and so does `get_email()`.
- `OSError` when network discovery cannot start, for example because no network interface is available.
  Pass `disable_discovery=True` if you do not need IP addresses and ports.

If Google does not reply within 10 seconds when the device methods fetch the device list itself,
they log the error and return no devices.

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
