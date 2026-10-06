"""D-003 single process task ownership, serial monitor and bounded drain.

HTTP acceptance calls dispatch only after its successful native commit. Tasks
are in-memory execution handles, never a substitute for actual persistent runs.
"""
import asyncio
from collections import deque
from datetime import datetime, timezone
from time import monotonic

from backend.app.infrastructure.execution_lease import ExecutionLease, ExecutionRetired, LeasedDatabase
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.idempotency import Idempotency
from backend.app.infrastructure.audit_repository import AuditRepository
from backend.app.infrastructure.counting_journal import CountingJournal
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_integer
from .commands import recover_runs, fail_guide_run
from .orchestrator import execute_guide_run, _native

MONITOR_SECONDS = 30
SHUTDOWN_GRACE_SECONDS = 10


class WorkerStartupFailed(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__('Worker startup refused: '+code)


class GuideWorker:
    def __init__(self, database, *, catalog=None, clock=lambda: datetime.now(timezone.utc),
                 orchestrator_options=None):
        self.database = database
        self.catalog = ResourceCatalog() if catalog is None else catalog
        self.clock = clock
        self.process_lock = ProcessLock.for_database(database.path)
        self.executor = None
        self._options = {} if orchestrator_options is None else dict(orchestrator_options)
        if set(self._options) - {'profile', 'gateway', 'context_compiler', 'compatibility_check', 'sleep','counting_counter','counting_compatibility_check'}:
            raise ValueError('Only private diagnostic ORCH dependencies are injectable')
        self._tasks = {}; self._leases = {}; self._resubmit = set()
        self._loop = None; self._monitor = None; self._scan_lock = asyncio.Lock()
        self.accepting = False; self.started = False
        self.events = deque(maxlen=512)  # Diagnostics, not business persistence.

    @property
    def live_run_ids(self):
        return frozenset(identity for identity, task in self._tasks.items() if not task.done())

    async def start(self):
        if self.started: raise RuntimeError('Worker already started')
        # Verify existing schema before acquiring the exclusive process owner;
        # startup never initializes, drops or migrates an application database.
        def verify():
            with self.database.transaction(): pass
        await _native(verify)
        try:
            await _native(self.process_lock.acquire)
            self.executor = Idempotency(self.database, self.process_lock, clock=self.clock)
            cleared = await _native(self.executor.recover_previous_process)
            recovery = await _native(recover_runs, self.database, {'recovery_reason': 'STARTUP',
                'live_run_ids': set(), 'operation_time': operation_time(self.clock)}, process_lock=self.process_lock)
            if recovery['code'] not in ('RECOVERED', 'RECOVERY_NO_CHANGE'):
                raise WorkerStartupFailed(recovery['code'])
            self._loop = asyncio.get_running_loop(); self.started = self.accepting = True
            self.events.append({'event': 'STARTED', 'cleared_claims': cleared, 'recovery': recovery})
            self._monitor = asyncio.create_task(self._monitor_loop(), name='walle-no-progress')
            return recovery
        except BaseException:
            if self.process_lock.owner_epoch is not None: self.process_lock.release()
            self.executor = None
            raise

    def dispatch(self, identity):
        strict_integer(identity, 'guide_run_id')
        if not self.accepting or asyncio.get_running_loop() is not self._loop:
            self.events.append({'event': 'DISPATCH_REJECTED', 'guide_run_id': identity})
            return False
        previous = self._tasks.get(identity)
        if previous is not None and not previous.done():
            # A new user may continue just after C07 committed WAITING_USER
            # while the previous coroutine is returning its frozen receipt.
            # One coalesced replay only observes the actual persisted state;
            # it neither creates new business input nor retries a failed run.
            self._resubmit.add(identity)
            return False
        lease = ExecutionLease()
        task = asyncio.create_task(self._drive(identity, lease), name='walle-guide-'+str(identity))
        self._tasks[identity] = task; self._leases[identity] = lease
        task.add_done_callback(lambda completed: self._finished(identity, completed))
        return True

    async def _drive(self, identity, lease):
        try:
            outcome = await execute_guide_run(LeasedDatabase(self.database, lease), {'guide_run_id': identity},
                process_lock=self.process_lock, catalog=self.catalog, clock=self.clock, **self._options)
            self.events.append({'event': 'RUN_RETURNED', 'guide_run_id': identity, 'code': outcome['code']})
        except (asyncio.CancelledError, ExecutionRetired):
            self.events.append({'event': 'RUN_RETIRED', 'guide_run_id': identity})
        except Exception:
            self.events.append({'event': 'RUN_EXCEPTION', 'guide_run_id': identity})
            if not lease.retired:
                result = await _native(fail_guide_run, self.database, {'guide_run_id': identity,
                    'error_code': 'INTERNAL_ERROR', 'safe_message': '系统处理失败，请稍后重试'},
                    process_lock=self.process_lock, clock=self.clock)
                self.events.append({'event': 'FAILURE_RETURNED', 'guide_run_id': identity, 'code': result['code']})

    def _finished(self, identity, task):
        if self._tasks.get(identity) is not task: return
        self._tasks.pop(identity, None); self._leases.pop(identity, None)
        if not task.cancelled(): task.exception()  # Consume native exception, never print its text.
        repeat = identity in self._resubmit; self._resubmit.discard(identity)
        if repeat and self.accepting: self.dispatch(identity)

    async def cancel_connection(self, identity):
        # Called only after logical C03 cancellation has committed. The SQL
        # fence and local connection cancellation do not promise remote refund.
        strict_integer(identity, 'guide_run_id')
        self._resubmit.discard(identity)
        lease, task = self._leases.get(identity), self._tasks.get(identity)
        if lease is not None: await asyncio.to_thread(lease.retire)
        if task is not None and not task.done(): task.cancel()

    async def check_no_progress(self, *, scheduled_at=None):
        if self._scan_lock.locked():
            self.events.append({'event': 'SCAN_COALESCED'}); return None
        async with self._scan_lock:
            started = monotonic()
            result = await _native(recover_runs, self.database, {'recovery_reason': 'NO_PROGRESS',
                'live_run_ids': set(self.live_run_ids), 'operation_time': operation_time(self.clock)},
                process_lock=self.process_lock)
            self.events.append({'event': 'SCAN_RETURNED', 'code': result['code'],
                'delay_seconds': max(0, started-scheduled_at) if scheduled_at is not None else 0,
                'duration_seconds': max(0, monotonic()-started)})
            if result['code'] in ('RECOVERED', 'RECOVERY_NO_CHANGE'):
                for identity in result['data']['recovered_run_ids']: await self.cancel_connection(identity)
                def prune():
                    self.process_lock.assert_owned()
                    with self.database.transaction(write=True) as connection:
                        return AuditRepository(connection).prune_raw(operation_time(self.clock))
                try:
                    count = await _native(prune)
                    self.events.append({'event': 'AUDIT_PRUNED', 'count': count})
                    count_records=await _native(CountingJournal(self.database,self.process_lock).prune_raw,operation_time(self.clock))
                    if count_records:self.events.append({'event':'COUNT_RAW_PRUNED','count':count_records})
                except Exception:
                    self.events.append({'event': 'AUDIT_PRUNE_FAILED'})
            return result

    async def _monitor_loop(self):
        due = monotonic()+MONITOR_SECONDS
        try:
            while self.accepting:
                await asyncio.sleep(max(0, due-monotonic()))
                if not self.accepting: break
                started = monotonic()
                try: await self.check_no_progress(scheduled_at=due)
                except asyncio.CancelledError: raise
                except Exception: self.events.append({'event': 'MONITOR_EXCEPTION'})
                # One missed check runs immediately, no overlapping/backlog
                # fanout. After that scan, plan from its actual start again.
                due = max(due+MONITOR_SECONDS, started+MONITOR_SECONDS)
        except asyncio.CancelledError: pass

    async def after_commit(self, result):
        """Use actual application success before HTTP projection may fail."""
        try:
            code, data = result['code'], result['data']
            if code == 'CREATED' and set(data) == {'requirement', 'current_document_id', 'guide_run_id'}:
                identity = data['guide_run_id']
            elif code == 'GUIDE_ACCEPTED':
                identity = data['guide_run']['id'] if 'guide_run' in data else data['id']
            elif code == 'CARDS_ACCEPTED':
                identity = data['guide_run']['id']
            elif code in ('GUIDE_CONTINUED', 'GUIDE_RETRY_ACCEPTED'):
                identity = data['id']
            elif code == 'GUIDE_CANCELLED':
                await self.cancel_connection(data['id']); return
            else: return
            self.dispatch(identity)
        except Exception:
            # Already committed acceptance stays observable/replayable. The
            # no-progress/startup paths handle a dispatch that could not start.
            self.events.append({'event': 'DISPATCH_EXCEPTION'})

    async def close(self):
        if not self.started: return None
        self.accepting = False; self._resubmit.clear()
        if self._monitor is not None:
            self._monitor.cancel()
            await self._monitor
            self._monitor = None
        tasks = set(self._tasks.values())
        waited = monotonic()
        if tasks: _, remaining = await asyncio.wait(tasks, timeout=SHUTDOWN_GRACE_SECONDS)
        else: remaining = set()
        self.events.append({'event': 'DRAINED', 'wait_seconds': monotonic()-waited, 'remaining': len(remaining)})
        # Fence every old synchronous stage before releasing ownership. A slow
        # CPU stage can finish later but cannot commit after retirement.
        for lease in tuple(self._leases.values()): await asyncio.to_thread(lease.retire)
        for task in remaining: task.cancel()
        recovery = None
        try:
            recovery = await _native(recover_runs, self.database, {'recovery_reason': 'STARTUP',
                'live_run_ids': set(), 'operation_time': operation_time(self.clock)}, process_lock=self.process_lock)
            self.events.append({'event': 'CLOSED_RECOVERY', 'code': recovery['code']})
        finally:
            self.process_lock.release(); self.executor = None; self.started = False
        return recovery
