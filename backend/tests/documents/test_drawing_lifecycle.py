"""A drawing uses the existing document, draft and revision transactions."""

import json
from uuid import uuid4

from backend.app.documents.commands import create_document
from backend.app.documents.drawing import END_FENCE, FENCE, empty_drawing
from backend.app.documents.queries import get_current_document
from backend.app.revisions.queries import get_revision
from backend.tests.documents.test_v15_editing import candidate, finish, save, start
from backend.tests.documents.test_v15_documents import setup, workspace

__all__ = ['setup', 'workspace']


def test_picture_scene_saves_and_restores_the_original_revision(workspace):
    database, executor, catalog = workspace
    creation = {
        'requirement_id': 1,
        'name': '流程图',
        'document_kind': 'DRAWING',
        'template_ref': None,
        'initial_content': 'EMPTY',
        'idempotency_key': str(uuid4()),
    }
    result = create_document(executor, creation, catalog=catalog)
    assert result['code'] == 'CREATED', result
    assert create_document(executor, creation, catalog=catalog) == result
    document = result['data']['document']
    identity = document['id']
    assert document['document_kind'] == 'DRAWING'
    assert document['markdown_content'] == empty_drawing()
    assert len(document['block_state_json']['blocks']) == 1
    initial_revision = result['data']['revision_id']

    opened = start(workspace, identity=identity)
    assert opened['code'] == 'DRAFT_STARTED', opened
    draft = opened['data']['manual_draft']
    scene = json.loads(empty_drawing()[len(FENCE) : -len(END_FENCE)])
    scene['elements'].append(
        {
            'id': 'one',
            'type': 'image',
            'isDeleted': False,
            'x': 0,
            'y': 0,
            'width': 1,
            'height': 1,
            'fileId': 'pixel',
            'status': 'saved',
        }
    )
    block_id = draft['block_state_json']['blocks'][0]['block_id']

    def snapshot():
        markdown = FENCE + json.dumps(scene, separators=(',', ':')) + END_FENCE
        return candidate(workspace, draft, markdown, identities=[block_id])

    rejected = save(workspace, draft, snapshot())
    assert rejected['code'] == 'DOCUMENT_INVALID'
    scene['files']['pixel'] = {
        'id': 'pixel',
        'mimeType': 'image/png',
        'dataURL': (
            'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAA'
            'AAC0lEQVR42mP8/x8AAwMCAO+jWqkAAAAASUVORK5CYII='
        ),
    }
    picture = snapshot()
    result = save(workspace, draft, picture)
    assert result['code'] == 'DRAFT_SAVED', result
    assert get_current_document(database, 1, identity, catalog=catalog)['data'] == document
    finished = finish(workspace, result['data'])
    assert finished['code'] == 'DRAFT_COMPLETED', finished
    revision_id = finished['data']['revision_id']
    recorded = get_revision(database, revision_id, catalog=catalog)['data']
    assert recorded['markdown_content'] == picture.parsed.markdown

    restored = start(workspace, identity=identity, version=2, restore=initial_revision)
    assert restored['code'] == 'DRAFT_STARTED', restored
    assert restored['data']['manual_draft']['markdown_content'] == empty_drawing()
    result = finish(workspace, restored['data']['manual_draft'])
    assert result['data']['after_content_version'] == 3, result
    assert get_revision(database, revision_id, catalog=catalog)['data'] == recorded
