[![Glocaltokens Actions Status](https://github.com/leikoilja/glocaltokens/workflows/Running%20tests/badge.svg?branch=master)](https://github.com/leikoilja/glocaltokens/actions)
# Google home local authentication token extraction

Python 3 package to extract google home devices local authentication tokens from
google servers. These local authentication tokens are needed to control Google
Home devices(See @rithvikvibhu's [Google Home (2.0) API](https://rithvikvibhu.github.io/GHLocalApi/)).

Please note:
Once you have local google authentication tokens they only live about 1 day
long. After that you will need to obtain new ones. You will probably need to
run the script repeatedly storing the tokens somewhere convenient.

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
  username='<YOUR_GOOGLE_USERNAME>',
  password='<YOUR_GOOGLE_PASSWORD>'
)

# Get master token
print('[*] Master token', client.get_master_token())

# Get access token (lives 1 hour)
print('\n[*] Access token (lives 1 hour)', client.get_access_token())

# Get google device local authentication tokens (live about 1 day)
print('\n[*] Google devices local authentication tokens')
google_devices = client.get_google_devices_json()
```

## Security Recommendation
Never store the user's password nor username in plain text, if storage is necessary, generate a
master token and store it. Example approach:
```python
from glocaltokens.client import GLocalAuthenticationTokens

# Using google username and password first, and only once
client = GLocalAuthenticationTokens(
  username='<YOUR_GOOGLE_USERNAME>',
  password='<YOUR_GOOGLE_PASSWORD>'
)

# Get master token
master_token = client.get_master_token()
print('[*] Master token', master_token)



"""Now store master_token somewhere"""

```

## Contributing
This is an open-source project and all countribution is highly welcomed. To
contribute please:
- Fork this repo
- Create a new branch
- Create a new virtual environment and install dependencies:
`pip install -r requirements`
- Implement your changes
- If possible add tests for your changes
- Push your changes to your branch
- Open Pull Request

When writting unittests please follow the good practises like:
- Use `faker` to fake the data. See [examples](https://faker.readthedocs.io/en/master/)
- Use `mock` to patch objects/methods. See [examples](https://realpython.com/python-mock-library/)
- You can run `python -m discover -p 'test*.py'` or `tox` inside of your virtual
  environment to test locally.

# Credits
Much credits go to @rithvikvibhu(https://github.com/rithvikvibhu) for doing
most of the heavy work like finding a way to extract master and access tokens
(See his gist [here](https://gist.github.com/rithvikvibhu/952f83ea656c6782fbd0f1645059055d)).

Also, thank you very much to the guys at `pychromecast` which provided the code required to scan 
devices in the network.
