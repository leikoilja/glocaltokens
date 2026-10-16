[![GitHub Workflow Status][workflow-shield]][workflow]
[![PyPI][pypi-shield]][pypi]
[![Downloads][pepy-shield]][pepy]
[![Pre-commit][pre-commit-shield]][pre-commit]
[![GitHub Activity][commits-shield]][commits]

# Google home local authentication token extraction

Python package to extract Google Home devices local authentication tokens from Google servers.
These local authentication tokens are needed to control Google Home devices
(See [@rithvikvibhu](https://github.com/rithvikvibhu)'s [Google Home (2.0) API](https://rithvikvibhu.github.io/GHLocalApi/)).

Please note:
Once you have local Google authentication tokens they only live about 1 day long.
After that you will need to obtain new ones.
You will probably need to run the script repeatedly storing the tokens somewhere convenient.

## Quickstart

glocaltokens requires Python 3.12 or newer.

- Install the python package.

Using uv:

```console
$ uv add glocaltokens
```

Using pip:

```console
$ pip install glocaltokens
```

Use in your program as (see [`example/get_tokens.py`](example/get_tokens.py) for a detailed example):

```Python
from glocaltokens.client import GLocalAuthenticationTokens

# Using Google username and password
#
# Log in with the password only once, then store the master token
# and use it instead (see "Security Recommendation" below).
#
# If you log in too often, Google will disconnect your Android devices and other weird things will happen.
client = GLocalAuthenticationTokens(
    username="<YOUR_GOOGLE_USERNAME>", password="<YOUR_GOOGLE_PASSWORD>"
)

# Get master token
print("[*] Master token", client.get_master_token())

# Get access token (lives 1 hour)
print("\n[*] Access token (lives 1 hour)", client.get_access_token())

# Get Google device local authentication tokens (live about 1 day)
print("\n[*] Google devices local authentication tokens")
google_devices = client.get_google_devices_json()
print(google_devices)

# You can also select specific models to select when calling get_google_devices or get_google_devices_json with the models_list parameter.
# For example, we have pre-defined a constant with some Google Home Models (WARNING! Not all of them may be present)
# This could be used this way
from glocaltokens.const import GOOGLE_HOME_MODELS

google_devices_select = client.get_google_devices_json(GOOGLE_HOME_MODELS)

# But if you need to select just a set of models, or add new models, you can use a list of str
google_devices_select_2 = client.get_google_devices_json(
    [
        "Google Home",
        "Google Home Mini",
        "Google Nest Mini",
    ]
)
```

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

### Predefined models list

There are some pre-defined models list in [`const.py`](glocaltokens/const.py), feel free to
add new lists, or add models to a list with a pull-request.

#### `GOOGLE_HOME_MODELS`:

- Google Home
- Google Home Mini
- Google Nest Mini
- Lenovo Smart Clock

## Logging in

If your Google account uses 2-Step Verification, create an [app password](https://myaccount.google.com/apppasswords)
and use it instead of your regular password.

Logging in with a password does not work for every account. If `get_master_token()` returns `None`,
or your account uses a passkey, get a master token another way, for example with
[gpsoauth's alternative flow](https://github.com/simon-weber/gpsoauth#alternative-flow),
and pass it to the client together with your username.

## Security Recommendation

Never store the user's password nor username in plain text, if storage is necessary, generate a master token and store it.
The master token gives access to the Google account, so protect it like a password.
Example approach:

```python
from glocaltokens.client import GLocalAuthenticationTokens

# Using Google username and password first, and only once
client = GLocalAuthenticationTokens(
    username="<YOUR_GOOGLE_USERNAME>", password="<YOUR_GOOGLE_PASSWORD>"
)

# Get master token
master_token = client.get_master_token()
print("[*] Master token", master_token)

"""Now store master_token somewhere"""

# Later, use the stored master token instead of the password
client = GLocalAuthenticationTokens(
    username="<YOUR_GOOGLE_USERNAME>", master_token=master_token
)
```

## Contributing

See [Contributing guidelines](CONTRIBUTING.md).
This is an open-source project and all contributions are highly welcomed.

# Credits

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
