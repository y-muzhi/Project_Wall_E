"""The original C05 ref write fence and private receipt references."""

from dataclasses import asdict, dataclass

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.git_baseline_ref_transaction import (
    RefCommitPermit,
    RefProcessBinding,
)
from backend.app.infrastructure.git_receipt_store import GitReceiptStore
from backend.app.infrastructure.git_receipts import (
    GitReceipt,
    GitReceiptBinding,
    GitReceiptFacts,
    GitRefObservation,
)
from backend.app.infrastructure.guard_control_git_input import (
    BASELINE_REF_COMMAND_REF,
    CONFIG_COMMAND_REF,
)
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown
from backend.app.infrastructure.schema_transport import compact
from backend.app.infrastructure.windows_local_paths import FileIdentity
from backend.app.infrastructure.windows_private_record import PrivateRecordReference
from backend.app.shared.command_execution import operation_time

from .repository_baseline_validation import original_baseline
from .repository_git_dispatch import VALIDATION_FAILURES, _RepositoryReadDispatch

_MAX_RECEIPT_BYTES = 4096
_MAX_RECEIPTS = 100000


@dataclass(frozen=True)
class OriginalPinDispatch:
    process: RefProcessBinding
    prepared: PrivateRecordReference
    dispatch: PrivateRecordReference
    location_sha256: str

    def result(self, confirmed, file):
        return {
            'process': {**asdict(self.process), 'location_sha256': self.location_sha256},
            'prepared': asdict(self.prepared),
            'dispatch': asdict(self.dispatch),
            'committed': asdict(confirmed),
            'ref': asdict(file),
        }


