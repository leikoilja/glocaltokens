# Generated by the gRPC Python protocol compiler plugin. DO NOT EDIT!
"""Client and server classes corresponding to protobuf-defined services."""
from __future__ import annotations

import grpc

from glocaltokens.google.internal.home.foyer import (
    v1_pb2 as glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2,
)


class HomeControlServiceStub:
    """Home Control Service"""

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """
        self.GetAssistantRoutines = channel.unary_stream(
            "/google.internal.home.foyer.v1.HomeControlService/GetAssistantRoutines",
            request_serializer=glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2.GetAssistantRoutinesRequest.SerializeToString,
            response_deserializer=glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2.GetAssistantRoutinesResponse.FromString,
        )


class HomeControlServiceServicer:
    """Home Control Service"""

    def GetAssistantRoutines(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")


def add_HomeControlServiceServicer_to_server(servicer, server):
    rpc_method_handlers = {
        "GetAssistantRoutines": grpc.unary_stream_rpc_method_handler(
            servicer.GetAssistantRoutines,
            request_deserializer=glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2.GetAssistantRoutinesRequest.FromString,
            response_serializer=glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2.GetAssistantRoutinesResponse.SerializeToString,
        ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
        "google.internal.home.foyer.v1.HomeControlService", rpc_method_handlers
    )
    server.add_generic_rpc_handlers((generic_handler,))


# This class is part of an EXPERIMENTAL API.
class HomeControlService:
    """Home Control Service"""

    @staticmethod
    def GetAssistantRoutines(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_stream(
            request,
            target,
            "/google.internal.home.foyer.v1.HomeControlService/GetAssistantRoutines",
            glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2.GetAssistantRoutinesRequest.SerializeToString,
            glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2.GetAssistantRoutinesResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
        )


class StructuresServiceStub:
    """Structure Service"""

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """
        self.GetHomeGraph = channel.unary_unary(
            "/google.internal.home.foyer.v1.StructuresService/GetHomeGraph",
            request_serializer=glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2.GetHomeGraphRequest.SerializeToString,
            response_deserializer=glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2.GetHomeGraphResponse.FromString,
        )


class StructuresServiceServicer:
    """Structure Service"""

    def GetHomeGraph(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")


def add_StructuresServiceServicer_to_server(servicer, server):
    rpc_method_handlers = {
        "GetHomeGraph": grpc.unary_unary_rpc_method_handler(
            servicer.GetHomeGraph,
            request_deserializer=glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2.GetHomeGraphRequest.FromString,
            response_serializer=glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2.GetHomeGraphResponse.SerializeToString,
        ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
        "google.internal.home.foyer.v1.StructuresService", rpc_method_handlers
    )
    server.add_generic_rpc_handlers((generic_handler,))


# This class is part of an EXPERIMENTAL API.
class StructuresService:
    """Structure Service"""

    @staticmethod
    def GetHomeGraph(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/google.internal.home.foyer.v1.StructuresService/GetHomeGraph",
            glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2.GetHomeGraphRequest.SerializeToString,
            glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2.GetHomeGraphResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
        )


class HomeDevicesServiceStub:
    """Home Devices Service"""

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """
        self.GetAssistantDeviceSettings = channel.unary_stream(
            "/google.internal.home.foyer.v1.HomeDevicesService/GetAssistantDeviceSettings",
            request_serializer=glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2.GetAssistantDeviceSettingsRequest.SerializeToString,
            response_deserializer=glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2.GetAssistantDeviceSettingsResponse.FromString,
        )
        self.UpdateAssistantDeviceSettings = channel.unary_stream(
            "/google.internal.home.foyer.v1.HomeDevicesService/UpdateAssistantDeviceSettings",
            request_serializer=glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2.UpdateAssistantDeviceSettingsRequest.SerializeToString,
            response_deserializer=glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2.UpdateAssistantDeviceSettingsResponse.FromString,
        )


class HomeDevicesServiceServicer:
    """Home Devices Service"""

    def GetAssistantDeviceSettings(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def UpdateAssistantDeviceSettings(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")


def add_HomeDevicesServiceServicer_to_server(servicer, server):
    rpc_method_handlers = {
        "GetAssistantDeviceSettings": grpc.unary_stream_rpc_method_handler(
            servicer.GetAssistantDeviceSettings,
            request_deserializer=glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2.GetAssistantDeviceSettingsRequest.FromString,
            response_serializer=glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2.GetAssistantDeviceSettingsResponse.SerializeToString,
        ),
        "UpdateAssistantDeviceSettings": grpc.unary_stream_rpc_method_handler(
            servicer.UpdateAssistantDeviceSettings,
            request_deserializer=glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2.UpdateAssistantDeviceSettingsRequest.FromString,
            response_serializer=glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2.UpdateAssistantDeviceSettingsResponse.SerializeToString,
        ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
        "google.internal.home.foyer.v1.HomeDevicesService", rpc_method_handlers
    )
    server.add_generic_rpc_handlers((generic_handler,))


# This class is part of an EXPERIMENTAL API.
class HomeDevicesService:
    """Home Devices Service"""

    @staticmethod
    def GetAssistantDeviceSettings(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_stream(
            request,
            target,
            "/google.internal.home.foyer.v1.HomeDevicesService/GetAssistantDeviceSettings",
            glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2.GetAssistantDeviceSettingsRequest.SerializeToString,
            glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2.GetAssistantDeviceSettingsResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
        )

    @staticmethod
    def UpdateAssistantDeviceSettings(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_stream(
            request,
            target,
            "/google.internal.home.foyer.v1.HomeDevicesService/UpdateAssistantDeviceSettings",
            glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2.UpdateAssistantDeviceSettingsRequest.SerializeToString,
            glocaltokens_dot_google_dot_internal_dot_home_dot_foyer_dot_v1__pb2.UpdateAssistantDeviceSettingsResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
        )
