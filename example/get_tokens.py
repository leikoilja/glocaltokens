import json
from os import getenv

from glocaltokens.client import GLocalAuthenticationTokens

# Creds to use when logging in
GOOGLE_USERNAME = getenv("GOOGLE_USERNAME", None)
GOOGLE_PASSWORD = getenv("GOOGLE_PASSWORD", None)

# Optional Overrides (Set to None to ignore)
DEVICE_ID = getenv("DEVICE_ID", None)
GOOGLE_MASTER_TOKEN = getenv("GOOGLE_MASTER_TOKEN", None)
GOOGLE_ACCESS_TOKEN = getenv("GOOGLE_ACCESS_TOKEN", None)


if __name__ == "__main__":
    print(
        """
    The client generates tokens that can be used when
    making requests to the Google Home API.
    There are 3 kinds of tokens used here:

    1. Master token - Is in the form `aas_et/***` and is long lived.
       Needs Google username and password.
    2. Access token - Is in the form `ya29.***` and lasts for an hour.
       Needs Master token to generate.
    3. Local authentication tokens - Are individual google device local
    authentication tokens used to send requests to specific google assistant
    devidevices

    If you do not want to store the Google account password in plaintext,
    get the master token once, and set it as an override value.

    It's safer/easier to generate an app password and
    use it instead of the actual password.
    It still has the same access as the regular password,
    but still better than using the real password while scripting.
    (https://myaccount.google.com/apppasswords)
    """
    )

    # Using google username and password
    client = GLocalAuthenticationTokens(
        username=GOOGLE_USERNAME,
        password=GOOGLE_PASSWORD,
        master_token=GOOGLE_MASTER_TOKEN,
        android_id=DEVICE_ID,
        verbose=True,
    )

    # Get master token
    print("[*] Master token", client.get_master_token())

    # Get access token (lives 1 hour)
    print("\n[*] Access token (lives 1 hour)", client.get_access_token())

    # Get google device local authentication tokens (live about 1 day)
    print("\n[*] Google devices local authentication tokens")
    google_devices = client.get_google_devices_json()
    # Pretty print json data
    google_devices_str = json.dumps(google_devices, indent=2)
    print("[*] Google devices", google_devices_str)
