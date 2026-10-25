"""Common assertion helper classes used for unittesting."""

# pylint: disable=invalid-name
from unittest import TestCase

from ghome_foyer_api.api_pb2 import HomeGraph  # pylint: disable=no-name-in-module

from glocaltokens.client import Device
import glocaltokens.utils.token as token_utils


class DeviceAssertions(TestCase):
    """Device specific assessors."""

    def assertDevice(
        self,
        homegraph_device: Device,
        homegraph_device_struct: HomeGraph.Device,
    ) -> None:
        """Assert a Device class object is created for each received homegraph device.

        In testing, the homegraph devices that are created are of type Struct.
        """
        assert (
            homegraph_device.local_auth_token
            == homegraph_device_struct.local_auth_token
        )
        assert homegraph_device.device_id == homegraph_device_struct.id.device_id
        assert homegraph_device.device_name == homegraph_device_struct.display_name
        assert homegraph_device.cloud_device_id == (
            homegraph_device_struct.id.agent_info.unique_id or None
        )
        assert homegraph_device.hardware == homegraph_device_struct.hardware.model


class TypeAssertions(TestCase):
    """Type assessors."""

    def assertIsAasEt(self, variable: str) -> None:
        """Assert the given variable follows AAS token format."""
        assert token_utils.is_aas_et(variable), (
            f"Given variable {variable} doesn't follow the AAS_ET format"
        )
