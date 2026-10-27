"""Explicit temporary browser fixture: real app/SQLite, private offline AI only.

No environment credentials, user DB, fixed user port or retained test artifacts.
Run with --serve; send 'stop' or close stdin to clean up the owned test process.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
from time import monotonic, sleep

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', action='store_true', required=True)
    parser.parse_args()
    import uvicorn
    from backend.app.service import create_app
    from backend.app.guide.worker import GuideWorker
    from backend.app.infrastructure.database import Database
    from backend.app.infrastructure.resources import ResourceCatalog, ConfigInvalid
    from backend.app.infrastructure.collaboration_resources import CollaborationResources
    from backend.app.infrastructure.model_profile import ModelProfile, DEFAULT_PROFILE
    from backend.tests.guide.test_v15_counting import Counter
    from backend.tests.guide.test_v15_execution import Gateway, output, delta
    from backend.tests.guide.test_v15_cards import group
    from backend.tests.guide.test_v15_progress import topic, evidence

    profile = ModelProfile('private-offline-browser-fixture', DEFAULT_PROFILE)
    catalog = ResourceCatalog();catalog.collaboration
    def private_admission(self, snapshot, **private):
        if snapshot != profile.snapshot: raise ConfigInvalid('Offline fixture profile mismatch')
    CollaborationResources.require_live = private_admission  # This process only; never a published release change.

    def returned(context):
        request = context.input['current_request'];operation = request['operation']
        target = request['target']
        if operation == 'GENERATE':
            markdown = '# 目标\n\n记录电影、评分并推荐下一部电影。\n\n# 范围\n\n先支持个人记录与评分。\n'
            if '[bulk-review]' in (request['content'] or ''):
                # Private browser fixture only; no product setting or provider.
                markdown = '# 目标与背景\n\n' + '\n\n'.join(
                    '第'+str(index)+'项：电影推荐应根据观影记录、评分偏好和当前情境提供明确建议，同时保留用户自行选择的空间。（用户陈述，m'+str(index)+'）'
                    for index in range(1, 16)) + '\n'
            if '[layout]' in (request['content'] or ''):
                markdown += '\n# 明细\n\n| 记录 | 说明 | 约束 |\n| --- | --- | --- |\n'
                markdown += ''.join('| '+str(index)+' | '+'推荐规则与长说明'*12+' | 保留用户记录 |\n' for index in range(1, 41))
                markdown += '\n# 补充说明\n\n'+'\n\n'.join('第'+str(index)+'段：保留文档阅读位置与独立对话输入。' for index in range(1, 81))+'\n'
            return output(context, response_type='DOCUMENT_RESULT', document_result={'name': target['name'], 'document_kind': target['document_kind'],
                'markdown_content': markdown, 'change_summary': '离线浏览器明确生成'})
        if operation in ('REVISE', 'PROPOSE_CHANGES'):
            document = next(item for item in context.input['documents'] if 'TARGET' in item['roles'])
            block = next(item for item in document['blocks'] if item['writable'] and item['block_type'] == 'paragraph')
            if operation == 'PROPOSE_CHANGES':
                patch = {'title': '补充推荐规则', 'explanation': '根据本次指令明确推荐范围', 'impact': None, 'patch_operation': 'REPLACE_BLOCK',
                    'target_ref': {'block_id': block['block_id']}, 'selector_json': None, 'original_content': block['markdown_content'],
                    'proposed_markdown': '优先推荐尚未观看且评分偏好匹配的电影。\n', 'proposed_data_json': None}
                if '[bulk-review]' in (request['content'] or ''):
                    paragraphs = [item for item in document['blocks'] if item['writable'] and item['block_type'] == 'paragraph']
                    patches = [{**patch, 'title': '统一第'+str(index)+'项推荐说明',
                        'explanation': '去除来源标注，保留明确的产品要求与用户选择。',
                        'impact': '仅调整此段说明，保留其他建议的独立决定。',
                        'target_ref': {'block_id': item['block_id']}, 'original_content': item['markdown_content'],
                        'proposed_markdown': '第'+str(index)+'项：根据观影记录、评分偏好和当前情境提供明确推荐，并保留用户自行选择的空间。\n'}
                        for index, item in enumerate(paragraphs[:15], 1)]
                    return output(context, response_type='CHANGE_PROPOSALS', suggestions=patches)
                return output(context, response_type='CHANGE_PROPOSALS', suggestions=[patch])
            scope = request['scope']['scope_type'];blocks = document['blocks']
            markdown = '\n'.join(item['markdown_content'] for item in blocks if scope == 'DOCUMENT' or item['writable'])
            markdown = markdown.replace(block['markdown_content'], '用户明确修订后的电影推荐规则。\n')
            return output(context, response_type='DOCUMENT_RESULT', document_result={'name': document['name'], 'document_kind': document['document_kind'],
                'markdown_content': markdown, 'change_summary': '离线浏览器明确修订'})
        if operation in ('COMPARE', 'REVIEW'):
            return output(context, response_type='ANALYSIS', analysis={'conclusion': 'RESULT', 'summary': '离线检查无新增修改', 'findings': [],
                'covered_refs': [document['ref'] for document in context.input['documents']], 'unresolved': []})
        if '[fact]' in (request['content'] or ''):
            document = next(item for item in context.input['documents'] if item['document_id'] == target['document_id'])
            # Discussion grants no direct model write; C06 separately proves
            # the exact proposal and the user's formal program confirmation.
            block = next(item for item in document['blocks'] if item['block_type'] == 'paragraph')
            patch = {'title': '确认推荐范围', 'explanation': '按本轮用户原话更新', 'impact': None,
                'patch_operation': 'REPLACE_BLOCK', 'target_ref': {'block_id': block['block_id']},
                'selector_json': None, 'original_content': block['markdown_content'],
                'proposed_markdown': '首版仅推荐尚未观看的电影。\n', 'proposed_data_json': None}
            return output(context, cards=group('FACT_CONFIRMATION', {'confirmed_fact_patches': [{'patch': patch,
                'evidence': [{'message_id': request['message_id'], 'quoted_text': '仅推荐尚未观看的电影'}]}]}))
        if '[phase]' in (request['content'] or ''):
            return output(context, cards=group('PHASE_CHANGE', {'phase_kind': 'SOLUTION', 'closure_summary': '用户确认后进入方案',
                'unresolved_refs': [], 'basis_discussion_version': request['basis_ref']['discussion_version']}))
        if '[progress-layout]' in (request['content'] or ''):
            # Rich presentation fixture travels through the ordinary C07 path.
            # It cannot be selected in the product or reach a real provider.
            progress = delta(context)
            progress['topic_changes'] = [
                topic('new_t1', title='电影推荐的核心目标', purpose='明确准确推荐与探索新片的关系', assessment='SUPPORTED',
                    expected_outcomes=[{'outcome_ref': 'new_o1', 'text': '形成推荐目标', 'criterion': '区分用户喜欢与探索未知的结果。'}]),
                topic('new_t2', mainline_ref='actors', title='主要使用者与首次使用场景', purpose='梳理新用户进入与已有偏好用户的使用入口',
                    evidence_refs=['new_e2'], unresolved_impacts=['首次使用时是否允许跳过偏好录入？']),
                topic('new_t3', mainline_ref='core_flow', title='推荐结果的反馈闭环与跨设备观看历史如何共同影响下一轮推荐',
                    purpose='先明确从打开小程序、看到推荐到反馈结果的一条主路径', assessment='REVIEW_REQUIRED',
                    evidence_refs=['new_e3'], dependencies=['new_t1'],
                    unresolved_impacts=['反馈入口是否同时包含喜欢、不喜欢和已看过？', '跨设备观看历史尚未确认同步方式。'],
                    expected_outcomes=[{'outcome_ref': 'new_o1', 'text': '明确主流程', 'criterion': '描述触发、主要操作、结果与反馈。'},
                                       {'outcome_ref': 'new_o2', 'text': '确定异常处理边界', 'criterion': '标出无结果与反馈失败时的处理范围。'}]),
                topic('new_t4', mainline_ref='scope', title='首版范围', purpose='整理版本包含和暂不包含的内容',
                    assessment='NOT_STARTED', evidence_refs=[]),
            ]
            progress['evidence_changes'] = [
                evidence(assertion='推荐目标优先考虑用户已有偏好，探索新片作为独立方向。', source_refs=[request['message_ref']]),
                evidence(ref='new_e2', assertion='首版以个人使用为主；首次使用的偏好建立过程仍需讨论。',
                    applies_to=['new_t2'], topic_refs=['new_t2'], source_refs=[request['message_ref']]),
                evidence(ref='new_e3', assertion='建议把喜欢、不喜欢与已看过放在同一反馈入口，并保留独立的数据含义。',
                    origin='AI_PROPOSAL', nature='PROPOSAL', applies_to=['new_t3'], topic_refs=['new_t3'], source_refs=[request['message_ref']]),
            ]
            progress['focus_topic_ref'] = 'new_t3'
            progress['next_step'] = {'action': 'ASK_DECISION', 'topic_ref': 'new_t3',
                'reason': '先确定反馈入口的三种动作，再核对观看历史的同步边界。', 'unresolved_impacts': []}
            return output(context, progress_delta=progress)
        guide = catalog.collaboration.guide(context.input['project_position']['phase_kind'])
        progress = delta(context)
        progress['topic_changes'] = [topic('new_t1', mainline_ref=guide['mainlines'][0]['ref'])]
        progress['evidence_changes'] = [evidence(source_refs=[request['message_ref']])]
        progress['focus_topic_ref'] = 'new_t1'
        action = {'operation': 'GENERATE', 'target': {'kind': 'NEW', 'name': '电影需求说明', 'document_kind': 'brief', 'template_ref': None},
            'scope': None, 'source_refs': [request['message_ref']], 'basis_discussion_version': request['basis_ref']['discussion_version'],
            'unresolved_impacts': [], 'selectable_fields': ['target', 'source_refs']}
        return output(context, progress_delta=progress, cards=group('DOCUMENT_ACTION', action))

    with TemporaryDirectory(prefix='walle-v15-browser-') as directory:
        temporary = Path(directory);frontend = temporary/'frontend';work = temporary/'cli';work.mkdir()
        database = Database(temporary/'offline.sqlite');database.initialize()
        result = subprocess.run([r'C:\Program Files\nodejs\node.exe', 'node_modules/vite/bin/vite.js', 'build', '--outDir', str(frontend)],
            cwd=ROOT/'frontend', capture_output=True, encoding='utf-8', errors='replace')
        if result.returncode:
            print((result.stdout+result.stderr).encode('ascii', 'backslashreplace').decode(), flush=True)
            raise RuntimeError('Temporary frontend build failed')
        config = {'browser': {'browserName': 'chromium', 'isolated': True,
            'launchOptions': {'channel': 'chrome', 'headless': True}, 'contextOptions': {'viewport': {'width': 1600, 'height': 1000}}},
            'outputDir': str(work/'artifacts'), 'outputMode': 'stdout'}
        (work/'cli.config.json').write_text(json.dumps(config), encoding='utf-8')
        counter = Counter(['OK']*100);gateway = Gateway(returned)
        app = create_app(database=database, catalog=catalog, frontend_directory=frontend,
            worker_factory=lambda db, resources: GuideWorker(db, catalog=resources, orchestrator_options={
                'profile': profile, 'gateway': gateway, 'counting_counter': counter}))
        listener = socket.socket();listener.bind(('127.0.0.1', 0));port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
        thread = Thread(target=lambda: server.run(sockets=[listener]), name='walle-v15-offline-http')
        thread.start()
        try:
            deadline = monotonic()+20
            while not server.started and thread.is_alive() and monotonic()<deadline: sleep(.05)
            if not server.started: raise RuntimeError('Owned temporary server did not start')
            print('V1.5_OFFLINE_BROWSER pid='+str(os.getpid())+' port='+str(port)+' cli='+str(work), flush=True)
            for line in sys.stdin:
                if line.strip() == 'stop': break
        finally:
            server.should_exit = True;thread.join(timeout=20);listener.close()
            if thread.is_alive(): raise RuntimeError('Owned temporary server failed to drain')
            print('OFFLINE_COUNTS count_batches='+str(len(counter.calls))+' chat='+str(len(gateway.calls)), flush=True)
    print('OWNED_TEMPORARY_SERVER_STOPPED_AND_OUTPUT_CLEANED', flush=True)


if __name__ == '__main__':
    main()
