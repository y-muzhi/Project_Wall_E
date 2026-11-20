"""New EV fixtures can exercise each real C07 task; bad outputs remain rejected."""

import asyncio
import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools'))
from formation_evaluation_execution import protected_facts
from formation_evaluation_fixture import prepare_sample
from formation_evaluation_spec import Sample, samples

from backend.app.guide.orchestrator import execute_guide_run
from backend.app.infrastructure.collaboration_admission import CollaborationAdmission
from backend.app.infrastructure.collaboration_observation import CollaborationObservation
from backend.app.infrastructure.formation_database import FormationDatabase
from backend.app.infrastructure.formation_schema_release import load_release
from backend.app.infrastructure.model_profile import ModelProfile
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.shared.command_execution import operation_time
from backend.tests.formation.test_v21_proposal_contracts import group
from backend.tests.guide.test_v15_counting import Counter
from backend.tests.guide.test_v15_execution import Gateway, output

PROFILE = ModelProfile('offline-only-v29-examples', 'deepseek-v2')


def formation_progress(context, changes):
    return {
        'topic_changes': [],
        'evidence_changes': [],
        'focus_topic_ref': None,
        'next_step': None,
        'processed_user_message_ids': [],
        'formation_delta': {
            'basis': deepcopy(context.input['project_position']['formation']['basis']),
            'changes': changes,
        },
    }


def task_output(sample, context):
    current = context.input['current_request']['message_ref']
    formation = context.input['project_position']['formation']
    basis = formation['basis']
    value = output(context)
    if sample.task == 'write':
        cards = group()
        payload = cards['action_payload']
        payload.update(
            step_ref='s2',
            result_refs=['s2.o1'],
            document_revision_id=basis['document_revision_id'],
            content_version=basis['content_version'],
            goal_version=basis['goal_version'],
            definition_version=formation['selected_step']['definition_version'],
            source_refs=[current],
        )
        if basis['content_version'] == 1:
            payload.update(markdown_content='用户选择影片，系统给出三条推荐。\n')
        else:
            block = context.input['documents'][0]['blocks'][0]
            payload.update(
                write_mode='PATCH_EXISTING',
                markdown_content=None,
                scope={'scope_type': 'BLOCK', 'scope_ref': {'block_id': block['block_id']}},
                patches=[
                    {
                        'title': '明确推荐数量',
                        'explanation': '按本轮任务给出精确内容',
                        'impact': None,
                        'target_ref': {'block_id': block['block_id']},
                        'original_content': block['markdown_content'],
                        'patch_operation': 'REPLACE_BLOCK',
                        'selector_json': None,
                        'proposed_markdown': '用户选择影片，系统给出三条推荐。\n',
                        'proposed_data_json': None,
                    }
                ],
            )
        value['cards'] = cards
    elif sample.task == 'path':
        cards = group('FORMATION_PATH_CHANGE')
        changes = []
        for number, kind in ((1, 'CONTENT'), (2, 'ANALYSIS')):
            changes.append(
                {
                    'type': 'ADD_STEP',
                    'temp_step_ref': 'new_step_' + str(number),
                    'title': '推荐流程' if number == 1 else '异常与范围判断',
                    'expected_results': [
                        {
                            'temp_result_ref': 'new_result_' + str(number),
                            'description': '推荐流程' if number == 1 else '范围判断',
                            'kind': kind,
                        }
                    ],
                    'dependencies': ['s1'] if number == 1 else ['new_step_1'],
                    'replaces_step_refs': ['s2'],
                    'before_step_ref': 's3',
                }
            )
        changes.extend(
            [
                {'type': 'SET_DEPENDENCIES', 'step_ref': 's3', 'dependencies': ['new_step_2']},
                {'type': 'MOVE_ISSUE', 'issue_ref': 'i1', 'to_step_ref': 'new_step_2'},
                {'type': 'SET_BRANCH_RETURN', 'branch_ref': 'b4', 'return_step_ref': 'new_step_2'},
                {
                    'type': 'CANCEL_STEP',
                    'step_ref': 's2',
                    'replacement_step_refs': ['new_step_1', 'new_step_2'],
                },
            ]
        )
        cards['action_payload'] = {
            'basis': deepcopy(basis),
            'changes': changes,
            'result_routes': [
                {
                    'from_result_ref': 's2.o' + str(number),
                    'disposition': 'REPLACED',
                    'target_result_refs': ['new_result_' + str(number)],
                    'reason': '按原种类完整保留要求',
                }
                for number in (1, 2)
            ],
            'change_summary': '拆分流程和异常；i2保持原归属及DEFERRED',
            'source_refs': [current],
        }
        value['cards'] = cards
    elif sample.task == 'associate':
        blocks = context.input['documents'][0]['blocks']
        value['progress_delta'] = formation_progress(
            context,
            [
                {
                    'type': 'ASSOCIATE_CONTENT',
                    'step_ref': 's2',
                    'result_refs': ['s2.o1'],
                    'document_refs': [blocks[0]['ref']],
                    'source_refs': [current],
                    'review_of': 'a1' if sample.body == 'fbase' else None,
                }
            ],
        )
    elif sample.task == 'assess':
        refs = [
            block['ref'] for document in context.input['documents'] for block in document['blocks']
        ]
        value['progress_delta'] = formation_progress(
            context,
            [
                {
                    'type': 'ASSESS_STEP',
                    'step_ref': 's2',
                    'definition_version': 1,
                    'verdict': 'UNCERTAIN',
                    'reason': '异常及范围判断依据不足',
                    'document_refs': refs,
                    'source_refs': [current],
                },
                {
                    'type': 'RECOMMEND',
                    'step_ref': 's2',
                    'action': 'NEED_MATERIAL',
                    'reason': '补充实际范围判断依据',
                    'target_step_ref': None,
                    'source_refs': [current],
                },
            ],
        )
    return value


