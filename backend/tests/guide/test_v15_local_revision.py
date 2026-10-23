"""Local-only model output, exact scope stitching and immutable outside IDs."""
import json
import pytest

from backend.tests.requirements.test_v15_foundation import tmp_path, setup
from backend.tests.documents.test_v15_documents import workspace, document
from backend.tests.documents.test_v15_editing import start, candidate, save, finish
from backend.tests.guide.test_v15_acceptance import accept
from backend.tests.guide.test_v15_execution import execute, Gateway, output
from backend.tests.guide.test_v15_counting import offline_gate
from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.guide.queries import get_guide_run


def seed(workspace, markdown):
    current = document(workspace)['data']['document'];draft = start(workspace, current['id'])['data']['manual_draft']
    saved = save(workspace, draft, candidate(workspace, draft, markdown));assert saved['code'] == 'DRAFT_SAVED', saved
    assert finish(workspace, saved['data'])['code'] == 'DRAFT_COMPLETED'
    with workspace[0].transaction() as connection:
        return dict(DocumentRepository(connection).get_current(1, current['id']))


def revise(workspace, current, scope, markdown):
    result = accept(workspace, operation='REVISE', target={'kind': 'EXISTING', 'document_id': current['id'], 'expected_content_version': 2}, scope=scope)
    assert result['code'] == 'GUIDE_ACCEPTED', result
    gateway = Gateway(lambda context: output(context, response_type='DOCUMENT_RESULT', document_result={
        'name': current['name'], 'document_kind': 'brief', 'markdown_content': markdown, 'change_summary': '局部修订'}))
    result = execute(workspace, gateway);assert result['code'] == 'AI_FINISHED', result
    with workspace[0].transaction() as connection:
        actual = dict(DocumentRepository(connection).get_current(1, current['id']))
    return get_guide_run(workspace[0], 1)['data'], actual, gateway.calls[0]


def test_section_local_output_inserts_inside_and_preserves_identical_outside_blocks_by_frozen_position(workspace, monkeypatch):
    offline_gate(monkeypatch);current = seed(workspace, '重复\n\n# 章节\n\n重复\n\n# 尾章\n\n重复\n')
    run, actual, context = revise(workspace, current, {'scope_type': 'SECTION', 'scope_ref': {'heading_block_id': 2}}, '# 章节\n\n新增内容\n\n重复\n')
    assert run['application_result'] == 'APPLIED', run
    assert actual['markdown_content'] == '重复\n\n# 章节\n\n新增内容\n\n重复\n\n# 尾章\n\n重复\n'
    assert [item['block_id'] for item in json.loads(actual['block_state_json'])['blocks']] == [1, 2, 6, 3, 4, 5]
    assert context.input_json.count('新增内容') == 0
    assert 'SECTION范围只返回该章节' in context.system


@pytest.mark.parametrize('outside', [False, True])
def test_selection_local_full_block_uses_unicode_anchor_and_rejects_changes_beyond_selected_span(workspace, monkeypatch, outside):
    offline_gate(monkeypatch);current = seed(workspace, '前言\n\n# 章节\n\n正文甲😀末尾\n\n# 尾章\n\n保留\n')
    scope = {'scope_type': 'SELECTION', 'scope_ref': {'block_id': 3, 'selected_text': '甲', 'prefix_text': '正文', 'suffix_text': '😀末尾'}}
    run, actual, _ = revise(workspace, current, scope, '越权乙😀末尾' if outside else '正文乙😀末尾')
    assert run['application_result'] == ('NOT_APPLIED' if outside else 'APPLIED'), run
    assert actual['content_version'] == (2 if outside else 3)
    assert actual['markdown_content'] == current['markdown_content'].replace('甲', '乙') if not outside else actual['markdown_content'] == current['markdown_content']


def test_identical_local_block_without_final_newline_is_no_change_without_new_content(workspace, monkeypatch):
    offline_gate(monkeypatch);current = seed(workspace, '前言\n\n目标原文\n\n尾文\n')
    run, actual, _ = revise(workspace, current, {'scope_type': 'BLOCK', 'scope_ref': {'block_id': 2}}, '目标原文')
    assert run['application_result'] == 'NO_CHANGE' and run['document_effect']['after_content_version'] == 2, run
    assert actual['markdown_content'] == current['markdown_content']
