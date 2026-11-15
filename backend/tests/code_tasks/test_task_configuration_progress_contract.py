"""Both public decoders preserve the original configuration application frontier."""

import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from backend.app.code_tasks.task_configuration_live_records import (
    project_live_configuration_operation,
)
from backend.app.shared.validation import InvalidInput

KINDS = ('BLOCK_NEW', 'QUIESCE_IF_REQUIRED', 'APPLY_PAIR', 'VERIFY_EFFECTIVE')


def instant(second):
    return f'2026-11-12T00:00:{second:02d}.000Z'


def operation(status, states):
    fixed = {
        'task_id': 10,
        'expected_state_version': 1,
        'execution_profile_version_id': 20,
        'authorization_id': 21,
        'reason': '明确应用',
    }
    terminal = status in ('SUCCEEDED', 'CANCELLED')
    row = {
        'id': 77,
        'task_id': 10,
        'testing_task_id': None,
        'resource_kind': 'TASK',
        'resource_id': 10,
        'session_id': 11,
        'operation_type': 'APPLY_CONFIGURATION',
        'idempotency_key': '00000000-0000-4000-8000-00000000000a',
        'expected_state_version': 1,
        'fixed_input': fixed,
        'control_generation': 1,
        'status': status,
        'created_at': instant(0),
        'started_at': instant(0),
        'ended_at': instant(9) if terminal else None,
        'failure_code': {
            'RUNNING': None,
            'UNKNOWN': 'EXTERNAL_RESULT_UNKNOWN',
            'SUCCEEDED': None,
            'CANCELLED': 'TASK_ENDED',
        }[status],
        'content_capture': None,
        'steps': [],
    }
    results = [
        {'state_version': 2},
        {'scope': 'CURRENT_SESSION'},
        {'configuration_application_id': 30},
        {'configuration_application_id': 30, 'start_operation_id': 3},
    ]
    for index, (kind, state) in enumerate(zip(KINDS, ('SUCCEEDED', *states), strict=True)):
        started = None if state == 'PENDING' else instant(index * 2 - 1 if index else 0)
        ended = None
        observed = None if state == 'PENDING' else instant(index * 2)
        if state == 'SUCCEEDED':
            ended = instant(9 if index == 3 else index * 2)
            observed = ended
        elif state == 'CANCELLED':
            started = ended = observed = instant(9)
        row['steps'].append(
            {
                'operation_id': 77,
                'step_no': index + 1,
                'step_type': kind,
                'status': state,
                'external_identity': None,
                'fixed_input': deepcopy(fixed),
                'result_ref': deepcopy(results[index]) if state == 'SUCCEEDED' else None,
                'started_at': started,
                'ended_at': ended,
                'last_observed_at': observed,
            }
        )
    return row


def valid_operations():
    rows = [operation('SUCCEEDED', ['SUCCEEDED'] * 3)]
    for completed in range(3):
        for active in ('PENDING', 'RUNNING'):
            rows.append(
                operation(
                    'RUNNING', ['SUCCEEDED'] * completed + [active] + ['PENDING'] * (2 - completed)
                )
            )
        rows.append(
            operation(
                'UNKNOWN', ['SUCCEEDED'] * completed + ['UNKNOWN'] + ['PENDING'] * (2 - completed)
            )
        )
        rows.append(
            operation('CANCELLED', ['SUCCEEDED'] * completed + ['CANCELLED'] * (3 - completed))
        )
    return rows


def invalid_operations():
    base = operation('UNKNOWN', ['SUCCEEDED', 'UNKNOWN', 'PENDING'])
    rows = []
    for field, value in [
        ('status', 'RUNNING'),
        ('failure_code', None),
        ('ended_at', instant(9)),
        ('session_id', None),
    ]:
        row = deepcopy(base)
        row[field] = value
        rows.append(row)
    for index, field, value in [
        (1, 'status', 'PENDING'),
        (1, 'result_ref', {'scope': 'NO_INSTANCE'}),
        (1, 'ended_at', None),
        (2, 'external_identity', {'nonce': 'private'}),
        (2, 'started_at', instant(1)),
        (2, 'ended_at', instant(5)),
        (2, 'result_ref', {'configuration_application_id': 30}),
        (3, 'status', 'SUCCEEDED'),
        (3, 'last_observed_at', instant(6)),
    ]:
        row = deepcopy(base)
        row['steps'][index][field] = value
        rows.append(row)
    row = deepcopy(base)
    row['steps'][2]['fixed_input']['expected_state_version'] = True
    rows.append(row)
    row = operation('RUNNING', ['SUCCEEDED', 'SUCCEEDED', 'PENDING'])
    row['steps'][2]['result_ref']['configuration_application_id'] = True
    rows.append(row)
    row = operation('RUNNING', ['SUCCEEDED', 'SUCCEEDED', 'SUCCEEDED'])
    row['steps'][3]['ended_at'] = row['steps'][3]['last_observed_at'] = instant(7)
    rows.append(row)
    row = operation('SUCCEEDED', ['SUCCEEDED'] * 3)
    row['steps'][3]['result_ref']['configuration_application_id'] = 31
    rows.append(row)
    return rows


@pytest.mark.parametrize('row', valid_operations())
def test_live_configuration_frontier_and_independent_success_times_are_readable(row):
    assert project_live_configuration_operation(row, 77) == row


@pytest.mark.parametrize('row', invalid_operations())
def test_live_configuration_rejects_out_of_order_or_premature_public_facts(row):
    with pytest.raises((ValueError, KeyError, TypeError, InvalidInput)):
        project_live_configuration_operation(row, 77)


def test_frontend_and_backend_use_the_same_public_frontier_vectors_without_artifacts():
    root = Path(__file__).resolve().parents[3]
    program = """
import { readFileSync } from 'node:fs';
import { decodeConfigurationOperation } from './frontend/src/api/code-task-configuration.ts';
const vectors = JSON.parse(readFileSync(0, 'utf8'));
for (const [valid, rows] of [[true, vectors.valid], [false, vectors.invalid]]) {
  for (const [index, row] of rows.entries()) {
    let accepted = true;
    try { decodeConfigurationOperation(row); } catch { accepted = false; }
    if (accepted !== valid) throw new Error('Configuration decoder vector ' + valid + ':' + index);
  }
}
process.stdout.write('PUBLIC_DECODER_PARITY=' + (vectors.valid.length + vectors.invalid.length));
"""
    result = subprocess.run(
        ['node', '--input-type=module', '-e', program],
        cwd=root,
        input=json.dumps({'valid': valid_operations(), 'invalid': invalid_operations()}),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'PUBLIC_DECODER_PARITY=30'
