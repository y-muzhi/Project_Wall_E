"""OpenAI-only readiness, isolated one-shot observation, or native service startup.

No default credential read, provider I/O, database initialization, or service
switch. Existing DeepSeek service/data/configuration are never stopped here.
"""

import argparse
import asyncio
import os
import sys
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def append(path, text):
    with path.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())


def runtime():
    from backend.app.infrastructure.sqlite_runtime import activate

    activate()


def profile_and_catalog():
    from backend.app.infrastructure.model_profile import OPENAI_PROFILE, ModelProfile
    from backend.app.infrastructure.resources import ResourceCatalog

    return ModelProfile(
        'metadata-only-openai-profile', OPENAI_PROFILE
    ), ResourceCatalog().for_formation_profile(OPENAI_PROFILE)


def check(args):
    if args.database is not None:
        runtime()
    profile, catalog = profile_and_catalog()
    if args.database is not None:
        from backend.app.infrastructure.collaboration_provider import admission_for
        from backend.app.infrastructure.formation_database import FormationDatabase
        from backend.app.infrastructure.formation_schema_release import load_release
        from backend.app.infrastructure.process_lock import ProcessLock

        database = FormationDatabase(
            args.database.resolve(), formation_release=load_release(), read_only=True
        )
        with database.transaction():
            pass
        proof = admission_for(database, ProcessLock.for_database(database.path), catalog).current(
            profile.snapshot
        )
        state = proof.value['state']
    else:
        state = catalog.collaboration.release['admission']['state']
    from backend.app.infrastructure.openai_transport import configured_proxy

    print(
        'OPENAI_READY; model='
        + profile.model_name
        + '; admission='
        + state
        + '; credentials_read=0; provider_calls=0; service_started=0; transport='
        + ('local_proxy' if configured_proxy() else 'direct')
    )
    return 0


def observe(args, *, count_limit=3):
    if type(count_limit) is not int or not 1 <= count_limit <= 3:
        raise ValueError('A count allowance from one to three is required')
    runtime()
    from formation_evaluation_fixture import prepare_sample
    from formation_evaluation_spec import samples

    from backend.app.guide.orchestrator import execute_guide_run
    from backend.app.infrastructure.collaboration_observation import CollaborationObservation
    from backend.app.infrastructure.collaboration_provider import admission_for
    from backend.app.infrastructure.formation_database import FormationDatabase
    from backend.app.infrastructure.formation_schema_release import load_release
    from backend.app.infrastructure.local_credentials import read_local_credential
    from backend.app.infrastructure.model_gateway import ModelGateway
    from backend.app.infrastructure.model_profile import OPENAI_PROFILE, ModelProfile
    from backend.app.infrastructure.openai_counting import OpenAIInputCounter
    from backend.app.infrastructure.openai_protocol import digest
    from backend.app.infrastructure.process_lock import ProcessLock
    from backend.app.shared.command_execution import operation_time

    slot = args.slot.resolve()
    report = args.report.resolve()
    if (
        slot.parent != (ROOT / 'data').resolve()
        or slot.exists()
        or args.slot.is_symlink()
        or report.exists()
        or report.is_symlink()
        or report.parent != (ROOT / 'docs/verification/v2.1').resolve()
        or report.suffix != '.md'
    ):
        raise ValueError('A fresh owned observation slot and verification Markdown are required')
    metadata, catalog = profile_and_catalog()
    # Validate the configured key locally before claiming a new observation slot.
    profile = ModelProfile(
        read_local_credential(args.credential_file, name='OPENAI_API_KEY'), OPENAI_PROFILE
    )
    if profile.snapshot != metadata.snapshot:
        raise ValueError('OpenAI observation profile differs')
    slot.mkdir(exist_ok=False)
    with report.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(
            '# OpenAI单次技术观察\n\n状态：PREPARING。仅合成样本，最多1模型请求/'
            + str(count_limit)
            + '必要整请求计数，0重试；不使用真实用户数据，不切服务。\n'
        )
        stream.flush()
        os.fsync(stream.fileno())
    from backend.app.infrastructure.openai_transport import configured_proxy

    append(report, '\nTransport: ' + (configured_proxy() or 'DIRECT') + '\n')
    chats = counts = 0
    request_hash = None
    database = None

    class Counter:
        async def count_context(self, actual, context):
            nonlocal counts
            if actual.snapshot != metadata.snapshot or counts >= count_limit:
                raise ValueError('OpenAI observation count allowance exhausted')
            append(report, '\nCOUNT_INTENT ' + digest(actual.request(context)) + '\n')
            counts += 1
            return await OpenAIInputCounter().count_context(actual, context)

    class Gateway:
        async def send(self, actual, context):
            nonlocal chats, request_hash
            if actual.snapshot != metadata.snapshot or chats != 0:
                raise ValueError('OpenAI observation model allowance exhausted')
            request_hash = digest(actual.request(context))
            append(report, '\nMODEL_INTENT ' + request_hash + '\n')
            chats += 1
            return await ModelGateway().send(actual, context)

    try:
        context, _ = prepare_sample(slot, catalog, samples()[0])
        append(
            report,
            '\nRelease-SHA256: '
            + catalog.collaboration.release_sha256
            + '\nProfile-SHA256: '
            + digest(metadata.snapshot)
            + '\nInput-SHA256: '
            + sha256(context.input_json.encode()).hexdigest()
            + '\n',
        )
        database = FormationDatabase(slot / 'input.sqlite', formation_release=load_release())
        with ProcessLock.for_database(database.path) as lock:
            permit = CollaborationObservation(
                database,
                1,
                catalog,
                profile,
                count_batches=count_limit,
                chat_calls=1,
                total_tokens=catalog.collaboration.counting['total_limit'],
            )
            result = asyncio.run(
                execute_guide_run(
                    database,
                    {'guide_run_id': 1},
                    process_lock=lock,
                    catalog=catalog,
                    profile=profile,
                    counting_counter=Counter(),
                    gateway=Gateway(),
                    observation=permit,
                )
            )
            with database.transaction() as connection:
                row = connection.execute(
                    'SELECT * FROM llm_uses ORDER BY id DESC LIMIT 1'
                ).fetchone()
            if (
                result['code'] != 'AI_FINISHED'
                or row is None
                or row['call_status'] != 'SUCCEEDED'
                or row['validation_status'] != 'SUCCEEDED'
            ):
                append(report, '\n结果：NOT_PASSED；不得重跑该槽/自动补发，保留正常审计核对。\n')
                return 1
            # A real saved call proves only this isolated release's technical
            # admission. Normal user DB/service activation remains explicit.
            proof = admission_for(database, lock, catalog).approve_saved_call(
                database.path.resolve(), row['id'], operation_time(None)
            )
            append(
                report,
                '\n结果：TECHNICAL_COMPATIBLE；输入='
                + str(row['input_tokens'])
                + '；输出='
                + str(row['output_tokens'])
                + '；同release技术状态='
                + proof['state']
                + '。不代表完整效果验收，未更新正常服务。\n',
            )
            return 0
    except BaseException as error:
        append(
            report,
            '\n状态：STOPPED；原因类别='
            + type(error).__name__
            + '；未知结果先核对INTENT及正常审计，不自动重试。\n',
        )
        raise
    finally:
        append(
            report,
            '\n实际计数尝试='
            + str(counts)
            + '；实际模型尝试='
            + str(chats)
            + '；SDK请求SHA='
            + str(request_hash)
            + '；正常数据库及计数审计保留在本槽。\n',
        )
        print(
            'OpenAI observation ended; counts='
            + str(counts)
            + '; model_attempts='
            + str(chats)
            + '; no_retry=1; service_switched=0'
        )


