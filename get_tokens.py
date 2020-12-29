"""
Credits to rithvikvibhu (https://github.com/rithvikvibhu)
for implementing master and access token fetching
See: https://gist.github.com/rithvikvibhu/952f83ea656c6782fbd0f1645059055d
"""
import logging
import grpc
import jq
import json

from gpsoauth import perform_master_login, perform_oauth
from google.internal.home.foyer import v1_pb2_grpc
from google.internal.home.foyer import v1_pb2
from google.protobuf.json_format import MessageToJson
from uuid import getnode as getmac
from os import getenv
from sys import exit

ACCESS_TOKEN_APP_NAME = 'com.google.android.apps.chromecast.app'
ACCESS_TOKEN_CLIENT_SIGNATURE = '24bb24c05e47e0aefa68a58a766179d9b613a600'
ACCESS_TOKEN_SERVICE = 'oauth2:https://www.google.com/accounts/OAuthLogin'
GOOGLE_HOME_FOYER_API = 'googlehomefoyer-pa.googleapis.com:443'

# Creds to use when logging in
USERNAME = getenv('USERNAME', None)
PASSWORD = getenv('PASSWORD', None)

# Optional Overrides (Set to None to ignore)
DEVICE_ID = getenv('DEVICE_ID' , None)
MASTER_TOKEN = getenv('MASTER_TOKEN', None)
ACCESS_TOKEN = getenv('ACCESS_TOKEN', None)

# Flags
DEBUG = False

def get_master_token(username, password, android_id):
    res = perform_master_login(username, password, android_id)
    if DEBUG:
        print(res)
    if 'Token' not in res:
        print('[!] Could not get master token.')
        return None
    return res['Token']

def get_access_token(username, MASTER_TOKEN, android_id):
    res = perform_oauth(
        username, MASTER_TOKEN, android_id,
        app=ACCESS_TOKEN_APP_NAME,
        service=ACCESS_TOKEN_SERVICE,
        client_sig=ACCESS_TOKEN_CLIENT_SIGNATURE
    )
    if DEBUG:
        print(res)
    if 'Auth' not in res:
        print('[!] Could not get access token.')
        return None
    return res['Auth']

def get_homegraph(token):
    """
    Returns the entire Google Home Foyer V2 service
    """
    scc = grpc.ssl_channel_credentials(root_certificates=None)
    tok = grpc.access_token_call_credentials(token)
    ccc = grpc.composite_channel_credentials(scc, tok)

    with grpc.secure_channel(GOOGLE_HOME_FOYER_API, ccc) as channel:
        rpc_service = v1_pb2_grpc.StructuresServiceStub(channel)
        request = v1_pb2.GetHomeGraphRequest(string1="", num2="")
        response = rpc_service.GetHomeGraph(request)
        return response

def get_google_devices(homegraph_json):
    """
    Returns and print a list of google devices with their
    local authentication tokens
    """
    devices = jq.compile('.home.devices[] | {deviceName, localAuthToken}').input(homegraph_json)
    return devices.all()

def _get_android_id():
    mac_int = getmac()
    if (mac_int >> 40) % 2:
        raise OSError("a valid MAC could not be determined."
                      " Provide an android_id (and be"
                      " sure to provide the same one on future runs).")

    android_id = _create_mac_string(mac_int)
    android_id = android_id.replace(':', '')
    return android_id

def _create_mac_string(num, splitter=':'):
    mac = hex(num)[2:]
    if mac[-1] == 'L':
        mac = mac[:-1]
    pad = max(12 - len(mac), 0)
    mac = '0' * pad + mac
    mac = splitter.join([mac[x:x + 2] for x in range(0, 12, 2)])
    mac = mac.upper()
    return mac

if __name__ == '__main__':
    print('''
    This script generates tokens that can be used when making requests to the Google Home Foyer API.
    There are 2 kinds of tokens used here:

    1. Master token - Is in the form `aas_et/***` and is long lived. Needs Google username and password.
    2. Access token - Is in the form `ya29.***` and lasts for an hour. Needs Master token to generate.

    If you do not want to store the Google account password in plaintext,
    get the master token once, and set it as an override value.

    It's safer/easier to generate an app password and use it instead of the actual password.
    It still has the same access as the regular password, but still better than using the real password while scripting.
    (https://myaccount.google.com/apppasswords)
    ''')
    logging.basicConfig()

    if (not USERNAME or not PASSWORD) and not MASTER_TOKEN:
        print(
            '[!] You must provide your google USERNAME and '
            'PASSWORD or MASTER_TOKEN.'
        )
        exit()

    if not DEVICE_ID:
        print('\n[*] Generating Android id...')
        DEVICE_ID = _get_android_id()
        print('[*] Android id:', DEVICE_ID)

    print('\n[*] Getting master token...')
    if not MASTER_TOKEN:
        MASTER_TOKEN = get_master_token(USERNAME, PASSWORD, DEVICE_ID)
    print('[*] Master token:', MASTER_TOKEN)

    print('\n[*] Getting access token...')
    if not ACCESS_TOKEN:
        ACCESS_TOKEN = get_access_token(USERNAME, MASTER_TOKEN, DEVICE_ID)
    print('[*] Access token:', ACCESS_TOKEN)

    if ACCESS_TOKEN:
        print('\n[*] Getting google devices...')
        homegraph = get_homegraph(ACCESS_TOKEN)
        homegraph_json = json.loads(MessageToJson(homegraph))
        google_devices = get_google_devices(homegraph_json)
        google_devices_str = json.dumps(google_devices, indent=2)
        print('[*] Google devices', google_devices_str)

    print('\n[*] Done.')
