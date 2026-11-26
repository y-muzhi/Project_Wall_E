"""One V1.5 round: bounded count candidates, one Chat, one C07 commit."""

import asyncio
import json
import logging
import re
import sqlite3
from dataclasses import replace

from backend.app.infrastructure.audit_repository import AuditRepository
from backend.app.infrastructure.counting_journal import CountingJournal
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.execution_lease import ExecutionRetired
from backend.app.infrastructure.model_gateway import ModelGateway
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.infrastructure.tokenization import (
    ExactCountUnavailable,
    check_text_capacity,
)
from backend.app.shared.command_execution import Rejected, operation_time

from .collaboration_context import compile_context, read_canonical
from .collaboration_counting import compile_counted, receipt_type, restore_candidate_measurement
from .collaboration_results import persist_collaboration_result
from .response_display import response_text


def _storage_failure(identity, phase, error):
    """Retain native error identities without SQL, paths, messages or credentials."""
    errors = []
    seen = set()
    current = error
    while current is not None and len(errors) < 4 and id(current) not in seen:
        seen.add(id(current))
        item = {'kind': 'STORAGE'}
        if isinstance(current, sqlite3.Error):
            item['kind'] = 'SQLITE'
            code = getattr(current, 'sqlite_errorcode', None)
            name = getattr(current, 'sqlite_errorname', None)
            if type(code) is int and 0 <= code <= 2**31 - 1:
                item['code'] = code
            if type(name) is str and re.fullmatch(r'SQLITE_[A-Z0-9_]{1,64}', name):
                item['name'] = name
        elif isinstance(current, OSError):
            item['kind'] = 'OS'
            for field in ('errno', 'winerror'):
                value = getattr(current, field, None)
                if type(value) is int and 0 <= value <= 2**31 - 1:
                    item[field] = value
        errors.append(item)
        current = current.__cause__ or current.__context__
    try:
        logging.getLogger(__name__).warning(
            'collaboration_storage_failure run=%s phase=%s errors=%s',
            identity,
            phase,
            json.dumps(errors, separators=(',', ':')),
        )
    except (OSError, ValueError, TypeError):
        # A failed diagnostic sink must not replace the actual storage failure.
        return


def _canonical(database, identity, catalog):
    with database.transaction() as connection:
        return read_canonical(connection, identity, catalog)


class _Counter:
    def __init__(
        self, database, lock, identity, canonical, catalog, counter, native, clock, admission_guard
    ):
        (
            self.database,
            self.identity,
            self.canonical,
            self.catalog,
            self.counter,
            self.native,
            self.clock,
        ) = database, identity, canonical, catalog, counter, native, clock
        self.journal = CountingJournal(database, lock)
        self.admission_guard = admission_guard

    def check(self):
        current = _canonical(self.database, self.identity, self.catalog)
        if self.catalog.collaboration.serialize(
            'Canonical', current
        ) != self.catalog.collaboration.serialize('Canonical', self.canonical):
            raise Rejected('SOURCE_INVALID')

    async def count(self, profile, texts):
        await self.admission_guard()
        await self.native(self.check)
        candidate = None
        for history, background in ((False, False), (True, False), (True, True)):
            context = compile_context(
                self.canonical, self.catalog, omit_history=history, omit_background=background
            )
            if context.texts == texts:
                candidate = context
                break
        if candidate is None:
            raise ConfigInvalid('Count belongs to no valid candidate')
        record = await self.native(
            self.journal.prepare_collaboration,
            self.identity,
            candidate,
            profile,
            operation_time(self.clock),
            self.catalog.collaboration,
        )
        try:
            await self.admission_guard()
            await self.native(self.check)
            check_text_capacity(profile, texts)
            if profile.provider == 'openai':
                receipt = await self.counter.count_context(profile, candidate)
            else:
                receipt = await self.counter.count(profile, texts)
            if type(receipt) is not receipt_type(profile):
                raise ConfigInvalid('Exact count receipt required')
            restore_candidate_measurement(
                receipt.evidence, texts, profile, self.catalog, context=candidate
            )
        except asyncio.CancelledError:
            try:
                await self.native(
                    self.journal.finish,
                    record,
                    profile,
                    operation_time(self.clock),
                    status='INTERRUPTED',
                )
            except (ExecutionRetired, StorageUnavailable):
                pass
            raise
        except ExecutionRetired:
            raise
        except ExactCountUnavailable as error:
            await self.native(
                self.journal.finish,
                record,
                profile,
                operation_time(self.clock),
                status='INTERRUPTED' if error.reason == 'TRANSPORT_ERROR' else 'FAILED',
                failure_reason=error.reason,
                http_status=error.http_status,
                provider_error=error.provider_error,
            )
            raise
        except Exception:
            await self.native(
                self.journal.finish, record, profile, operation_time(self.clock), status='FAILED'
            )
            raise
        receipt = replace(receipt, journal_id=record)
        await self.native(
            self.journal.finish,
            record,
            profile,
            operation_time(self.clock),
            status='SUCCEEDED',
            measurement=receipt.evidence,
        )
        return receipt


