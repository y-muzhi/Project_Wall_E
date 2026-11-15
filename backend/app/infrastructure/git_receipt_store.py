"""Private append/read of strict original-operation Git receipts.

Uses the original LaunchJournal scope lock and private package, not a second
dispatch ledger. Records are evidence only. Unknown append is reconciled through
its same filename/hash/FileID; neither rename nor Git execution is retried.
"""

import hashlib
import re
from dataclasses import replace
from threading import RLock
from uuid import uuid4

from backend.app.shared.validation import MAX_SAFE_INTEGER

from .git_receipts import PHASES, GitReceiptBinding, decode_receipt, encode_receipt
from .runtime_launch_journal import LaunchJournal
from .windows_config_source import LockedConfigSource
from .windows_local_paths import FileIdentity
from .windows_private_record import PrivateRecordAppend, PrivateRecordReference


class GitReceiptStoreError(RuntimeError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class GitReceiptStore:
    def __init__(self, journal, binding, *, max_receipt_bytes, max_records, unique_phases=False):
        if type(journal) is not LaunchJournal or type(binding) is not GitReceiptBinding:
            raise GitReceiptStoreError('ORIGINAL_GIT_RECEIPT_STORE_BINDING_REQUIRED')
        for value in (max_receipt_bytes, max_records):
            if type(value) is not int or not 1 <= value <= MAX_SAFE_INTEGER:
                raise GitReceiptStoreError('GIT_RECEIPT_STORE_LIMIT_INVALID')
        if type(unique_phases) is not bool:
            raise GitReceiptStoreError('GIT_RECEIPT_STORE_MODE_INVALID')
        self._unique_phases = unique_phases
        self._journal, self._binding = journal, binding
        self._maximum, self._max_records = max_receipt_bytes, max_records
        self._gate = RLock()
        self._pending = []
        self._retained_reads = []
        self._closing = False
        journal._verify()

    def _capacity(self):
        import os

        with os.scandir(self._journal.root) as rows:
            count = 0
            for row in rows:
                if row.name.endswith('.git.json'):
                    count += 1
                    if count >= self._max_records:
                        raise GitReceiptStoreError('GIT_RECEIPT_CAPACITY_EXHAUSTED')

    def _phase_filename(self, phase):
        if not self._unique_phases or phase not in PHASES:
            raise GitReceiptStoreError('ORIGINAL_GIT_RECEIPT_PHASE_REQUIRED')
        key = f'GIT_RECEIPT:{self._binding.scope.key}:{phase}'.encode('ascii')
        return hashlib.sha256(key).hexdigest()[:32] + '.git.json'

    def read_phase(self, phase):
        """Locate the one private record for the original scope and phase."""
        filename = self._phase_filename(phase)
        path = self._journal.root / filename
        with self._gate, self._journal._scope(self._binding.scope):
            self._journal._verify()
            try:
                path.lstat()
            except FileNotFoundError:
                return None
            identity = self._journal._package.verify_member(filename, directory=False)
            try:
                with LockedConfigSource(
                    path, max_file_bytes=self._maximum, expected_file=identity
                ) as held:
                    facts = held.verify()
                    receipt = decode_receipt(
                        facts.raw, self._binding, max_receipt_bytes=self._maximum
                    )
                    if receipt.phase != phase:
                        raise GitReceiptStoreError('GIT_RECEIPT_ORIGINAL_PHASE_DIFFERS')
                    reference = PrivateRecordReference(
                        filename, facts.sha256, facts.byte_count, facts.file
                    )
                    return reference, receipt
            except BaseException as error:
                retained = getattr(error, 'retained_owner', None)
                if type(retained) is LockedConfigSource:
                    self._retained_reads.append(retained)
                    error.retained_owner = self
                raise

    def append(self, receipt):
        raw = encode_receipt(receipt, max_receipt_bytes=self._maximum)
        if receipt.binding != self._binding:
            raise GitReceiptStoreError('GIT_RECEIPT_ORIGINAL_BINDING_DIFFERS')
        with self._gate, self._journal._scope(self._binding.scope):
            if self._closing:
                raise GitReceiptStoreError('GIT_RECEIPT_STORE_CLOSED')
            if self._pending or self._retained_reads:
                raise GitReceiptStoreError('GIT_RECEIPT_APPEND_REQUIRES_OBSERVATION')
            filename = (
                self._phase_filename(receipt.phase)
                if self._unique_phases
                else uuid4().hex + '.git.json'
            )
            if self._unique_phases and self.read_phase(receipt.phase) is not None:
                raise GitReceiptStoreError('GIT_RECEIPT_APPEND_REQUIRES_OBSERVATION')
            self._capacity()
            writer = None
            try:
                writer = PrivateRecordAppend(
                    self._journal._package,
                    filename,
                    raw,
                    max_record_bytes=self._maximum,
                )
                self._pending.append(writer)
                reference = writer.publish()
                writer.close()
                # ACK only after the same final file can be decoded against the
                # original binding and exact immutable bytes/native identity.
                actual = self.read(reference)
                if actual != receipt:
                    raise GitReceiptStoreError('GIT_RECEIPT_PUBLISHED_FACTS_DIFFER')
                self._pending.remove(writer)
                return reference
            except BaseException as original:
                retained = getattr(original, 'retained_owner', None)
                if writer is None and type(retained) is PrivateRecordAppend:
                    self._pending.append(retained)
                error = GitReceiptStoreError('GIT_RECEIPT_APPEND_UNVERIFIED')
                error.retained_owner = self
                raise error from original

    def read(self, reference):
        if (
            type(reference) is not PrivateRecordReference
            or type(reference.filename) is not str
            or re.fullmatch(r'[0-9a-f]{32}\.git\.json', reference.filename) is None
            or type(reference.sha256) is not str
            or re.fullmatch('[0-9a-f]{64}', reference.sha256) is None
            or type(reference.byte_count) is not int
            or not 1 <= reference.byte_count <= self._maximum
            or type(reference.file) is not FileIdentity
        ):
            raise GitReceiptStoreError('ORIGINAL_GIT_RECEIPT_REFERENCE_REQUIRED')
        with self._gate, self._journal._scope(self._binding.scope):
            self._journal._verify()
            self._journal._package.verify_member(reference.filename, directory=False)
            try:
                with LockedConfigSource(
                    self._journal.root / reference.filename,
                    max_file_bytes=self._maximum,
                    expected_file=reference.file,
                ) as held:
                    snapshot = held.verify()
                    if (
                        snapshot.sha256 != reference.sha256
                        or snapshot.byte_count != reference.byte_count
                    ):
                        raise GitReceiptStoreError('GIT_RECEIPT_ORIGINAL_BYTES_DIFFER')
                    value = decode_receipt(
                        snapshot.raw, self._binding, max_receipt_bytes=self._maximum
                    )
                    held.verify()
                    return value
            except BaseException as error:
                retained = getattr(error, 'retained_owner', None)
                if type(retained) is LockedConfigSource:
                    self._retained_reads.append(retained)
                    error.retained_owner = self
                raise

    def reconcile_pending(self):
        with self._gate, self._journal._scope(self._binding.scope):
            resolved = []
            for writer in tuple(self._pending):
                try:
                    writer.close()
                    if writer._identity is None:
                        raise GitReceiptStoreError('GIT_RECEIPT_CREATED_IDENTITY_UNKNOWN')
                    reference = PrivateRecordReference(
                        writer._filename,
                        writer._sha256,
                        writer._raw_size,
                        replace(writer._identity, canonical_path=str(writer._target)),
                    )
                    receipt = self.read(reference)
                    self._pending.remove(writer)
                    resolved.append((reference, receipt))
                except BaseException as original:
                    error = GitReceiptStoreError('GIT_RECEIPT_APPEND_STILL_UNVERIFIED')
                    error.retained_owner = self
                    raise error from original
            return tuple(resolved)

    def close(self):
        with self._gate:
            self._closing = True
            for source in tuple(self._retained_reads):
                try:
                    source.close()
                except BaseException as error:
                    error.retained_owner = self
                    raise
                self._retained_reads.remove(source)
            for writer in self._pending:
                try:
                    writer.close()
                except BaseException as error:
                    error.retained_owner = self
                    raise
            # Keep unresolved original evidence and references. No path cleanup,
            # re-publication or permission to re-execute is inferred from close.
