"""Native OpenAI generation/revision over real Schema210 commands, no external I/O."""

import asyncio
import json

import pytest

from backend.app.guide.orchestrator import execute_guide_run
from backend.app.guide.queries import get_guide_run
from backend.app.infrastructure.collaboration_provider import admission_for
from backend.app.infrastructure.model_profile import OPENAI_PROFILE
from backend.app.shared.command_execution import operation_time
from backend.tests.formation.test_openai_execution import PROFILE, adapters, technical_source
from backend.tests.formation.test_v21_schema import database, released, workspace
from backend.tests.guide.test_v15_acceptance import accept
from backend.tests.guide.test_v15_execution import output

__all__ = ['database', 'released', 'workspace', 'technical_source']


@pytest.mark.parametrize('operation', ('GENERATE', 'REVISE'))
def test_native_write_uses_original_single_commit_and_leaves_other_document_unchanged(
    workspace, technical_source, operation
):
    db, commands, original_catalog = workspace
    catalog = original_catalog.for_formation_profile(OPENAI_PROFILE)
    active = db, commands, catalog
    target = (
        {'kind': 'NEW', 'name': 'OpenAI新稿', 'document_kind': 'design', 'template_ref': None}
        if operation == 'GENERATE'
        else {'kind': 'EXISTING', 'document_id': 1, 'expected_content_version': 1}
    )
    with db.transaction() as connection:
        untouched = dict(
            connection.execute('SELECT * FROM requirement_documents WHERE id=2').fetchone()
        )
        before_revisions = connection.execute('SELECT count(*) FROM revisions').fetchone()[0]
    result = accept(
        active,
        operation=operation,
        target=target,
        scope=None if operation == 'GENERATE' else {'scope_type': 'DOCUMENT', 'scope_ref': None},
    )
    assert result['code'] == 'GUIDE_ACCEPTED', result

    def written(context):
        return output(
            context,
            response_type='DOCUMENT_RESULT',
            document_result={
                'name': 'OpenAI新稿' if operation == 'GENERATE' else '需求',
                'document_kind': 'design',
                'markdown_content': '# 目标\n\n通过原生接口形成的离线夹具正文。\n',
                'change_summary': '生成或修订明确目标',
            },
        )

    counter, gateway, seen = adapters(None, make=written)
    admission_for(db, commands.process_lock, catalog).approve_saved_call(
        technical_source, 1, operation_time(None)
    )
    finished = asyncio.run(
        execute_guide_run(
            db,
            {'guide_run_id': 1},
            process_lock=commands.process_lock,
            catalog=catalog,
            profile=PROFILE,
            counting_counter=counter,
            gateway=gateway,
        )
    )
    assert finished['code'] == 'AI_FINISHED', finished
    run = get_guide_run(db, 1)['data']
    assert run['status'] == 'COMPLETED' and run['application_result'] == 'APPLIED', run
    assert run['document_effect']['result'] == ('CREATED' if operation == 'GENERATE' else 'UPDATED')
    with db.transaction() as connection:
        assert (
            dict(connection.execute('SELECT * FROM requirement_documents WHERE id=2').fetchone())
            == untouched
        )
        assert (
            connection.execute('SELECT count(*) FROM revisions').fetchone()[0]
            == before_revisions + 1
        )
        use = connection.execute('SELECT * FROM llm_uses').fetchone()
        assert use['provider'] == 'openai' and use['validation_status'] == 'SUCCEEDED'
        assert json.loads(use['raw_response_json'])['object'] == 'response'
        assert (
            connection.execute(
                "SELECT count(*) FROM document_change_audits WHERE guide_run_id=1 AND event_type='CONTENT_COMMITTED'"
            ).fetchone()[0]
            == 1
        )
    assert [kind for kind, _ in seen] == ['count', 'model']