def start(args):
    runtime()
    from backend.app.infrastructure.collaboration_provider import admission_for
    from backend.app.infrastructure.formation_database import FormationDatabase
    from backend.app.infrastructure.formation_schema_release import load_release
    from backend.app.infrastructure.local_credentials import read_local_credential
    from backend.app.infrastructure.model_profile import OPENAI_PROFILE, ModelProfile
    from backend.app.infrastructure.openai_protocol import BASE_URL
    from backend.app.infrastructure.process_lock import ProcessLock

    profile, catalog = profile_and_catalog()
    database = FormationDatabase(
        args.database.resolve(), formation_release=load_release(), read_only=True
    )
    with database.transaction():
        pass
    proof = admission_for(database, ProcessLock.for_database(database.path), catalog).current(
        profile.snapshot
    )
    activated = args.activate_release
    os.environ.pop('WALLE_ACTIVATED_OPENAI_RELEASE_SHA256', None)
    if activated is not None:
        if activated != catalog.collaboration.release_sha256:
            raise ValueError('Activation digest differs from selected OpenAI release')
        os.environ['WALLE_ACTIVATED_OPENAI_RELEASE_SHA256'] = activated
    catalog.collaboration.require_live(profile.snapshot, admission=proof)
    print(
        'OPENAI_START release=' + catalog.collaboration.release_sha256
        + ' admission=' + proof.value['state']
        + ' activation=' + ('explicit' if activated else 'verified'),
        flush=True,
    )
    key = read_local_credential(args.credential_file, name='OPENAI_API_KEY')
    ModelProfile(key, OPENAI_PROFILE)
    os.environ.update(
        OPENAI_API_KEY=key,
        WALLE_MODEL_PROFILE=OPENAI_PROFILE,
        WALLE_MODEL_ID=profile.model_name,
        WALLE_MODEL_VERSION=profile.model_version,
        WALLE_MODEL_BASE_URL=BASE_URL,
        WALLE_DATABASE_PATH=str(args.database.resolve()),
    )
    os.environ.pop('WALLE_MODEL_API_KEY', None)
    from backend.app.__main__ import main as native

    native(port=args.port, schema_version=210)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--observe', action='store_true')
    action.add_argument('--start', action='store_true')
    parser.add_argument('--activate-release', metavar='SHA256', help='Start the selected offline-ready OpenAI release by its exact digest')
    parser.add_argument('--database', type=Path)
    parser.add_argument('--credential-file', type=Path, default=ROOT / '.env.openai.local')
    parser.add_argument('--slot', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--port', type=int, default=8001)
    parser.add_argument('--count-limit', type=int, choices=(1, 2, 3), default=3)
    parser.add_argument('--proxy', help='Explicit credential-free local HTTP proxy for OpenAI only')
    args = parser.parse_args(argv)
    if args.activate_release is not None and not args.start:
        parser.error('--activate-release only applies to service startup')
    if not 1024 <= args.port <= 65535:
        parser.error('A valid local HTTP port is required')
    from backend.app.infrastructure.openai_transport import configured_proxy, validate_proxy

    if args.proxy is not None:
        os.environ['OPENAI_HTTP_PROXY'] = validate_proxy(args.proxy)
    configured_proxy()
    if args.observe:
        if args.slot is None or args.report is None or args.database is not None:
            parser.error(
                'Observation requires a fresh --slot and --report, never a user --database'
            )
        return observe(args, count_limit=args.count_limit)
    if args.start:
        if args.database is None or args.slot is not None or args.report is not None:
            parser.error('Startup requires an existing --database')
        return start(args)
    if args.slot is not None or args.report is not None:
        parser.error('Output slots require explicit --observe')
    return check(args)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except Exception as error:
        print('OpenAI operation stopped: ' + type(error).__name__, file=sys.stderr)
        raise SystemExit(1) from None
