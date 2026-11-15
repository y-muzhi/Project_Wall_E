"""Current authenticated controller facts bound to the original process epoch.

A digest is routing data, not authentication. Guard callers retain and verify
the original CLIENT peer/program; backend callers use their actual ProcessLock.
Cross-controller recovery and protocol action admission are separate policies.
"""

import hashlib
import os
from dataclasses import asdict, dataclass, field
from uuid import UUID

from .process_lock import ProcessLock
from .runtime_launch_journal import LaunchScope, _bytes
from .windows_controller_token import ControllerTokenError, _ordinary
from .windows_guard_pipe import pipe_name
from .windows_pipe_peer import NamedPipePeerLease
from .windows_process import NativeProcessIdentity, ObservedProcess


class GuardBindingError(RuntimeError):
    pass


def owner_epoch(value):
    if type(value) is not str:
        raise GuardBindingError('ORIGINAL_OWNER_EPOCH_REQUIRED')
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise GuardBindingError('ORIGINAL_OWNER_EPOCH_INVALID') from error
    if parsed.version != 4 or str(parsed) != value:
        raise GuardBindingError('CANONICAL_ORIGINAL_OWNER_EPOCH_REQUIRED')
    return value


@dataclass(frozen=True)
class GuardControllerBinding:
    installation_ref: str
    owner_epoch: str
    controller: NativeProcessIdentity = field(repr=False)

    def __post_init__(self):
        pipe_name(self.installation_ref)
        owner_epoch(self.owner_epoch)
        if type(self.controller) is not NativeProcessIdentity:
            raise TypeError('Original native controller facts required')
        try:
            _ordinary(self.controller)
        except ControllerTokenError as error:
            raise GuardBindingError('ORDINARY_ORIGINAL_CONTROLLER_REQUIRED') from error

    @property
    def controller_ref(self):
        return hashlib.sha256(
            _bytes(
                {
                    'installation_ref': self.installation_ref,
                    'owner_epoch': self.owner_epoch,
                    'controller': asdict(self.controller),
                }
            )
        ).hexdigest()

    def scope(self, operation_id, step_no, nonce):
        return LaunchScope(self.controller_ref, operation_id, step_no, nonce)

    def assert_peer(self, peer):
        if type(peer) is not NamedPipePeerLease or peer._peer_kind != 'CLIENT':
            raise GuardBindingError('ORIGINAL_AUTHENTICATED_BACKEND_PEER_REQUIRED')
        if peer.verify() != self.controller:
            raise GuardBindingError('ORIGINAL_CONTROLLER_PEER_DIFFERS')

    def assert_backend(self, process_lock):
        current = bind_backend_controller(process_lock, self.installation_ref)
        if current != self:
            raise GuardBindingError('ORIGINAL_BACKEND_EPOCH_OR_IDENTITY_CHANGED')


def bind_guard_controller(peer, epoch, installation_ref):
    """Fix one binding for this authenticated peer; never rebind it per packet."""
    if type(peer) is not NamedPipePeerLease or peer._peer_kind != 'CLIENT':
        raise GuardBindingError('ORIGINAL_AUTHENTICATED_BACKEND_PEER_REQUIRED')
    return GuardControllerBinding(installation_ref, owner_epoch(epoch), peer.verify())


def bind_backend_controller(process_lock, installation_ref):
    """Read only this process, with the caller's actual held execution lock."""
    if type(process_lock) is not ProcessLock:
        raise TypeError('Original actual process lock required')
    process_lock.assert_owned()
    epoch = process_lock.owner_epoch
    with ObservedProcess(os.getpid()) as current:
        binding = GuardControllerBinding(installation_ref, epoch, current.identity)
    process_lock.assert_owned()
    if process_lock.owner_epoch != epoch:
        raise GuardBindingError('ORIGINAL_BACKEND_EPOCH_CHANGED')
    return binding
