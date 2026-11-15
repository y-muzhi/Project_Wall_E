"""Original accepted model connection proof for a resumed TASK root."""

import hashlib
import socket
from dataclasses import dataclass

from .guard_task_basis_protocol import _hex, _object
from .opencode_task_launch import TaskExecutionError
from .runtime_launch_journal import _bytes
from .windows_task_endpoints import verify_task_model_connection

VERIFY_MODEL_SOURCE = 'VERIFY_MODEL_SOURCE'
MODEL_SOURCE_STATUS = 'MODEL_SOURCE'


@dataclass(frozen=True)
class ModelSourceResult:
    data: dict


@dataclass(frozen=True)
class AcceptedModelConnection:
    client: tuple[str, int]
    server: tuple[str, int]

    def __post_init__(self):
        for endpoint in (self.client, self.server):
            if (
                type(endpoint) is not tuple
                or len(endpoint) != 2
                or endpoint[0] != '127.0.0.1'
                or type(endpoint[1]) is not int
                or not 1 <= endpoint[1] <= 65535
            ):
                raise TaskExecutionError('ORIGINAL_TASK_MODEL_ENDPOINT_INVALID')
        if self.client == self.server:
            raise TaskExecutionError('ORIGINAL_TASK_MODEL_CONNECTION_DIFFERS')

    @classmethod
    def from_accept(cls, accepted):
        if (
            type(accepted) is not socket.socket
            or accepted.family != socket.AF_INET
            or accepted.type != socket.SOCK_STREAM
        ):
            raise TaskExecutionError('ORIGINAL_TASK_MODEL_ACCEPT_REQUIRED')
        try:
            return cls(accepted.getpeername(), accepted.getsockname())
        except OSError as error:
            raise TaskExecutionError('ORIGINAL_TASK_MODEL_ACCEPT_REQUIRED') from error

    def wire(self):
        return {
            'address_family': 'IPv4',
            'protocol': 'TCP',
            'client': list(self.client),
            'server': list(self.server),
        }


def decode_model_source_request(request):
    if (
        request.action != VERIFY_MODEL_SOURCE
        or request.scope.step_no != 4
        or request.recovery is not None
        or not _hex(request.binding_ref, 32)
    ):
        raise TaskExecutionError('ORIGINAL_TASK_MODEL_SCOPE_REQUIRED')
    value = _object(request.input, ('address_family', 'protocol', 'client', 'server'))
    if (
        value['address_family'] != 'IPv4'
        or value['protocol'] != 'TCP'
        or type(value['client']) is not list
        or type(value['server']) is not list
    ):
        raise TaskExecutionError('ORIGINAL_TASK_MODEL_CONNECTION_DIFFERS')
    return AcceptedModelConnection(tuple(value['client']), tuple(value['server']))


def verify_model_source(request, execution, backend_identity, checkpoint):
    accepted = decode_model_source_request(request)
    if accepted.server != execution._network.model_listener:
        raise TaskExecutionError('ORIGINAL_TASK_MODEL_LISTENER_DIFFERS')
    identity, reference = execution._native.verify_model_root(checkpoint)
    verify_task_model_connection(
        accepted.client, accepted.server, root_pid=identity.pid, backend_pid=backend_identity.pid
    )
    if execution._native.verify_model_root(checkpoint) != (identity, reference):
        raise TaskExecutionError('ORIGINAL_TASK_MODEL_ROOT_UNVERIFIED')
    return ModelSourceResult(
        {
            'binding_ref': request.binding_ref,
            'scope': request.scope.key,
            'resource_ref': reference,
            'connection_sha256': hashlib.sha256(_bytes(accepted.wire())).hexdigest(),
            'source_evidence_ref': hashlib.sha256(
                _bytes(
                    {
                        'scope': request.scope.key,
                        'binding_ref': request.binding_ref,
                        'resource_ref': reference,
                        'connection': accepted.wire(),
                        'root_pid': identity.pid,
                        'root_created': identity.creation_time_hex,
                        'backend_created': backend_identity.creation_time_hex,
                    }
                )
            ).hexdigest(),
        }
    )


def check_model_source_result(request, value):
    accepted = decode_model_source_request(request)
    _object(
        value, ('binding_ref', 'scope', 'resource_ref', 'connection_sha256', 'source_evidence_ref')
    )
    if (
        value['binding_ref'] != request.binding_ref
        or value['scope'] != request.scope.key
        or not _hex(value['resource_ref'], 32)
        or not _hex(value['source_evidence_ref'], 64)
        or value['connection_sha256'] != hashlib.sha256(_bytes(accepted.wire())).hexdigest()
    ):
        raise TaskExecutionError('ORIGINAL_TASK_MODEL_SOURCE_EVIDENCE_DIFFERS')
