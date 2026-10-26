"""One V1.5 round: bounded count candidates, one Chat, one C07 commit."""
import asyncio
from dataclasses import replace

from backend.app.infrastructure.audit_repository import AuditRepository
from backend.app.infrastructure.counting_journal import CountingJournal
from backend.app.infrastructure.guide_repository import GuideRepository
from backend.app.infrastructure.model_gateway import ModelGateway
from backend.app.infrastructure.tokenization import TokenizationGateway, TokenCounts, ExactCountUnavailable, check_text_capacity
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.infrastructure.execution_lease import ExecutionRetired
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.shared.command_execution import Rejected, operation_time
from .collaboration_context import read_canonical, compile_context
from .collaboration_counting import compile_counted, restore_candidate_measurement
from .collaboration_results import persist_collaboration_result
from .response_display import response_text


def _canonical(database, identity, catalog):
    with database.transaction() as connection:
        return read_canonical(connection, identity, catalog)


class _Counter:
    def __init__(self, database, lock, identity, canonical, catalog, counter, native, clock, admission_guard):
        self.database, self.identity, self.canonical, self.catalog, self.counter, self.native, self.clock = database, identity, canonical, catalog, counter, native, clock
        self.journal = CountingJournal(database, lock)
        self.admission_guard = admission_guard

    def check(self):
        current = _canonical(self.database, self.identity, self.catalog)
        if self.catalog.collaboration.serialize('Canonical', current) != self.catalog.collaboration.serialize('Canonical', self.canonical):
            raise Rejected('SOURCE_INVALID')

    async def count(self, profile, texts):
        await self.admission_guard()
        await self.native(self.check)
        candidate = None
        for history, background in ((False, False), (True, False), (True, True)):
            context = compile_context(self.canonical, self.catalog, omit_history=history, omit_background=background)
            if context.texts == texts:
                candidate = context;break
        if candidate is None:
            raise ConfigInvalid('Count belongs to no valid candidate')
        record = await self.native(self.journal.prepare_collaboration, self.identity, candidate, profile, operation_time(self.clock), self.catalog.collaboration)
        try:
            await self.admission_guard()
            await self.native(self.check)
            check_text_capacity(profile, texts)
            receipt = await self.counter.count(profile, texts)
            if type(receipt) is not TokenCounts:
                raise ConfigInvalid('Exact count receipt required')
            restore_candidate_measurement(receipt.evidence, texts, profile, self.catalog)
        except asyncio.CancelledError:
            try:
                await self.native(self.journal.finish, record, profile, operation_time(self.clock), status='INTERRUPTED')
            except (ExecutionRetired, StorageUnavailable):
                pass
            raise
        except ExecutionRetired:
            raise
        except ExactCountUnavailable as error:
            await self.native(self.journal.finish, record, profile, operation_time(self.clock),
                status='INTERRUPTED' if error.reason == 'TRANSPORT_ERROR' else 'FAILED',
                failure_reason=error.reason, http_status=error.http_status, provider_error=error.provider_error)
            raise
        except Exception:
            await self.native(self.journal.finish, record, profile, operation_time(self.clock), status='FAILED')
            raise
        receipt = replace(receipt, journal_id=record)
        await self.native(self.journal.finish, record, profile, operation_time(self.clock), status='SUCCEEDED', measurement=receipt.evidence)
        return receipt


def _prepare(database, identity, profile, context, catalog, clock, admission, observation=None):
    with database.transaction(write=True) as connection:
        return dict(AuditRepository(connection).prepare_collaboration(identity, profile, context, operation_time(clock), catalog=catalog, admission=admission, observation=observation))


async def execute_collaboration(database, identity, *, process_lock, catalog, profile, gateway, counting_counter, native, state, fail, clock, observation=None):
    from backend.app.infrastructure.collaboration_admission import CollaborationAdmission
    admission = CollaborationAdmission(database, process_lock, catalog)
    if observation is not None:
        from backend.app.infrastructure.collaboration_observation import CollaborationObservation
        if type(observation) is not CollaborationObservation:
            raise ConfigInvalid('Only the explicit isolated observation capability is permitted')
        counting_counter = observation.counter(TokenizationGateway() if counting_counter is None else counting_counter)
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
    await admitted()
    canonical = await native(_canonical, database, identity, catalog)
    counter = _Counter(database, process_lock, identity, canonical, catalog,
        TokenizationGateway() if counting_counter is None else counting_counter, native, clock, admitted)
    context = await compile_counted(canonical, catalog, profile, counter=counter, admission_guard=admitted)
    proof = await admitted()
    prepared = await native(_prepare, database, identity, profile, context, catalog, clock, proof, observation)
    # Preparation is durable. Check cancellation and the execution lease again
    # before I/O; neither a duplicate dispatcher nor an expired task may send.
    await admitted()
    row, last = await state()
    from .contracts import execute_guide_run_result
    if row['status'] != 'RUNNING':
        return execute_guide_run_result('AI_STOPPED', row, last)
    process_lock.assert_owned()
    wire = await (ModelGateway() if gateway is None else gateway).send(profile, context)
    from .orchestrator import _transport, _parse
    await native(_transport, database, prepared['id'], wire, profile, clock)
    row, last = await state()
    if row['status'] != 'RUNNING':
        return execute_guide_run_result('AI_STOPPED', row, last)
    if wire.succeeded:
        await native(_parse, database, prepared['id'], clock)
    if response_text(wire.raw_response) is None:
        return await fail('OUTPUT_INVALID' if wire.succeeded else 'MODEL_ERROR')
    await native(persist_collaboration_result, database, prepared['id'], process_lock=process_lock, profile=profile, catalog=catalog, clock=clock)
    row, last = await state()
    return execute_guide_run_result('AI_FINISHED', row, last)
