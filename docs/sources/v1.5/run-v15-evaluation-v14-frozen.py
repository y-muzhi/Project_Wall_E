"""Offline preview by default; explicitly bounded, isolated EV execution only.

Real execution requires a new current human authorization. Every case is sent
at most once, with no repair, transport retry, model judge or user service.
Normal evidence databases/count audits are retained even on failure. The report
records program outcomes and leaves semantic decisions for human review.
"""
import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
COUNT_LIMIT = 78
CHAT_LIMIT = 24
TOTAL_LIMIT = CHAT_LIMIT * 139264
PREPARATION_SHA256 = 'a6b92ffe1975035afbc2ba171c24ee4127bd1e96cdda82675c5d003b10b28a6d'


def preparation():
    path = ROOT/'tools/prepare-v15-evaluation.py'
    if hashlib.sha256(path.read_bytes()).hexdigest() != PREPARATION_SHA256:
        raise ValueError('Fixed inputs changed; review and record a new evaluation plan')
    spec = importlib.util.spec_from_file_location('walle_v15_fixed_ev_inputs', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Allowance:
    """Consume worst-case allowances before IO; an exception never refunds."""
    def __init__(self, profile):
        self.profile = profile.snapshot
        self.counts = self.chats = 0

    def for_case(self, *, chat_allowed=True):
        owner = self
        class Case:
            count_calls = chat_calls = 0
            chat_suppressed = False

            def counter(self, delegate):
                case = self
                class Counter:
                    async def count(self, profile, texts):
                        from backend.app.infrastructure.resources import ConfigInvalid
                        if profile.snapshot != owner.profile or case.count_calls >= 3 or owner.counts >= COUNT_LIMIT:
                            raise ConfigInvalid('EV counting allowance exhausted or profile changed')
                        from backend.app.infrastructure.tokenization import check_text_capacity
                        check_text_capacity(profile, texts)
                        case.count_calls += 1;owner.counts += 1
                        return await delegate.count(profile, texts)
                return Counter()

            def gateway(self, delegate):
                case = self
                class Gateway:
                    async def send(self, profile, context):
                        from backend.app.infrastructure.resources import ConfigInvalid
                        if not chat_allowed:
                            case.chat_suppressed = True
                            raise ConfigInvalid('Required-input fixture did not reach the token limit; Chat suppressed')
                        if profile.snapshot != owner.profile or case.chat_calls >= 1 or owner.chats >= CHAT_LIMIT:
                            raise ConfigInvalid('EV Chat allowance exhausted or profile changed')
                        case.chat_calls += 1;owner.chats += 1
                        return await delegate.send(profile, context)
                return Gateway()
        return Case()


def append(report, value):
    with report.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write(value);stream.flush();os.fsync(stream.fileno())


def program_digest():
    source_root=Path(__file__).resolve().parents[1]
    digest=hashlib.sha256()
    paths=[*(source_root/'backend/app').rglob('*.py'),Path(__file__).resolve(),source_root/'tools/prepare-v15-evaluation.py']
    for path in sorted(paths):
        digest.update(path.relative_to(source_root).as_posix().encode('utf-8'))
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def proposal_postcondition(database, lock, catalog, domain, case, final):
    """Check exact model output before authorized isolated adoption/fault test."""
    from backend.app.infrastructure.idempotency import Idempotency
    from backend.app.suggestions.queries import get_batch
    from backend.app.suggestions.commands import decide_suggestion, complete_batch, discard_batch
    from backend.app.documents.markdown import parse_markdown
    from backend.app.documents.tables import table_model
    from backend.app.documents.snapshot import validate_snapshot, assign_identities, Provenance
    from backend.app.documents.sources import DocumentSources
    batch_id = final.get('suggestion_batch_id')
    if batch_id is None:
        return 'NOT_EXERCISED: no saved candidate batch'
    batch = get_batch(database, batch_id, catalog=catalog)
    if batch['code'] != 'READ_OK':
        return 'FAILED: saved candidate batch unavailable'
    batch = batch['data'];executor = Idempotency(database, lock)
    items = batch['suggestions']
    with database.transaction() as connection:
        before = dict(connection.execute('SELECT * FROM requirement_documents WHERE id=?', (batch['target_document_id'],)).fetchone())
        before_revisions = connection.execute('SELECT count(*) FROM revisions').fetchone()[0]
    # The task requests exactly one row. Do not adopt a broader generated patch
    # or repair it into the expected answer just to pass an evaluation.
    if (len(items) != 1 or items[0]['patch_operation'] != 'REPLACE_TABLE_ROW'
            or items[0]['selector'] != {'key_column_index': 0, 'key_value': domain.row_name}):
        discard_batch(executor, {'batch_id': batch_id, 'idempotency_key': str(uuid4())})
        return 'FAILED: expected exactly one precise target-row candidate; discarded without adoption'
    item = items[0];edit = case == 'proposals-user-edit'
    edited = domain.new_rule+' 由用户确认后处理。'
    request = {'suggestion_id': item['id'], 'decision': 'EDITED' if edit else 'ACCEPTED', 'idempotency_key': str(uuid4())}
    if edit: request['edited_content'] = json.dumps({'cells': [domain.row_name, edited]},ensure_ascii=False)
    decision = decide_suggestion(executor, request, catalog=catalog)
    if decision['code'] != 'SUGGESTION_DECIDED':
        return 'FAILED: normal decision '+decision['code']
    injected = None
    if case == 'proposals-stale-original':
        # Explicit isolated race injection, never a user workflow or a forged
        # normal content commit. Keep the changed state as evidence afterwards.
        injected = before['markdown_content'].replace(domain.old_rule, '并发修改后的规则，必须保留。')
        with database.transaction(write=True) as connection:
            sources = DocumentSources(connection, 1, catalog, document_id=before['id'])
            prior = validate_snapshot(before['markdown_content'], json.loads(before['block_state_json']), sources)
            session = connection.execute('SELECT draft_id FROM manual_edit_sessions WHERE current_document_id=? ORDER BY draft_id DESC LIMIT 1', (before['id'],)).fetchone()[0]
            snapshot = assign_identities(injected, [block['block_id'] for block in prior.state['blocks']], prior.next_block_id,
                prior, Provenance('USER', 'MANUAL_EDIT', session), before['updated_at'], sources)
            connection.execute('UPDATE requirement_documents SET markdown_content=?,block_state_json=? WHERE id=?',
                (injected,json.dumps(snapshot.state,ensure_ascii=False),before['id']))
    completed = complete_batch(executor, {'batch_id': batch_id, 'expected_content_version': before['content_version'],
        'idempotency_key': str(uuid4())}, catalog=catalog)
    with database.transaction() as connection:
        after = connection.execute('SELECT markdown_content,content_version FROM requirement_documents WHERE id=?', (before['id'],)).fetchone()
        after_revisions = connection.execute('SELECT count(*) FROM revisions').fetchone()[0]
    if injected is not None:
        passed = completed['code'] == 'TARGET_STALE' and after['markdown_content'] == injected and before_revisions == after_revisions
        return ('PASSED' if passed else 'FAILED')+': isolated stale-original injection; result='+completed['code']
    preserved = '| 保留项 | 本行不能修改。 |\n' in after['markdown_content']
    rows = parse_markdown(after['markdown_content']).blocks
    expected = edited if edit else domain.new_rule
    actual_cells = table_model(rows[0]).rows[0].cells if len(rows)==1 and rows[0].block_type=='table' else None
    passed = (completed['code']=='BATCH_APPLIED' and preserved and actual_cells==(domain.row_name,expected)
        and after['content_version']==before['content_version']+1 and after_revisions==before_revisions+1
        and len(rows)==1 and rows[0].block_type=='table')
    return ('PASSED' if passed else 'FAILED')+': normal '+('EDITED' if edit else 'ACCEPTED')+' row completion; result='+completed['code']


def execute(args, profile, catalog, inputs):
    from backend.app.infrastructure.database import Database
    from backend.app.infrastructure.process_lock import ProcessLock
    from backend.app.infrastructure.collaboration_admission import CollaborationAdmission, _profile_digest
    from backend.app.infrastructure.tokenization import TokenizationGateway
    from backend.app.infrastructure.model_gateway import ModelGateway
    from backend.app.guide.orchestrator import execute_guide_run
    from backend.app.shared.command_execution import operation_time
    if _profile_digest(profile.snapshot) != catalog.collaboration.release['model_profile_sha256']:
        raise ValueError('Fixed profile differs from the release')
    # Each new isolated case imports and verifies the original qualifying
    # technical evidence before any provider IO. Never import into a user DB.
    source = args.source_database
    if not source.is_absolute() or not source.is_file(): raise ValueError('Original technical evidence required')
    output = args.output_dir
    if not output.is_absolute() or output.parent.resolve() != (ROOT/'data').resolve() or output.exists():
        raise ValueError('Explicit new isolated data directory required')
    report = args.report
    if not report.is_absolute() or report.parent.resolve() != (ROOT/'docs/verification/v1.5').resolve() or report.suffix!='.md' or report.exists():
        raise ValueError('Explicit new verification Markdown required')
    output.mkdir(exist_ok=False)
    with report.open('x',encoding='utf-8',newline='\n') as stream:
        stream.write('# V1.5 explicitly bounded EV execution\n\nHuman authorization required before this command. '
            'At most 78 count batches and 24 Chat calls across 26 fixed cases; worst-case Chat total '
            +str(TOTAL_LIMIT)+'. Per Chat input131072/output8192/total139264, reserve1024, zero retries. '
            'No model judge. Normal databases/count audits retained, including failure.\n\n'
            'Release: '+catalog.collaboration.release_sha256+'; input source: '+PREPARATION_SHA256
            +'; runner source: '+hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            +'; application source: '+program_digest()+'; manifest: '+catalog.collaboration.manifest_sha256
            +'; profile: '+_profile_digest(profile.snapshot)+'; model: '+profile.model_name+'\n')
    args._owned_report = True
    allowance=Allowance(profile)
    for domain in inputs.DOMAINS:
        for case in inputs.CASES:
            name=domain.key+'/'+case;directory=output/domain.key/case;directory.mkdir(parents=True,exist_ok=False)
            database=Database(directory/'evaluation.sqlite');database.initialize()
            append(report,'\n## '+name+'\n\nSlot claimed; unknown/interrupted outcome must not be repeated.\n')
            with ProcessLock.for_database(database.path) as lock:
                identity,context,_=inputs.prepare_case(database,lock,catalog,domain,case)
                store=CollaborationAdmission(database,lock,catalog)
                store.approve_saved_call(source,args.llm_use_id,operation_time(None))
                budget=allowance.for_case(chat_allowed=case!='analysis-required-over-budget')
                result=asyncio.run(execute_guide_run(database,{'guide_run_id':identity},process_lock=lock,catalog=catalog,
                    profile=profile,gateway=budget.gateway(ModelGateway()),counting_counter=budget.counter(TokenizationGateway())))
                with database.transaction() as connection:
                    run=connection.execute('SELECT status,error_code,final_result_json FROM guide_runs WHERE id=?',(identity,)).fetchone()
                    row=connection.execute('''SELECT id,call_status,parse_status,validation_status,input_tokens,output_tokens,finish_reason,duration_ms,
                        CASE WHEN json_valid(raw_response_json) THEN json_extract(raw_response_json,'$.usage.total_tokens') END AS actual_total_tokens,
                        CASE WHEN json_valid(raw_response_json) THEN json_extract(raw_response_json,'$.usage.prompt_tokens_details.cached_tokens') END AS actual_cached_tokens,
                        json_extract(request_snapshot_json,'$.counting.count_attempts[#-1].measurement.counts') AS actual_text_counts
                        FROM llm_uses WHERE guide_run_id=?''',(identity,)).fetchone()
                    final=json.loads(run['final_result_json']) if run['final_result_json'] else {}
                append(report,'\nActual run='+str(identity)+'; result='+result['code']+'; count batches='+str(budget.count_calls)
                    +'; Chat='+str(budget.chat_calls)+'; status='+run['status']+'; error='+str(run['error_code'])
                    +'; user SHA256='+hashlib.sha256(context.input_json.encode('utf-8')).hexdigest()+'.\n'
                    +'\nLLMUse summary: '+('none' if row is None else ', '.join(key+'='+str(row[key]) for key in row.keys()))
                    +'; primary='+str(final.get('application_result'))+'; progress='+str(final.get('progress_result'))+'.\n')
                # Include failed/pre-Chat count candidates too; only small
                # exact measurements, never duplicate the normal raw audit.
                count_anomaly = False
                journal = database.path.with_name(database.path.name+'.count-audit')
                for path in sorted(journal.glob('*.finished.json')):
                    receipt=json.loads(path.read_text(encoding='utf-8'))
                    measurement=receipt.get('measurement') or {}
                    append(report,'\nCount audit '+receipt['id']+': phase='+receipt['phase']+'; exact eight counts='
                        +str(measurement.get('counts'))+'; failure_reason='+str(receipt.get('failure_reason'))
                        +'; http_status='+str(receipt.get('http_status'))+'.\n')
                    count_anomaly = count_anomaly or receipt['phase'] != 'SUCCEEDED'
                count_anomaly = count_anomaly or any(not path.with_name(path.name.replace('.prepared.json', '.finished.json')).is_file()
                    for path in journal.glob('*.prepared.json'))
                if count_anomaly:
                    append(report,'\nBatch stopped: failed/unknown exact counting evidence; no further provider IO. '
                        'Aggregate counts='+str(allowance.counts)+'; Chat='+str(allowance.chats)+'.\n')
                    return 1
                if case.startswith('proposals-'):
                    append(report,'\nProgram postcondition: '+proposal_postcondition(database,lock,catalog,domain,case,final)+'.\n')
                if budget.chat_suppressed:
                    append(report,'\nNOT_EXERCISED: necessary input was not rejected by token limit; Chat deliberately suppressed.\n')
                append(report,'\nSemantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.\n')
                if run['status']=='RUNNING' or row is not None and row['call_status']=='RUNNING':
                    append(report,'\nBatch stopped: unknown in-flight result retained; no further provider IO or automatic resend. '
                        'Aggregate counts='+str(allowance.counts)+'; Chat='+str(allowance.chats)+'.\n')
                    return 1
                if store.current(profile.snapshot).value['state']=='SUSPENDED':
                    append(report,'\nBatch stopped: actual usage suspended this release; no further provider IO.\n')
                    return 1
            print(name+' recorded; semantic_review=pending',flush=True)
    append(report,'\nActual aggregate counts='+str(allowance.counts)+'; Chat='+str(allowance.chats)+'. No retries.\n')
    return 0


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--report',type=Path)
    parser.add_argument('--source-database',type=Path)
    parser.add_argument('--llm-use-id',type=int)
    parser.add_argument('--credential-file',type=Path)
    parser.add_argument('--allow-count-batches',type=int)
    parser.add_argument('--allow-chat-calls',type=int)
    parser.add_argument('--max-total-tokens',type=int)
    args=parser.parse_args(argv)
    supplied=[value for key,value in vars(args).items() if key!='execute']
    if not args.execute:
        if any(value is not None for value in supplied): parser.error('Execution flags require --execute')
        return preparation().main([])
    if (any(value is None for value in supplied) or args.allow_count_batches!=COUNT_LIMIT
            or args.allow_chat_calls!=CHAT_LIMIT or args.max_total_tokens!=TOTAL_LIMIT or args.llm_use_id<1):
        parser.error('Execution requires all explicit paths, evidence identity and exactly 78/24/3342336 allowances')
    try:
        inputs=preparation()
        from backend.app.infrastructure.model_profile import ModelProfile
        from backend.app.infrastructure.local_credentials import read_local_credential
        from backend.app.infrastructure.resources import ResourceCatalog
        if not args.credential_file.is_absolute():raise ValueError('Absolute credential file required')
        profile=ModelProfile.from_environment({**os.environ,'WALLE_MODEL_API_KEY':read_local_credential(args.credential_file)})
        return execute(args,profile,ResourceCatalog(),inputs)
    except Exception as error:
        # No provider payload or credential in a terminal traceback. Claimed
        # slots and normal audits remain for read-only recovery, never resend.
        if getattr(args,'_owned_report',False):append(args.report,'\nExecution stopped: '+type(error).__name__+'; outcome must be inspected before any future action. No automatic retry.\n')
        print('evaluation_stopped='+type(error).__name__,file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
