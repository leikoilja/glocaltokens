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

1. **Master token**: starts with `aas_et/` and is long lived. You get it once with your Google username and password.
2. **Access token**: lives 1 hour. glocaltokens gets a new one from the master token when it expires.
3. **Local authentication tokens**: one per device, used to send requests to that device. They only live about 1 day, so you will need to get new ones regularly.

Store the master token, not your password: with the master token and your username, glocaltokens can get the other tokens whenever you need them.

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

# Later, use the stored master token instead of the password
client = GLocalAuthenticationTokens(
    username="<YOUR_GOOGLE_USERNAME>", master_token=master_token
)
```

### If logging in with a password fails

Logging in with a password does not work for every account. If `get_master_token()` returns `None`,
or your account uses a passkey, get a master token another way, for example with
[gpsoauth's alternative flow](https://github.com/simon-weber/gpsoauth#alternative-flow),
and pass it to the client together with your username.

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

By default you get every device on your account. To get only some models, pass a list of model names as `models_list`.
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

If discovery does not work on your network, turn it off and give the IP address of each device, using its name in the Google Home app:

```python
google_devices = client.get_google_devices_json(
    disable_discovery=True,
    addresses={"Living Room speaker": "192.168.1.10"},
)
```

### Options

Both `get_google_devices()` and `get_google_devices_json()` accept these arguments:

| Argument                 | Default | Description                                                                        |
| ------------------------ | ------- | ---------------------------------------------------------------------------------- |
| `models_list`            | `None`  | Only return these models. `None` returns every device.                             |
| `disable_discovery`      | `False` | Do not search the local network for device IP addresses and ports.                 |
| `addresses`              | `None`  | `{"device name": "IP address"}`, used when discovery is disabled or finds nothing. |
| `zeroconf_instance`      | `None`  | An existing `zeroconf.Zeroconf` instance to use for discovery.                     |
| `force_homegraph_reload` | `False` | Fetch new tokens from Google even if the cached ones are less than 24 hours old.   |

`get_google_devices()` also accepts `discovery_timeout`, how long to search the network in seconds (default `2`),
and `get_google_devices_json()` accepts `indent` for the JSON output (default `2`).

## Troubleshooting

If you get no devices or no tokens, create the client with `verbose=True` to print debug logs that show each step.
The logs mask your password and tokens, but they also include Google's responses to failed requests, so check them before you share them, for example in an issue.

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
