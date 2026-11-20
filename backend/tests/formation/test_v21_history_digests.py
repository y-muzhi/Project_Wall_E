"""History hashes are canonical arrays, not line delimited JSON or current pages."""

import hashlib
import json
import pytest

from backend.app.formation.digests import ArrayDigest, digest_rows
from backend.app.formation.commands import complete_step
from backend.tests.formation.test_v21_schema import database, released, workspace
from backend.tests.formation.test_v21_completion_commands import seed, request

__all__ = ['database', 'released', 'workspace']


@pytest.mark.parametrize('count', (0, 1, 1005))
def test_stream_hash_equals_the_exact_full_canonical_array(count):
    rows = [{'ordinal': index + 1, '文本': '保留\r\n空白  '} for index in range(count)]
    expected = hashlib.sha256(
        json.dumps(
            rows, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False
        ).encode('utf-8')
    ).hexdigest()
    assert digest_rows(iter(rows)) == expected
    accumulator = ArrayDigest()
    assert accumulator.hexdigest() == hashlib.sha256(b'[]').hexdigest()
    for row in rows:
        accumulator.append(row)
        accumulator.hexdigest()  # Observation cannot finalize or alter the live stream.
    assert accumulator.hexdigest() == expected


def test_real_completion_freezes_protocol_kind_order_and_full_evidence_digests(workspace):
    seed(workspace, related=True)
    result = complete_step(workspace[1], request(workspace), catalog=workspace[2])
    assert result['code'] == 'UPDATED', result
    with workspace[0].transaction() as connection:
        closure = connection.execute('SELECT * FROM formation_closures').fetchone()
        rows = [
            json.loads(row[0])
            for row in connection.execute(
                'SELECT payload_json FROM formation_closure_items WHERE event_id=? ORDER BY ordinal',
                (closure['event_id'],),
            )
        ]
        assert [row['kind'] for row in rows] == ['RESULT', 'ISSUE', 'BRANCH']
        assert (
            closure['items_digest']
            == hashlib.sha256(
                json.dumps(
                    rows, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False
                ).encode()
            ).hexdigest()
        )
        for row in rows:
            identity = row.get('result_ref', row.get('ref'))
            evidence = [
                json.loads(item[0])
                for item in connection.execute(
                    'SELECT payload_json FROM formation_closure_evidence WHERE event_id=? '
                    'AND owner_kind=? AND item_ref=? ORDER BY ordinal',
                    (closure['event_id'], row['kind'], identity),
                )
            ]
            assert row['evidence_count'] == len(evidence)
            assert (
                row['evidence_digest']
                == hashlib.sha256(
                    json.dumps(
                        evidence,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(',', ':'),
                        allow_nan=False,
                    ).encode()
                ).hexdigest()
            )
        for row in connection.execute(
            'SELECT event_id,ordinal,member_digest FROM formation_event_changes'
        ):
            members = []
            for member in connection.execute(
                'SELECT * FROM formation_event_members WHERE event_id=? AND change_ordinal=? ORDER BY ordinal',
                (row['event_id'], row['ordinal']),
            ):
                members.append(
                    {
                        'ordinal': member['ordinal'],
                        'collection': member['collection'],
                        'member_key': member['member_key'],
                        'before': None
                        if member['before_json'] is None
                        else json.loads(member['before_json']),
                        'after': None
                        if member['after_json'] is None
                        else json.loads(member['after_json']),
                    }
                )
            assert (
                row['member_digest']
                == hashlib.sha256(
                    json.dumps(
                        members,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(',', ':'),
                        allow_nan=False,
                    ).encode()
                ).hexdigest()
            )
