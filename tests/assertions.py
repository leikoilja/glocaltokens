import glocaltokens.utils.token as token_utils


class DeviceAssertions(object):
    def assertDevice(self, homegraph_device, homegraph_device_struct):
        """
        Custom assertion because we create Device class object for each of received homegraph devices,
        while in testing homegraph devices that we create are of type Struct"""
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
    def assertIsString(self, variable):
        self.assertTrue(
            type(variable) == str, msg=f"Given variable {variable} is not String type"
        )

    def assertIsAASET(self, variable):
        self.assertTrue(
            type(variable) == str and token_utils.is_aas_et(variable),
            msg=f"Given variable {variable} doesn't follow the AAS_ET format",
        )
