"""
Common assertion helper classes used for unittesting
"""
# pylint: disable=invalid-name
from unittest import TestCase

from glocaltokens.client import Device
from glocaltokens.google.internal.home.foyer.v1_pb2 import GetHomeGraphResponse
import glocaltokens.utils.token as token_utils


class DeviceAssertions(TestCase):
    """Device specific assessors"""

    def assertDevice(
        self,
        homegraph_device: Device,
        homegraph_device_struct: GetHomeGraphResponse.Home.Device,
    ) -> None:
        """
        Custom assertion because we create Device class object
        for each of received homegraph devices,
        while in testing homegraph devices that we create are of type Struct
        """
        self.assertEqual(
            homegraph_device.local_auth_token, homegraph_device_struct.local_auth_token
        )
        self.assertEqual(
            homegraph_device.device_id, homegraph_device_struct.device_info.device_id
        )
        self.assertEqual(
            homegraph_device.device_name, homegraph_device_struct.device_name
        )
        self.assertEqual(
            homegraph_device.hardware, homegraph_device_struct.hardware.model
        )


class TypeAssertions(TestCase):
    """Type assessors"""

    def assertIsAasEt(self, variable: str) -> None:
        """Assert the given variable is a of string type and follows AAS token format"""
        self.assertTrue(
            token_utils.is_aas_et(variable),
            msg=f"Given variable {variable} doesn't follow the AAS_ET format",
        )
