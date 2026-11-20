"""Combined FGROW: real route/artifacts/events and explicit issue/branch read fixture."""

import ctypes
import json
import math
import platform
import sys
from ctypes import wintypes
from time import monotonic
from uuid import uuid4

from backend.app.formation.commands import update_state
from backend.app.formation.history_queries import read_history
from backend.app.formation.read_queries import get_summary, read_current, read_entities
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.tests.formation.test_v21_contracts import add_step
from backend.tests.formation.test_v21_discuss_acceptance import (
    base_workspace,
    database,
    released,
    workspace,
)
from backend.tests.formation.test_v21_real_growth_continuation import route, seed_real_growth

__all__ = ['base_workspace', 'database', 'released', 'workspace']


class ProcessMemory(ctypes.Structure):
    _fields_ = [
        ('cb', wintypes.DWORD),
        ('PageFaultCount', wintypes.DWORD),
        ('PeakWorkingSetSize', ctypes.c_size_t),
        ('WorkingSetSize', ctypes.c_size_t),
        ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
        ('QuotaPagedPoolUsage', ctypes.c_size_t),
        ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
        ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
        ('PagefileUsage', ctypes.c_size_t),
        ('PeakPagefileUsage', ctypes.c_size_t),
    ]


def memory():
    value = ProcessMemory()
    value.cb = ctypes.sizeof(value)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessMemory),
        wintypes.DWORD,
    ]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(value), value.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return {
        'working_mib': round(value.WorkingSetSize / 1048576, 2),
        'peak_working_mib': round(value.PeakWorkingSetSize / 1048576, 2),
    }


def statistics(values):
    ordered = sorted(values)
    return {
        'n': len(values),
        'p50_ms': round((ordered[9] + ordered[10]) / 2, 3),
        'p95_ms': round(ordered[math.ceil(len(ordered) * 0.95) - 1], 3),
        'max_ms': round(ordered[-1], 3),
    }


def seed_relations(workspace, document):
    # Explicit performance preconditions, not alleged C07-generated results.
    with workspace[0].transaction(write=True) as connection:
        source = connection.execute(
            'SELECT e.id,e.source_id FROM formation_artifacts a JOIN document_change_audits e '
            "ON e.id=a.source_event_id WHERE a.document_id=? AND a.artifact_ref='a1'",
            (document,),
        ).fetchone()
        source_refs = json.dumps([{'kind': 'MESSAGE', 'message_id': source['source_id']}])
        for number in range(1, 1002):
            owner = 's' + str(number)
            connection.execute(
                'INSERT INTO formation_branches VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (
                    document,
                    'b' + str(number),
                    owner,
                    owner,
                    '支线' + str(number),
                    '性能前置材料',
                    'OPEN',
                    source['id'],
                    source['id'],
                    None,
                    '[]',
                    None,
                ),
            )
            connection.execute(
                'INSERT INTO formation_issues VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (
                    document,
                    'i' + str(number),
                    owner,
                    None,
                    '问题' + str(number),
                    source_refs,
                    0,
                    'OPEN',
                    None,
                    '[]',
                    None,
                ),
            )
        connection.execute(
            'UPDATE formation_heads SET next_issue_no=1002,next_branch_no=1002 WHERE document_id=?',
            (document,),
        )


def state_command(workspace, document, action):
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, document)
    return {
        'requirement_id': 1,
        'document_id': document,
        'expected_discussion_version': root['discussion_version'],
        'discussion_command': {'type': 'FORMATION', 'action': action, 'step_ref': 's1001'},
        'idempotency_key': str(uuid4()),
    }


def test_combined_fgrow_1001_1001_1001_2002_10001_hot_read_and_command_performance(workspace):
    assert sys.platform == 'win32', 'This bounded performance probe records Windows process memory'
    start = monotonic()
    document, _snapshot = seed_real_growth(workspace)
    for offset in range(40):
        changes = [add_step(number + 1) for number in range(20)]
        for index, change in enumerate(changes):
            change['title'] = '步骤' + str(202 + offset * 20 + index)
        route(workspace, document, changes)
    seed_relations(workspace, document)
    print('COMBINED_GROWTH_READY', round(monotonic() - start, 3), memory(), flush=True)
    for number in range(10001):
        action = 'START_STEP' if number == 0 else 'PAUSE_STEP' if number % 2 else 'RESUME_STEP'
        result = update_state(workspace[1], state_command(workspace, document, action))
        assert result['code'] == 'UPDATED', result
        if number % 1000 == 0:
            print('COMBINED_EVENT_PROGRESS', number + 1, round(monotonic() - start, 3), flush=True)
    with workspace[0].transaction() as connection:
        counts = {
            table: connection.execute(
                'SELECT count(*) FROM ' + table + ' WHERE document_id=?', (document,)
            ).fetchone()[0]
            for table in (
                'formation_steps',
                'formation_branches',
                'formation_issues',
                'formation_artifacts',
                'document_change_audits',
            )
        }
        assert connection.execute('PRAGMA foreign_key_check').fetchone() is None
    assert list(counts.values())[:4] == [1001, 1001, 1001, 2002], counts
    assert counts['document_change_audits'] >= 10001
    calls = {
        'summary': lambda: read_current(
            workspace[0],
            1,
            document,
            lambda: {},
            lambda context, _request: get_summary(context.connection, context.root),
            catalog=workspace[2],
        ),
        **{
            kind: lambda kind=kind: read_entities(
                workspace[0], 1, document, kind, {'limit': 20}, catalog=workspace[2]
            )
            for kind in ('steps', 'branches', 'issues', 'artifacts')
        },
        'events': lambda: read_history(workspace[0], 1, document, 'events', {'limit': 20}),
    }
    results = {}
    for kind, call in calls.items():
        at = monotonic()
        warm = call()
        assert warm['code'] == 'READ_OK', warm
        first = (monotonic() - at) * 1000
        samples = []
        for _ in range(20):
            at = monotonic()
            response = call()
            samples.append((monotonic() - at) * 1000)
            assert response['code'] == 'READ_OK', response
        results[kind] = {**statistics(samples), 'first_warmup_ms': round(first, 3)}
        print('FGROW_PERF_READ', kind, json.dumps(results[kind]), flush=True)
    samples = []
    for number in range(21):
        action = 'PAUSE_STEP' if number % 2 == 0 else 'RESUME_STEP'
        command = state_command(workspace, document, action)
        at = monotonic()
        response = update_state(workspace[1], command)
        elapsed = (monotonic() - at) * 1000
        assert response['code'] == 'UPDATED', response
        if number:
            samples.append(elapsed)
        else:
            command_warmup = elapsed
    results['state_command'] = {**statistics(samples), 'first_warmup_ms': round(command_warmup, 3)}
    print('FGROW_PERF_COMMAND', json.dumps(results['state_command']), flush=True)
    print(
        'FGROW_PERF_ENVIRONMENT',
        json.dumps(
            {
                'windows': platform.platform(),
                'processor': platform.processor(),
                'python': sys.version.split()[0],
                'counts': counts,
                'memory': memory(),
                'seconds': round(monotonic() - start, 3),
                'measurement': (
                    'in-process production entry, request preparation excluded, '
                    'warm OS/SQLite cache'
                ),
            }
        ),
        flush=True,
    )
    assert all(
        result['p95_ms'] <= 500 for kind, result in results.items() if kind != 'state_command'
    ), results
    assert results['state_command']['p95_ms'] <= 1000, results
