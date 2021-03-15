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
