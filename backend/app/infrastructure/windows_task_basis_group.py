"""Bind the complete original TASK basis plan to write closure and readback."""

import hashlib
import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass

from backend.app.shared.validation import MAX_SAFE_INTEGER

from .runtime_launch_journal import LaunchScope, _bytes
from .windows_config_source import LockedFileSource
from .windows_local_paths import FileIdentity
from .windows_private_record import PrivateRecordAppend
from .windows_task_basis import (
    BasisCopyReceipt,
    BasisCopySpec,
    TaskBasisSlot,
    TaskBasisTransferError,
)
from .windows_task_directories import TaskLpacDirectories

_MAX_SEAL_BYTES = 16384


@dataclass(frozen=True)
class BasisCopyPlan:
    operation_id: int
    task_id: int
    workspace_id: int
    generation: int
    source_sha256: str
    members: tuple[BasisCopySpec, ...]

    def __post_init__(self):
        identities = (self.operation_id, self.task_id, self.workspace_id, self.generation)
        if (
            any(
                type(value) is not int or not 1 <= value <= MAX_SAFE_INTEGER for value in identities
            )
            or type(self.source_sha256) is not str
            or type(self.members) is not tuple
            or not self.members
            or any(
                type(member) is not BasisCopySpec
                or member.number != number
                or member.source_sha256 != self.source_sha256
                for number, member in enumerate(self.members, 1)
            )
            or self.byte_count > MAX_SAFE_INTEGER
        ):
            raise TaskBasisTransferError('ORIGINAL_BASIS_GROUP_PLAN_REQUIRED')

    @property
    def byte_count(self):
        return sum(member.byte_count for member in self.members)

    @property
    def sha256(self):
        return hashlib.sha256(_bytes(asdict(self))).hexdigest()


@dataclass(frozen=True)
class BasisGroupEvidence:
    scope: LaunchScope
    binding_ref: str
    plan_sha256: str
    receipts_sha256: str
    document_count: int
    byte_count: int


def basis_group_evidence(plan, scope, binding_ref, receipts):
    """Both owners bind the same ordered, verified receipts to one original plan."""
    if (
        type(plan) is not BasisCopyPlan
        or type(scope) is not LaunchScope
        or scope.operation_id != plan.operation_id
        or type(receipts) is not tuple
        or len(receipts) != len(plan.members)
    ):
        raise TaskBasisTransferError('ORIGINAL_BASIS_GROUP_RECEIPTS_REQUIRED')
    digest = hashlib.sha256()
    identities = set()
    for spec, receipt in zip(plan.members, receipts, strict=True):
        if (
            type(receipt) is not BasisCopyReceipt
            or receipt.scope != scope
            or receipt.binding_ref != binding_ref
            or receipt.spec != spec
            or type(receipt.file) is not FileIdentity
            or receipt.file.is_directory is not False
        ):
            raise TaskBasisTransferError('ORIGINAL_BASIS_GROUP_RECEIPT_DIFFERS')
        identity = (receipt.file.volume_serial, receipt.file.file_id)
        if identity in identities:
            raise TaskBasisTransferError('ORIGINAL_BASIS_GROUP_RECEIPT_REUSED')
        identities.add(identity)
        digest.update(_bytes(asdict(receipt)))
    return BasisGroupEvidence(
        scope,
        binding_ref,
        plan.sha256,
        digest.hexdigest(),
        len(plan.members),
        plan.byte_count,
    )


