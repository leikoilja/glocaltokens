# Google home local authentication token extraction

Python 3 script to extract google home devices local authentication tokens from
google servers. These local authentication tokens are needed to control Google
Home devices(See @rithvikvibhu's [Google Home (2.0) API](https://rithvikvibhu.github.io/GHLocalApi/)).

Please note:
Once you have local google authentication tokens they only live about 1 day
long. After that you will need to obtain new ones. You will probably need to
modify the script and run this script repeatedly storing the tokens somewhere convenient.

## Quickstart

Note: the package was written and tested on Python 3.

- Clone the repo
- Install dependency packages: `pip install -r requirements`
- Modify the `get_tokens.py` script to specify your google username/password or
  master token(if you have one).
- Run the script `python get_tokens.py`

You will see something like that as an output:
```bash
python get_tokens.py

    This script generates tokens that can be used when making requests to the Google Home Foyer API.
    There are 2 kinds of tokens used here:

    1. Master token - Is in the form `aas_et/***` and is long lived. Needs Google username and password.
    2. Access token - Is in the form `ya29.***` and lasts for an hour. Needs Master token to generate.

    If you do not want to store the Google account password in plaintext,
    get the master token once, and set it as an override value.

    It's safer/easier to generate an app password and use it instead of the actual password.
    It still has the same access as the regular password, but still better than using the real password while scripting.
    (https://myaccount.google.com/apppasswords)


[*] Getting master token...
[*] Master token: aas_et/<MASTER TOKEN>

[*] Getting access token...
[*] Access token: ya29.<ACCESS TOKEN>

[*] Getting google devices...
[*] Google devices [
  {
    "deviceName": "Living Room TV",
    "localAuthToken": "<LOCAL DEVICE TOKEN>"
  },
  {
    "deviceName": "Living Room Speaker",
    "localAuthToken": "<LOCAL DEVICE TOKEN>"
  },
  {
    "deviceName": "Kitchen",
    "localAuthToken": "<LOCAL DEVICE TOKEN>"
  },
  {
    "deviceName": "Bedroom Speaker",
    "localAuthToken": "<LOCAL DEVICE TOKEN>"
  },
  ...
]

[*] Done.
```

# Credits
Much credits go to @rithvikvibhu(https://github.com/rithvikvibhu) for doing
most of the heavy work like finding a way to extract master and access tokens
(See his gist [here](https://gist.github.com/rithvikvibhu/952f83ea656c6782fbd0f1645059055d)).
