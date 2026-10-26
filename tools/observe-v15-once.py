"""Preview offline, or execute one explicitly budgeted isolated observation.

No user database, service or ordinary HTTP dispatch is used. Execution claims a
new directory before any provider I/O. Preserve that directory and its normal
database/count audit even after interruption; an existing slot cannot rerun.
Real execution still requires explicit current human authorization.
"""
import argparse
import asyncio
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def prepare(database, lock, catalog):
    from backend.app.infrastructure.idempotency import Idempotency
    from backend.app.requirements.commands import create_requirement
    from backend.app.guide.commands import create_guide_run
    executor = Idempotency(database, lock)
    created = create_requirement(executor, {'title': '电影记录观测', 'requirement_type': 'NEW',
        'initial_idea': '为个人电影记录工具明确记录、评分与推荐的范围。', 'idempotency_key': str(uuid4())})
    if created['code'] != 'CREATED':
        raise RuntimeError('Isolated requirement creation failed')
    result = create_guide_run(executor, {'requirement_id': created['data']['requirement']['id'],
        'expected_discussion_version': 1, 'operation': 'DISCUSS',
        'instruction': '请讨论首版目标、主要场景与推荐取舍，不生成文档。',
        'target': None, 'scope': None, 'source_refs': [], 'proposal_ref': None,
        'acknowledge_source_changes': False, 'idempotency_key': str(uuid4())}, catalog=catalog)
    if result['code'] != 'GUIDE_ACCEPTED':
        raise RuntimeError('Isolated observation acceptance failed')
    return result['data']['guide_run_id']


def preview(catalog):
    from backend.app.guide.collaboration_context import read_canonical, compile_context
    from backend.app.infrastructure.database import Database
    from backend.app.infrastructure.process_lock import ProcessLock
    from backend.app.infrastructure.collaboration_resources import sha256
    with TemporaryDirectory(prefix='walle-v15-observation-preview-') as directory:
        database = Database(Path(directory)/'preview.sqlite');database.initialize()
        with ProcessLock.for_database(database.path) as lock:
            identity = prepare(database, lock, catalog)
            with database.transaction() as connection:
                canonical = read_canonical(connection, identity, catalog)
            context = compile_context(canonical, catalog)
            return {'mode': 'OFFLINE_PREVIEW', 'release': catalog.collaboration.release_sha256,
                'system_sha256': sha256(context.system), 'user_sha256': sha256(context.input_json),
                'system_characters': len(context.system), 'user_characters': len(context.input_json),
                'count_batches_sent': 0, 'chat_calls_sent': 0,
                'input_limit': 131072, 'output_limit': 8192, 'total_limit': 139264, 'framing_reserve': 1024}


def observe_once(directory, *, profile, catalog, count_batches, chat_calls, total_tokens, gateway=None, counter=None):
    from backend.app.guide.orchestrator import execute_guide_run
    from backend.app.infrastructure.collaboration_admission import CollaborationAdmission, _profile_digest
    from backend.app.infrastructure.collaboration_observation import CollaborationObservation
    from backend.app.infrastructure.database import Database
    from backend.app.infrastructure.process_lock import ProcessLock
    from backend.app.infrastructure.resources import ConfigInvalid
    from backend.app.shared.command_execution import operation_time
    if type(count_batches) is not int or not 1 <= count_batches <= 3 or type(chat_calls) is not int or chat_calls != 1 or type(total_tokens) is not int or total_tokens != 139264:
        raise ConfigInvalid('Explicit count/Chat allowances and complete token budget are required')
    if _profile_digest(profile.snapshot) != catalog.collaboration.release['model_profile_sha256']:
        raise ConfigInvalid('Observation profile must match the frozen release')
    directory = Path(directory)
    if not directory.is_absolute() or not directory.parent.is_dir():
        raise ConfigInvalid('Observation requires an absolute new directory with an existing parent')
    # The durable slot is claimed even if initialization, a response or exit is
    # uncertain. Never remove/reuse it or retry provider I/O automatically.
    directory.mkdir(exist_ok=False)
    database = Database(directory/'observation.sqlite');database.initialize()
    with ProcessLock.for_database(database.path) as lock:
        identity = prepare(database, lock, catalog)
        permit = CollaborationObservation(database, identity, catalog, profile,
            count_batches=count_batches, chat_calls=chat_calls, total_tokens=total_tokens)
        result = asyncio.run(execute_guide_run(database, {'guide_run_id': identity}, process_lock=lock,
            catalog=catalog, profile=profile, gateway=gateway, counting_counter=counter, observation=permit))
        store = CollaborationAdmission(database, lock, catalog)
        state = store.current(profile.snapshot).value['state']
        with database.transaction() as connection:
            row = connection.execute('SELECT id,call_status FROM llm_uses WHERE guide_run_id=?', (identity,)).fetchone()
        if row is not None and row['call_status'] == 'SUCCEEDED' and state != 'SUSPENDED':
            try:
                state = store.approve_saved_call(database.path, row['id'], operation_time(None))['state']
            except ConfigInvalid:
                state = store.current(profile.snapshot).value['state']
        return {'mode': 'ISOLATED_OBSERVATION', 'database': str(database.path), 'release': catalog.collaboration.release_sha256,
            'result': result['code'], 'admission': state, 'count_batches_sent': permit.count_calls, 'chat_calls_sent': permit.chat_calls}


def main(argv=None):
    from backend.app.infrastructure.model_profile import ModelProfile
    from backend.app.infrastructure.resources import ResourceCatalog
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--allow-count-batches', type=int, choices=(1, 2, 3))
    parser.add_argument('--allow-chat-calls', type=int, choices=(1,))
    parser.add_argument('--max-total-tokens', type=int, choices=(139264,))
    parser.add_argument('--credential-file', type=Path, help='Explicit local credential import for execution only; never evaluated as code')
    args = parser.parse_args(argv)
    supplied = (args.output_dir, args.allow_count_batches, args.allow_chat_calls, args.max_total_tokens)
    if args.execute and any(value is None for value in supplied):
        parser.error('--execute requires an explicit new output directory and every allowance')
    if not args.execute and (any(value is not None for value in supplied) or args.credential_file is not None):
        parser.error('Execution allowances require --execute; default mode is an offline preview')
    catalog = ResourceCatalog()
    if args.execute:
        try:
            environment = None
            if args.credential_file is not None:
                import os
                from backend.app.infrastructure.local_credentials import read_local_credential
                if not args.credential_file.is_absolute():
                    raise ValueError('Credential file must be an explicit absolute path')
                environment = {**os.environ, 'WALLE_MODEL_API_KEY': read_local_credential(args.credential_file)}
            result = observe_once(args.output_dir, profile=ModelProfile.from_environment(environment), catalog=catalog,
                count_batches=args.allow_count_batches, chat_calls=args.allow_chat_calls, total_tokens=args.max_total_tokens)
        except Exception as error:
            # Credentials/provider payloads must not appear in console errors.
            print('observation_stopped='+type(error).__name__+' slot='+str(args.output_dir), file=sys.stderr)
            return 1
    else:
        result = preview(catalog)
    for name, value in result.items():
        print(name+'='+str(value))
    return 0 if result.get('mode') == 'OFFLINE_PREVIEW' or result.get('admission') == 'LIVE_VERIFIED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