class TaskBasisGroup:
    """One Guard-owned group. Missing or unconfirmed members never publish a seal."""

    def __init__(self, directories, plan, *, cancelled):
        if (
            type(directories) is not TaskLpacDirectories
            or type(plan) is not BasisCopyPlan
            or not callable(cancelled)
            or directories.scope.step_no != 4
            or directories.scope.operation_id != plan.operation_id
            or directories._basis_plan_sha256 != plan.sha256
        ):
            raise TaskBasisTransferError('ORIGINAL_BASIS_GROUP_SCOPE_DIFFERS')
        self._dirs, self.plan, self._lifetime_cancelled = directories, plan, cancelled
        self._action_cancelled = None
        self._journal = directories._actions._journal
        self._package = self._journal._package
        self._slots, self._receipts = {}, {}
        self._closing = False
        self._finish_requested = False
        self._seal_may_have_been_published = False
        self._name = directories.scope.key + '.task-basis-complete.json'
        with self._journal._scope(directories.scope):
            self._checkpoint()
            if directories._basis_group is not None or self._read_seal() is not None:
                raise TaskBasisTransferError('ORIGINAL_BASIS_GROUP_ALREADY_REGISTERED')
            directories.verify()
            self._role = directories._directories['basis']
            self._directory = self._role.verify().file
            directories._basis_group = self

    def _cancelled(self):
        return self._lifetime_cancelled() or (
            self._action_cancelled is not None and self._action_cancelled()
        )

    @contextmanager
    def action(self, cancelled):
        with self._journal._scope(self._dirs.scope):
            previous = self._action_cancelled
            self._action_cancelled = cancelled
            try:
                self._checkpoint()
                yield self
            finally:
                self._action_cancelled = previous

    def _checkpoint(self):
        if self._closing:
            raise TaskBasisTransferError('ORIGINAL_BASIS_GROUP_CLOSED')
        self._dirs._require_open(self._cancelled)

    def offer(self, number):
        if type(number) is not int or not 1 <= number <= len(self.plan.members):
            raise TaskBasisTransferError('ORIGINAL_BASIS_GROUP_MEMBER_NOT_PLANNED')
        with self._journal._scope(self._dirs.scope), self._dirs._controller.creation_handle():
            self._checkpoint()
            if number in self._slots:
                raise TaskBasisTransferError('ORIGINAL_BASIS_WRITER_ALREADY_OFFERED')
            slot = TaskBasisSlot(
                self._dirs, self.plan.members[number - 1], cancelled=self._cancelled
            )
            self._slots[number] = slot
            try:
                return slot._offer_once()
            except BaseException as error:
                error.retained_owner = self
                raise

    def _slot(self, number):
        if type(number) is not int or number not in self._slots:
            raise TaskBasisTransferError('ORIGINAL_BASIS_GROUP_MEMBER_NOT_OFFERED')
        return self._slots[number]

    def pin_written(self, number):
        with self._journal._scope(self._dirs.scope):
            self._checkpoint()
            self._slot(number).pin_written()

    def confirm(self, receipt):
        if type(receipt) is not BasisCopyReceipt or type(receipt.spec) is not BasisCopySpec:
            raise TaskBasisTransferError('ORIGINAL_BASIS_COPY_RECEIPT_DIFFERS')
        with self._journal._scope(self._dirs.scope):
            self._checkpoint()
            slot = self._slot(receipt.spec.number)
            original = slot.confirm(receipt)
            self._receipts[receipt.spec.number] = original
            return original

    def _read_seal(self):
        path = self._package.path / self._name
        try:
            path.lstat()
        except FileNotFoundError:
            return None
        expected = self._package.verify_member(self._name, directory=False)
        with LockedFileSource(path, max_file_bytes=_MAX_SEAL_BYTES, expected_file=expected) as held:
            return held.snapshot.raw

    def _verify_inventory(self):
        if self._role.verify().file != self._directory:
            raise TaskBasisTransferError('ORIGINAL_BASIS_GROUP_DIRECTORY_DIFFERS')
        remaining = {spec.filename for spec in self.plan.members}
        with os.scandir(self._role.path) as entries:
            for entry in entries:
                self._checkpoint()
                if entry.name not in remaining:
                    raise TaskBasisTransferError('ORIGINAL_BASIS_GROUP_TREE_DIFFERS')
                remaining.remove(entry.name)
        if remaining:
            raise TaskBasisTransferError('ORIGINAL_BASIS_GROUP_TREE_DIFFERS')

    def _complete_evidence(self):
        self._checkpoint()
        if len(self._receipts) != len(self.plan.members):
            raise TaskBasisTransferError('ORIGINAL_BASIS_GROUP_INCOMPLETE')
        self._verify_inventory()
        originals = []
        for spec in self.plan.members:
            self._checkpoint()
            originals.append(self._slot(spec.number).confirm(self._receipts[spec.number]))
        self._verify_inventory()
        return basis_group_evidence(
            self.plan, self._dirs.scope, self._dirs.binding_ref, tuple(originals)
        )

    def _seal_bytes(self, evidence):
        return _bytes(
            {
                'schema_version': 1,
                'prepare_input_sha256': self._dirs._original.input_sha256,
                'owner_epoch': self._dirs._original.owner_epoch,
                'directory': asdict(self._directory),
                'evidence': asdict(evidence),
            }
        )

    def finish(self):
        with self._journal._scope(self._dirs.scope), self._dirs._controller.creation_handle():
            evidence = self._complete_evidence()
            raw = self._seal_bytes(evidence)
            with self._journal._gate:
                self._checkpoint()
                existing = self._read_seal()
                if existing is None:
                    if self._seal_may_have_been_published:
                        raise TaskBasisTransferError('ORIGINAL_BASIS_GROUP_SEAL_OUTCOME_UNVERIFIED')
                    with PrivateRecordAppend(
                        self._package,
                        self._name,
                        raw,
                        max_record_bytes=_MAX_SEAL_BYTES,
                    ) as pending:
                        self._seal_may_have_been_published = True
                        pending.publish()
                if self._read_seal() != raw:
                    raise TaskBasisTransferError('ORIGINAL_BASIS_GROUP_SEAL_DIFFERS')
            self._checkpoint()
            return evidence

    def verify(self):
        with self._journal._scope(self._dirs.scope), self._dirs._controller.creation_handle():
            evidence = self._complete_evidence()
            if self._read_seal() != self._seal_bytes(evidence):
                raise TaskBasisTransferError('ORIGINAL_BASIS_GROUP_SEAL_UNVERIFIED')
            self._checkpoint()
            return evidence

    def close(self):
        with self._journal._scope(self._dirs.scope):
            self._closing = True
            for number, slot in reversed(tuple(self._slots.items())):
                slot.close()
                del self._slots[number]