@pytest.fixture(scope='module')
def technical_source(tmp_path_factory):
    directory = tmp_path_factory.mktemp('v29-technical-evidence')
    catalog = ResourceCatalog().for_formation_profile('deepseek-v2')
    prepare_sample(directory, catalog, samples()[0])
    database = FormationDatabase(directory / 'input.sqlite', formation_release=load_release())
    with ProcessLock.for_database(database.path) as lock:
        permit = CollaborationObservation(
            database, 1, catalog, PROFILE, count_batches=2, chat_calls=1, total_tokens=139264
        )
        result = asyncio.run(
            execute_guide_run(
                database,
                {'guide_run_id': 1},
                process_lock=lock,
                catalog=catalog,
                profile=PROFILE,
                counting_counter=Counter(['OK']),
                gateway=Gateway(),
                observation=permit,
            )
        )
        assert result['code'] == 'AI_FINISHED'
        CollaborationAdmission(database, lock, catalog).approve_saved_call(
            database.path, 1, operation_time(None)
        )
    return database.path


CASES = [
    (body, task, 'valid')
    for body in ('blank', 'fbase')
    for task in ('discuss', 'write', 'path', 'associate', 'assess')
] + [
    ('blank', 'assess', 'unknown-topic'),
    ('blank', 'path', 'missing-result-route'),
    ('fbase', 'path', 'dangling-dependency'),
    ('fbase', 'write', 'multiple-blocks'),
]


@pytest.mark.parametrize('body,task,defect', CASES)
def test_finite_ev_task_examples_and_counterexamples(
    tmp_path, technical_source, body, task, defect
):
    catalog = ResourceCatalog().for_formation_profile('deepseek-v2')
    sample = Sample(body, 3, task)
    context, _ = prepare_sample(tmp_path, catalog, sample)
    database = FormationDatabase(tmp_path / 'input.sqlite', formation_release=load_release())

    def returned(actual):
        value = task_output(sample, actual)
        if defect == 'unknown-topic':
            value['progress_delta']['next_step'] = {
                'action': 'ASK_DECISION',
                'topic_ref': 't1',
                'reason': '待确定',
                'unresolved_impacts': [],
            }
        elif defect == 'missing-result-route':
            value['cards']['action_payload']['result_routes'].pop()
        elif defect == 'dangling-dependency':
            value['cards']['action_payload']['changes'] = [
                change
                for change in value['cards']['action_payload']['changes']
                if change['type'] != 'SET_DEPENDENCIES'
            ]
        elif defect == 'multiple-blocks':
            value['cards']['action_payload']['patches'][0]['proposed_markdown'] += (
                '\n越界的第二段。\n'
            )
        return value

    with ProcessLock.for_database(database.path) as lock:
        CollaborationAdmission(database, lock, catalog).approve_saved_call(
            technical_source, 1, operation_time(None)
        )
        before = protected_facts(database)
        gateway = Gateway(returned)
        result = asyncio.run(
            execute_guide_run(
                database,
                {'guide_run_id': 1},
                process_lock=lock,
                catalog=catalog,
                profile=PROFILE,
                counting_counter=Counter(['OK']),
                gateway=gateway,
            )
        )
        assert result['code'] == 'AI_FINISHED', result
        with database.transaction() as connection:
            row = dict(connection.execute('SELECT * FROM llm_uses WHERE id=1').fetchone())
            import json

            effects = json.loads(
                connection.execute(
                    'SELECT final_result_json FROM guide_runs WHERE id=1'
                ).fetchone()[0]
            )
        assert row['validation_status'] == ('SUCCEEDED' if defect == 'valid' else 'FAILED'), effects
        assert protected_facts(database) == before
        assert len(gateway.calls) == 1
        assert gateway.calls[0].system == context.system
        assert 'V2.1本轮任务与引用规则' in context.system
        assert '本轮优先级' in context.input['current_request']['content']
        if task == 'path' and defect == 'valid':
            assert effects['proposal_result'] == 'APPLIED'
        if task == 'associate':
            assert (
                context.input['project_position']['formation']['selected_step']['status']
                == 'COMPLETED'
            )
