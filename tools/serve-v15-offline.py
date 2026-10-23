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
            return output(context, response_type='DOCUMENT_RESULT', document_result={'name': target['name'], 'document_kind': target['document_kind'],
                'markdown_content': '# 目标\n\n记录电影、评分并推荐下一部电影。\n\n# 范围\n\n先支持个人记录与评分。\n', 'change_summary': '离线浏览器明确生成'})
        if operation in ('REVISE', 'PROPOSE_CHANGES'):
            document = next(item for item in context.input['documents'] if 'TARGET' in item['roles'])
            block = next(item for item in document['blocks'] if item['writable'] and item['block_type'] == 'paragraph')
            if operation == 'PROPOSE_CHANGES':
                patch = {'title': '补充推荐规则', 'explanation': '根据本次指令明确推荐范围', 'impact': None, 'patch_operation': 'REPLACE_BLOCK',
                    'target_ref': {'block_id': block['block_id']}, 'selector_json': None, 'original_content': block['markdown_content'],
                    'proposed_markdown': '优先推荐尚未观看且评分偏好匹配的电影。\n', 'proposed_data_json': None}
                return output(context, response_type='CHANGE_PROPOSALS', suggestions=[patch])
            scope = request['scope']['scope_type'];blocks = document['blocks']
            markdown = '\n'.join(item['markdown_content'] for item in blocks if scope == 'DOCUMENT' or item['writable'])
            markdown = markdown.replace(block['markdown_content'], '用户明确修订后的电影推荐规则。\n')
            return output(context, response_type='DOCUMENT_RESULT', document_result={'name': document['name'], 'document_kind': document['document_kind'],
                'markdown_content': markdown, 'change_summary': '离线浏览器明确修订'})
        if operation in ('COMPARE', 'REVIEW'):
            return output(context, response_type='ANALYSIS', analysis={'conclusion': 'RESULT', 'summary': '离线检查无新增修改', 'findings': [],
                'covered_refs': [document['ref'] for document in context.input['documents']], 'unresolved': []})
        if '[phase]' in (request['content'] or ''):
            return output(context, cards=group('PHASE_CHANGE', {'phase_kind': 'SOLUTION', 'closure_summary': '用户确认后进入方案',
                'unresolved_refs': [], 'basis_discussion_version': request['basis_ref']['discussion_version']}))
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
