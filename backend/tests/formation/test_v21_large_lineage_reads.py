"""Large read fixture checks lineage paging, not 1000 model or adoption transactions."""

from time import monotonic

import pytest

from backend.app.formation.relation_queries import read_lineage
from backend.tests.formation.test_v21_content_maintenance import state
from backend.tests.formation.test_v21_relation_reads import associated
from backend.tests.formation.test_v21_schema import database, released, workspace

__all__ = ['database', 'released', 'workspace']


@pytest.mark.parametrize('anchor', ['a1', 'a501', 'a1001'])
def test_1001_member_read_fixture_crosses_all_pages_from_any_anchor_without_writes(
    workspace, anchor
):
    doc = associated(workspace)
    original = state(workspace, doc)
    artifact = original[2]
    # Explicit query preconditions only: no claim these are C07-generated review facts.
    with workspace[0].transaction(write=True) as connection:
        source = connection.execute(
            'SELECT id FROM conversation_messages WHERE document_id=? ORDER BY id LIMIT 1', (doc,)
        ).fetchone()[0]
        columns = tuple(artifact)
        for index in range(2, 1002):
            row = {**artifact, 'artifact_ref': 'a' + str(index)}
            connection.execute(
                'INSERT INTO formation_artifacts('
                + ','.join(columns)
                + ') VALUES('
                + ','.join('?' for _ in columns)
                + ')',
                tuple(row[key] for key in columns),
            )
        connection.executemany(
            'INSERT INTO formation_artifact_reviews VALUES(?,?,?,?,?,?,?,?)',
            [
                (
                    doc,
                    artifact['source_event_id'],
                    'a' + str(index),
                    'a' + str(index + 1),
                    'REASSOCIATED',
                    artifact['checked_against_revision_id'],
                    source,
                    '[]',
                )
                for index in range(1, 1001)
            ],
        )
    with workspace[0].transaction() as connection:
        count_before = connection.execute('SELECT count(*) FROM document_change_audits').fetchone()[
            0
        ]
    cursor = None
    seen = []
    pages = 0
    started = monotonic()
    while True:
        fields = {'limit': 20, **({} if cursor is None else {'cursor': cursor})}
        response = read_lineage(workspace[0], 1, doc, anchor, fields, catalog=workspace[2])
        assert response['code'] == 'READ_OK', response
        data = response['data']
        items = data['value']['items']
        assert data['value']['total'] == 1001 and data['value']['anchor_ref'] == anchor
        assert 0 < len(items) <= 20
        pages += 1
        for item in items:
            number = int(item['artifact_ref'][1:])
            assert item['predecessor_ref'] == (None if number == 1 else 'a' + str(number - 1))
            assert item['successor_ref'] == (None if number == 1001 else 'a' + str(number + 1))
            assert item['is_active'] == (number == 1001)
            seen.append(item['artifact_ref'])
        cursor = data['pagination']['next_cursor']
        if cursor is None:
            break
        assert pages <= 51
    assert pages == 51
    assert seen == ['a' + str(index) for index in range(1, 1002)]
    assert state(workspace, doc) == original
    with workspace[0].transaction() as connection:
        assert (
            connection.execute('SELECT count(*) FROM document_change_audits').fetchone()[0]
            == count_before
        )
    print('LINEAGE_1001_PAGES', pages, 'SECONDS', round(monotonic() - started, 3))
