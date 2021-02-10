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

# Credits
Much credits go to @rithvikvibhu(https://github.com/rithvikvibhu) for doing
most of the heavy work like finding a way to extract master and access tokens
(See his gist [here](https://gist.github.com/rithvikvibhu/952f83ea656c6782fbd0f1645059055d)).
