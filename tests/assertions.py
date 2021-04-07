"""
Common assertion helper classes used for unittesting
"""
# pylint: disable=no-member
# pylint: disable=invalid-name
import glocaltokens.utils.token as token_utils


# pylint: disable=too-few-public-methods
class DeviceAssertions:
    """Device specific assessors"""

    def assertDevice(self, homegraph_device, homegraph_device_struct):
        """
        Custom assertion because we create Device class object
        for each of received homegraph devices,
        while in testing homegraph devices that we create are of type Struct
        """
        self.assertEqual(
            homegraph_device.local_auth_token, homegraph_device_struct.local_auth_token
        )
        self.assertEqual(
            homegraph_device.device_name, homegraph_device_struct.device_name
        )
        self.assertEqual(
            homegraph_device.hardware, homegraph_device_struct.hardware.model
        )


class TypeAssertions:
    """Type assessors"""

    def assertIsString(self, variable):
        """Assert the given variable is of string type"""
        self.assertTrue(
            isinstance(variable, str),
            msg=f"Given variable {variable} is not String type",
        )

    def assertIsAASET(self, variable):
        """Assert the given variable is a of string type and follows AAS token format"""
        self.assertTrue(
            isinstance(variable, str) and token_utils.is_aas_et(variable),
            msg=f"Given variable {variable} doesn't follow the AAS_ET format",
        )
