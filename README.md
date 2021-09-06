[![GitHub Workflow Status][workflow-shield]][workflow]
[![PyPI][pypi-shield]][pypi]
[![Downloads][pepy-shield]][pepy]
[![Pre-commit][pre-commit-shield]][pre-commit]
[![GitHub Activity][commits-shield]][commits]

# Google home local authentication token extraction

Python 3 package to extract google home devices local authentication tokens from google servers.
These local authentication tokens are needed to control Google Home devices
(See [@rithvikvibhu](https://github.com/rithvikvibhu)'s [Google Home (2.0) API](https://rithvikvibhu.github.io/GHLocalApi/)).

Please note:
Once you have local google authentication tokens they only live about 1 day long.
After that you will need to obtain new ones.
You will probably need to run the script repeatedly storing the tokens somewhere convenient.

## Quickstart

Note: the package was written and tested on Python 3.

- Install the python package

```
pip install glocaltokens
```

Use in your program as (see examples folder for detailed example):

```Python
from glocaltokens.client import GLocalAuthenticationTokens

# Using google username and password
#
# ONLY CALL THIS ONCE
#
# If you call this too often, google will disconnect your android devices and other weird things will happen
#
# Call get_google_devices_json() afterwards to get timers/alarms as oftens as you want to update.
client = GLocalAuthenticationTokens(
  username="<YOUR_GOOGLE_USERNAME>",
  password="<YOUR_GOOGLE_PASSWORD>"
)

# Get master token
print("[*] Master token", client.get_master_token())

# Get access token (lives 1 hour)
print("\n[*] Access token (lives 1 hour)", client.get_access_token())

# Get google device local authentication tokens (live about 1 day)
print("\n[*] Google devices local authentication tokens")
google_devices = client.get_google_devices_json()

# You can also select specific models to select when calling get_google_devices or get_google_devices_json with the models_list parameter.
# For example, we have pre-defined a constant with some Google Home Models (WARNING! Not all of them may be present)
# This could be used this way
from glocaltokens.const import GOOGLE_HOME_MODELS

google_devices_select = client.get_google_devices_json(GOOGLE_HOME_MODELS)

# But if you need to select just a set of models, or add new models, you can use a list of str
google_devices_select_2 = client.get_google_devices_json([
    f"Google Home",
    f"Google Home Mini",
    f"Google Nest Mini",
])
```

### Predefined models list

There are some pre-defined models list in [`scanner.py`](/glocaltokens/scanner.py), feel free to
add new lists, or add models to a list with a pull-request.

#### `GOOGLE_HOME_MODELS`:

- Google Home
- Google Home Mini
- Google Nest Mini
- Lenovo Smart Clock

## Security Recommendation

Never store the user's password nor username in plain text, if storage is necessary, generate a master token and store it.
Example approach:

```python
from glocaltokens.client import GLocalAuthenticationTokens

# Using google username and password first, and only once
client = GLocalAuthenticationTokens(
  username="<YOUR_GOOGLE_USERNAME>",
  password="<YOUR_GOOGLE_PASSWORD>"
)

# Get master token
master_token = client.get_master_token()
print("[*] Master token", master_token)

"""Now store master_token somewhere"""

```

## Contributing

See [Contributing guidelines](CONTRIBUTING.md).
This is an open-source project and all countribution is highly welcomed.

# Credits

Much credits go to [@rithvikvibhu](https://github.com/rithvikvibhu) for doing most of the heavy work like finding a way to
extract master and access tokens
(See his gist [here](https://gist.github.com/rithvikvibhu/952f83ea656c6782fbd0f1645059055d)).

Also, thank you very much to the guys at `pychromecast` which provided the code required to scan devices in the network.

[workflow-shield]: https://img.shields.io/github/workflow/status/leikoilja/glocaltokens/Linting%20&%20Testing
[workflow]: https://github.com/leikoilja/glocaltokens/actions
[pypi-shield]: https://img.shields.io/pypi/v/glocaltokens
[pypi]: https://pypi.org/project/glocaltokens/
[pepy-shield]: https://pepy.tech/badge/glocaltokens
[pepy]: https://pepy.tech/project/glocaltokens
[commits-shield]: https://img.shields.io/github/commit-activity/y/leikoilja/glocaltokens
[commits]: https://github.com/leikoilja/glocaltokens/commits/master
[pre-commit-shield]: https://img.shields.io/badge/pre--commit-enabled-brightgreen
[pre-commit]: https://pre-commit.com/