class BaselinePinGitDispatch(_RepositoryReadDispatch):
    """Retain the same two PIN_COMMIT scopes and the exact ref transaction."""

    _commands = (CONFIG_COMMAND_REF, BASELINE_REF_COMMAND_REF)
    _external_key = 'git_baseline_pin'
    _step_no = 2

    def __init__(self, runtime, frames, binding, journal):
        super().__init__(runtime, frames, binding, journal)
        self._receipts = None

    @staticmethod
    def _active_step(connection, operation_id, *, allow_unknown=False):
        operation, _, steps = original_baseline(connection, operation_id)
        states = ('RUNNING', 'UNKNOWN') if allow_unknown else ('RUNNING',)
        if (
            operation['status'] not in states
            or steps[0]['status'] != 'SUCCEEDED'
            or steps[1]['status'] != operation['status']
            or any(step['status'] != 'PENDING' for step in steps[2:])
        ):
            raise StorageUnavailable('Original baseline PIN_COMMIT step is not active')
        return steps[1]

    def _require_preparation(self, original, request, decoded):
        super()._require_preparation(original, request, decoded)
        if original.command_ref == BASELINE_REF_COMMAND_REF:
            intent = decoded.metadata.ref_intent
            with self._runtime.database.transaction() as connection:
                _, fixed, _ = original_baseline(connection, original.scope.operation_id)
            if (
                intent is None
                or intent.resource_id != fixed['snapshot_id']
                or intent.full_ref != fixed['retention_ref']
                or intent.new_oid != fixed['commit_oid']
            ):
                raise StorageUnavailable('Original baseline ref reservation differs')

    def _receipt(self, phase, facts):
        return self._receipts.append(
            GitReceipt(self._receipts._binding, phase, operation_time(None), facts)
        )

    def _open_receipts(self, pin, prepared, source, proof, intent):
        if (
            self._receipts is not None
            or prepared['metadata_source']['ref_intent_sha256'] != intent.input_sha256
            or prepared['metadata_source']['metadata_sha256'] != proof.repository_sha256
        ):
            raise StorageUnavailable('Original baseline receipt binding differs')
        binding = GitReceiptBinding(
            pin.scope,
            prepared['guard_run_ref'],
            source.repository_id,
            proof.repository_sha256,
            intent.new_oid,
            intent.object_format,
        )
        self._receipts = GitReceiptStore(
            self._journal,
            binding,
            max_receipt_bytes=_MAX_RECEIPT_BYTES,
            max_records=_MAX_RECEIPTS,
            unique_phases=True,
        )

    def reopen_commit_dispatch(self, operation_id, source, proof, intent):
        config, pin = self.original(operation_id)
        self._completed_query(config)
        native = self._completed_query(pin, require_zero_exit=False)
        self._open_receipts(pin, native, source, proof, intent)
        prepared = self._receipts.read_phase('PREPARED')
        dispatch = self._receipts.read_phase('COMMIT_MAY_BE_SENT')
        if (
            prepared is None
            or dispatch is None
            or prepared[1].facts
            != GitReceiptFacts(
                True, None, None, GitRefObservation(intent.full_ref, None, None), None, 'VERIFIED'
            )
            or dispatch[1].facts != GitReceiptFacts(True, None, None, None, None, 'NOT_RUN')
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_BASELINE_COMMIT_DISPATCH_UNVERIFIED')
        process = RefProcessBinding(
            pin.scope, native['stdio_binding']['io_nonce'], intent.input_sha256
        )
        return OriginalPinDispatch(
            process, prepared[0], dispatch[0], native['metadata_source']['location_sha256']
        )

    def record_observation(self, original, intent, observed):
        existing = self._receipts.read_phase('OBSERVED')
        facts = GitReceiptFacts(
            True,
            None,
            None,
            GitRefObservation(intent.full_ref, intent.new_oid, None),
            None,
            'VERIFIED',
        )
        if existing is None:
            confirmed = self._receipt('OBSERVED', facts)
        elif existing[1].facts == facts:
            confirmed = existing[0]
        else:
            raise StorageUnavailable('Original baseline observed ref differs')
        return original.result(confirmed, observed)

    def record_prepared(self, operation_id, source, proof, intent, process, lock):
        if (
            type(process) is not RefProcessBinding
            or type(lock) is not FileIdentity
            or lock.is_directory
        ):
            raise TypeError('Original baseline prepare and lock evidence required')
        _, pin = self.original(operation_id)
        prepared = self.read_action(pin, 'PREPARE', 'ACKNOWLEDGED')
        resumed = self.read_action(pin, 'RESUME', 'ACKNOWLEDGED')
        if (
            self._receipts is not None
            or prepared is None
            or resumed is None
            or process.scope != pin.scope
            or process.intent_sha256 != intent.input_sha256
            or prepared['result']['stdio_binding']['io_nonce'] != process.io_nonce
            or prepared['result']['metadata_source']['ref_intent_sha256'] != process.intent_sha256
            or prepared['result']['metadata_source']['metadata_sha256'] != proof.repository_sha256
        ):
            raise StorageUnavailable('Original baseline prepared process differs')
        self._open_receipts(pin, prepared['result'], source, proof, intent)
        evidence = self._receipt(
            'PREPARED',
            GitReceiptFacts(
                True, None, None, GitRefObservation(intent.full_ref, None, None), None, 'VERIFIED'
            ),
        )
        return evidence

    def authorize_commit(self, operation_id, process, original):
        _, pin = self.original(operation_id)
        if type(process) is not RefProcessBinding or process.scope != pin.scope:
            raise StorageUnavailable('Original baseline prepare evidence required')
        prepared = self._receipts.read_phase('PREPARED')
        if (
            prepared is None
            or prepared[0] != original
            or prepared[1].facts.prepared_ack is not True
        ):
            raise StorageUnavailable('Original baseline prepare receipt differs')
        self._receipt(
            'COMMIT_MAY_BE_SENT', GitReceiptFacts(True, None, None, None, None, 'NOT_RUN')
        )
        return RefCommitPermit(process)

    def confirm_commit(self, operation_id, process, original, intent, observed):
        _, pin = self.original(operation_id)
        prepared = self._completed_query(pin)
        if (
            type(observed) is not FileIdentity
            or observed.is_directory
            or pin.scope != process.scope
            or prepared['stdio_binding']['io_nonce'] != process.io_nonce
        ):
            raise StorageUnavailable('Original baseline commit result differs')
        dispatch = self._receipts.read_phase('COMMIT_MAY_BE_SENT')
        if dispatch is None:
            raise StorageUnavailable('Original baseline dispatch receipt is missing')
        confirmed = self._receipt(
            'COMMIT_ACK',
            GitReceiptFacts(
                True,
                True,
                0,
                GitRefObservation(intent.full_ref, intent.new_oid, None),
                None,
                'VERIFIED',
            ),
        )
        with self._runtime.database.transaction(write=True) as connection:
            step = self._active_step(connection, operation_id)
            if step['result_ref'] is not None:
                raise StorageUnavailable('Original baseline commit result already exists')
            at = operation_time(None)
            connection.execute(
                "UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,ended_at=?,last_observed_at=? "
                'WHERE operation_id=? AND step_no=2',
                (
                    compact(
                        OriginalPinDispatch(
                            process,
                            original,
                            dispatch[0],
                            prepared['metadata_source']['location_sha256'],
                        ).result(confirmed, observed)
                    ),
                    at,
                    at,
                    operation_id,
                ),
            )
        return confirmed

    def fail_validation(self, operation_id, code):
        originals = self.original(operation_id)
        if self.read_action(originals[1], 'RESUME', 'MAY_HAVE_BEEN_SENT') is not None:
            raise StorageUnavailable('Original baseline ref result requires observation')
        with (
            self._validation_cleanup(
                originals,
                code,
                allowed=VALIDATION_FAILURES | {'RESOURCE_CONFLICT'},
            ),
            self._runtime.database.transaction(write=True) as connection,
        ):
            self._active_step(connection, operation_id)
            at = operation_time(None)
            connection.execute(
                "UPDATE code_operation_steps SET status='FAILED',ended_at=?,last_observed_at=? "
                'WHERE operation_id=? AND step_no=2',
                (at, at, operation_id),
            )
            connection.execute(
                "UPDATE code_operations SET status='FAILED',ended_at=?,failure_code=? WHERE id=?",
                (at, code, operation_id),
            )

    def close(self):
        if self._receipts is not None:
            self._receipts.close()
            self._receipts = None
        super().close()
