import pytest

from backend.app.code_tasks.task_basis import TaskBasisUnavailable, read_task_basis
from backend.tests.code_tasks.test_task_stop import seed_task
from backend.tests.documents.test_v15_documents import document, metadata
from backend.tests.documents.test_v15_editing import candidate, finish, save, start
from backend.tests.infrastructure.test_v20_command_http import package, service


def test_fixed_originals_follow_main_and_document_id_order_across_later_edits(service):
    database, app, client = service
    runtime = app.state.walle_runtime
    task_id = seed_task(database, runtime, client)
    workspace = (database, runtime.commands(), runtime.catalog)

    def edit(document_id, version, markdown):
        draft = start(workspace, identity=document_id, version=version)['data']['manual_draft']
        saved = save(workspace, draft, candidate(workspace, draft, markdown))
        return finish(workspace, saved['data'])['data']['revision_id']

    first = document(workspace, kind='DESIGN', name='固定附录一')['data']
    second = document(workspace, kind='DESIGN', name='固定附录二')['data']
    first_id, second_id = first['document']['id'], second['document']['id']
    body = '\ufeff材料内容\r\n第二行\n'
    material = edit(second_id, 1, body)
    for doc_id, version, revision in (
        (first_id, 1, first['revision_id']),
        (second_id, 2, material),
    ):
        result = metadata(
            workspace,
            doc_id,
            1,
            {'type': 'CONFIRM', 'expected_content_version': version, 'revision_id': revision},
        )
        assert result['code'] == 'UPDATED', result

    with database.transaction(write=True) as connection:
        connection.executemany(
            'INSERT INTO code_task_materials(task_id,document_id,revision_id) VALUES(?,?,?)',
            [(task_id, second_id, material), (task_id, first_id, first['revision_id'])],
        )
        task = dict(
            connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        )

    updated = edit(second_id, 2, '稍后修改的材料\n')
    with database.transaction() as connection:
        refs, metadata_only = read_task_basis(connection, task)
        same_refs, basis = read_task_basis(connection, task, include_originals=True)
        assert same_refs == refs
        assert [ref['document_id'] for ref in refs] == [first_id, second_id]
        assert metadata_only.originals == ()
        assert [item.document_id for item in basis.originals] == [
            task['document_id'],
            first_id,
            second_id,
        ]
        assert [item.revision_id for item in basis.originals] == [
            task['design_revision_id'],
            first['revision_id'],
            material,
        ]
        assert [item.utf8 for item in basis.originals] == [
            '原固定设计\n'.encode(),
            b'',
            body.encode('utf-8'),
        ]
        assert basis.differences == [
            {
                'document_id': second_id,
                'fixed_revision_id': material,
                'current_revision_id': updated,
            }
        ]
        with pytest.raises(TaskBasisUnavailable) as rejected:
            read_task_basis(
                connection, {**task, 'design_revision_id': updated}, include_originals=True
            )
        assert rejected.value.code == 'CONTENT_NOT_READY'

    response = client.get(f'/api/v1/code-tasks/{task_id}')
    assert response.status_code == 200, response.text
    assert response.json()['data']['material_refs'] == refs
    assert response.json()['data']['current_basis_difference'] == basis.differences
    assert 'markdown_snapshot' not in response.text and '材料内容' not in response.text
