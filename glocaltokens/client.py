"""
Credits to rithvikvibhu (https://github.com/rithvikvibhu)
for implementing master and access token fetching
See: https://gist.github.com/rithvikvibhu/952f83ea656c6782fbd0f1645059055d
"""
import logging
import grpc
import json
import datetime

from gpsoauth import perform_master_login, perform_oauth
from google.protobuf.json_format import MessageToJson
from uuid import getnode as getmac

from .google.internal.home.foyer import v1_pb2_grpc
from .google.internal.home.foyer import v1_pb2

ACCESS_TOKEN_APP_NAME = 'com.google.android.apps.chromecast.app'
ACCESS_TOKEN_CLIENT_SIGNATURE = '24bb24c05e47e0aefa68a58a766179d9b613a600'
ACCESS_TOKEN_SERVICE = 'oauth2:https://www.google.com/accounts/OAuthLogin'
GOOGLE_HOME_FOYER_API = 'googlehomefoyer-pa.googleapis.com:443'


class GLocalAuthenticationTokens:

    def __init__(self, username=None, password=None, master_token=None,
                 android_id=None):
        """
        Initialize an GLocalAuthenticationTokens instance with google account
        credentials
        :params
            username: google account username (the first part of email,
                excluding @gmail.com);
            password: google account password (can be app password);
            master_token: google master token (instead of username/password
                combination);
            android_id: the id of an android device. Will be randomly generated
                if not set;

        """
        self.username = username
        self.password = password
        self.master_token = master_token
        self.android_id = android_id
        if (not self.username or not self.password) and not self.master_token:
            logging.exception(
                'You must either provide google username/password '
                'or google master token'
            )
        self.access_token = None
        self.homegraph = None
        self.access_token_date = None

    def _create_mac_string(self, num, splitter=':'):
        mac = hex(num)[2:]
        if mac[-1] == 'L':
            mac = mac[:-1]
        pad = max(12 - len(mac), 0)
        mac = '0' * pad + mac
        mac = splitter.join([mac[x:x + 2] for x in range(0, 12, 2)])
        mac = mac.upper()
        return mac

    def _get_android_id(self):
        if not self.android_id:
            mac_int = getmac()
            if (mac_int >> 40) % 2:
                raise OSError("a valid MAC could not be determined."
                              " Provide an android_id (and be"
                              " sure to provide the same one on future runs).")

            android_id = self._create_mac_string(mac_int)
            self.android_id = android_id.replace(':', '')
        return self.android_id

    def get_master_token(self):
        """
        Get google master token from username and password
        """
        if not self.master_token:
            res = perform_master_login(
                self.username,
                self.password,
                self._get_android_id()
            )
            if 'Token' not in res:
                logging.exception('[!] Could not get master token.')
                return None
            self.master_token = res['Token']
        return self.master_token

    def get_access_token(self):
        if self.access_token is None or datetime.datetime.now().timestamp() - self.access_token_date.timestamp() > 3600:
            res = perform_oauth(
                self.username,
                self.get_master_token(),
                self._get_android_id(),
                app=ACCESS_TOKEN_APP_NAME,
                service=ACCESS_TOKEN_SERVICE,
                client_sig=ACCESS_TOKEN_CLIENT_SIGNATURE
            )
            if 'Auth' not in res:
                logging.exception('[!] Could not get access token.')
                return None
            self.access_token = res['Auth']
            self.access_token_date = datetime.datetime.now()
        return self.access_token

    def get_homegraph(self):
        """
        Returns the entire Google Home Foyer V2 service
        """
        if self.homegraph is None:
            scc = grpc.ssl_channel_credentials(root_certificates=None)
            tok = grpc.access_token_call_credentials(self.get_access_token())
            ccc = grpc.composite_channel_credentials(scc, tok)

            with grpc.secure_channel(GOOGLE_HOME_FOYER_API, ccc) as channel:
                rpc_service = v1_pb2_grpc.StructuresServiceStub(channel)
                request = v1_pb2.GetHomeGraphRequest(string1="", num2="")
                response = rpc_service.GetHomeGraph(request)
                self.homegraph = response
        return self.homegraph

    def get_google_devices_json(self):
        """
        Returns a json of google devices with their
        local authentication tokens
        """

        def extract_devices(items):
            """
            Replacement for jq
            """
            devices = []
            for item in items:
                if item.local_auth_token != "":
                    device = {}
                    device['deviceName'] = item.device_name
                    device['localAuthToken'] = item.local_auth_token
                    devices.append(device)
            return devices

        homegraph = self.get_homegraph()

        devices = extract_devices(homegraph.home.devices)

        return devices