def _prepare(database, identity, profile, context, catalog, clock, admission, observation=None):
    with database.transaction(write=True) as connection:
        return dict(
            AuditRepository(connection).prepare_collaboration(
                identity,
                profile,
                context,
                operation_time(clock),
                catalog=catalog,
                admission=admission,
                observation=observation,
            )
        )


async def execute_collaboration(
    database,
    identity,
    *,
    process_lock,
    catalog,
    profile,
    gateway,
    counting_counter,
    native,
    state,
    fail,
    clock,
    observation=None,
):
    from backend.app.infrastructure.collaboration_provider import admission_for, counter_for

    admission = admission_for(database, process_lock, catalog)
    if observation is not None:
        from backend.app.infrastructure.collaboration_observation import CollaborationObservation

        if type(observation) is not CollaborationObservation:
            raise ConfigInvalid('Only the explicit isolated observation capability is permitted')
        counting_counter = observation.counter(
            counter_for(profile) if counting_counter is None else counting_counter
        )
        gateway = observation.gateway(ModelGateway() if gateway is None else gateway)

    async def admitted():
        process_lock.assert_owned()
        if observation is not None:
            proof = await native(observation.check, database, identity, catalog, profile)
            process_lock.assert_owned()
            return proof
        proof = await native(admission.current, profile.snapshot)
        process_lock.assert_owned()
        catalog.collaboration.require_live(profile.snapshot, admission=proof)
        return proof

    phase = 'CHECK_ADMISSION'
    try:
        await admitted()
        phase = 'READ_CONTEXT'
        canonical = await native(_canonical, database, identity, catalog)
        counter = _Counter(
            database,
            process_lock,
            identity,
            canonical,
            catalog,
            counter_for(profile) if counting_counter is None else counting_counter,
            native,
            clock,
            admitted,
        )
        phase = 'COUNT_CONTEXT'
        context = await compile_counted(
            canonical, catalog, profile, counter=counter, admission_guard=admitted
        )
        phase = 'CHECK_ADMISSION_AFTER_COUNT'
        proof = await admitted()
        phase = 'PREPARE_MODEL_CALL'
        prepared = await native(
            _prepare, database, identity, profile, context, catalog, clock, proof, observation
        )
        # Preparation is durable. Recheck cancellation and the original lease
        # before I/O; duplicate dispatchers and retired tasks still cannot send.
        phase = 'CHECK_ADMISSION_BEFORE_SEND'
        await admitted()
        phase = 'CHECK_STATE_BEFORE_SEND'
        row, last = await state()
    except (StorageUnavailable, sqlite3.Error) as error:
        _storage_failure(identity, phase, error)
        raise
    from .contracts import execute_guide_run_result

    if row['status'] != 'RUNNING':
        return execute_guide_run_result('AI_STOPPED', row, last)
    process_lock.assert_owned()
    wire = await (ModelGateway() if gateway is None else gateway).send(profile, context)
    from .orchestrator import _parse, _transport

    await native(_transport, database, prepared['id'], wire, profile, clock)
    row, last = await state()
    if row['status'] != 'RUNNING':
        return execute_guide_run_result('AI_STOPPED', row, last)
    if catalog.collaboration.formation_driven and not wire.succeeded:
        reason = {
            'READ_TIMEOUT': '等待模型响应超时，正文未写入。',
            'RESPONSE_CAPACITY': '模型响应超过当前读取容量，正文未写入。',
        }.get(wire.category)
        return await fail('MODEL_ERROR', reason)
    if wire.succeeded:
        await native(_parse, database, prepared['id'], clock)
        if wire.finish_reason == 'length' and canonical['operation'] in (
            'GENERATE',
            'REVISE',
            'PROPOSE_CHANGES',
        ):
            return await fail('OUTPUT_INVALID', '模型输出达到本次上限，未形成完整结果。')
    if response_text(wire.raw_response) is None:
        return await fail('OUTPUT_INVALID' if wire.succeeded else 'MODEL_ERROR')
    await native(
        persist_collaboration_result,
        database,
        prepared['id'],
        process_lock=process_lock,
        profile=profile,
        catalog=catalog,
        clock=clock,
    )
    row, last = await state()
    return execute_guide_run_result('AI_FINISHED', row, last)
