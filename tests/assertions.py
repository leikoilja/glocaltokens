"""Common assertion helper classes used for unittesting."""

# pylint: disable=invalid-name
from unittest import TestCase

from ghome_foyer_api.api_pb2 import GetHomeGraphResponse  # pylint: disable=no-name-in-module

from glocaltokens.client import Device
import glocaltokens.utils.token as token_utils


class DeviceAssertions(TestCase):
    """Device specific assessors."""

    def assertDevice(
        self,
        homegraph_device: Device,
        homegraph_device_struct: GetHomeGraphResponse.Home.Device,
    ) -> None:
        """Assert a Device class object is created for each received homegraph device.

        In testing, the homegraph devices that are created are of type Struct.
        """
        assert (
            homegraph_device.local_auth_token
            == homegraph_device_struct.local_auth_token
        )
        assert (
            homegraph_device.device_id == homegraph_device_struct.device_info.device_id
        )
        assert homegraph_device.device_name == homegraph_device_struct.device_name
        assert homegraph_device.cloud_device_id == (
            homegraph_device_struct.device_info.agent_info.unique_id or None
        )
        assert homegraph_device.hardware == homegraph_device_struct.hardware.model
        assert homegraph_device.manufacturer == (
            homegraph_device_struct.hardware.manufacturer or None
        )
        assert homegraph_device.software_version == (
            homegraph_device_struct.hardware.sw_version or None
        )


class TypeAssertions(TestCase):
    """Type assessors."""

    def assertIsAasEt(self, variable: str) -> None:
        """Assert the given variable follows AAS token format."""
        assert token_utils.is_aas_et(variable), (
            f"Given variable {variable} doesn't follow the AAS_ET format"
        )
