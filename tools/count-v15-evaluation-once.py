"""Offline preview, or one explicitly authorized count-only diagnostic.

Uses the fixed movie necessary-full-input EV fixture, normal isolated database
and CountingJournal. No Chat gateway, admission import, service or retry.
"""
import argparse
import asyncio
from dataclasses import replace
import hashlib
import importlib.util
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def inputs():
    spec = importlib.util.spec_from_file_location('walle_count_only_ev_loader', ROOT/'tools/run-v15-evaluation.py')
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.preparation()


def append(report, value):
    with report.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write(value);stream.flush();os.fsync(stream.fileno())


def count_once(directory, report, profile, catalog, *, counter=None, fixed_inputs=None):
    from backend.app.infrastructure.collaboration_admission import _profile_digest
    from backend.app.infrastructure.counting_journal import CountingJournal
    from backend.app.infrastructure.database import Database
    from backend.app.infrastructure.idempotency import Idempotency
    from backend.app.infrastructure.process_lock import ProcessLock
    from backend.app.infrastructure.tokenization import TokenizationGateway, ExactCountUnavailable, check_text_capacity, restore_measurement
    from backend.app.guide.commands import cancel_guide_run
    from backend.app.shared.command_execution import operation_time
    if _profile_digest(profile.snapshot) != catalog.collaboration.release['model_profile_sha256']:
        raise ValueError('Fixed profile differs from release')
    if not directory.is_absolute() or directory.parent.resolve() != (ROOT/'data').resolve() or directory.exists():
        raise ValueError('Explicit new isolated data directory required')
    if not report.is_absolute() or report.parent.resolve() != (ROOT/'docs/verification/v1.5').resolve() or report.suffix != '.md' or report.exists():
        raise ValueError('Explicit new verification Markdown required')
    fixed_inputs = inputs() if fixed_inputs is None else fixed_inputs
    directory.mkdir(exist_ok=False)
    with report.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write('# V1.5 one count-only diagnostic\n\nRequires a new explicit authorization. '
            'Maximum one Tokenization batch, zero Chat, zero retries; fixed movie/analysis-required-over-budget input. '
            'Preserve the claimed slot and original normal evidence on failure or interruption.\n\n'
            'release='+catalog.collaboration.release_sha256+'; manifest='+catalog.collaboration.manifest_sha256
            +'; profile='+_profile_digest(profile.snapshot)+'; tool SHA256='+hashlib.sha256(Path(__file__).read_bytes()).hexdigest()+'.\n')
        stream.flush();os.fsync(stream.fileno())
    database = Database(directory/'counting.sqlite');database.initialize()
    with ProcessLock.for_database(database.path) as lock:
        identity, context, _ = fixed_inputs.prepare_case(database, lock, catalog, fixed_inputs.DOMAINS[0], 'analysis-required-over-budget')
        journal = CountingJournal(database, lock)
        record = journal.prepare_collaboration(identity, context, profile, operation_time(None), catalog.collaboration)
        append(report, '\nCount slot claimed; journal='+record+'; user SHA256='
            +hashlib.sha256(context.input_json.encode('utf-8')).hexdigest()+'. No repeated send after unknown outcome.\n')
        try:
            check_text_capacity(profile, context.texts)
            # Exactly one call site, no loop and no Chat implementation.
            receipt = asyncio.run((TokenizationGateway() if counter is None else counter).count(profile, context.texts))
            receipt = replace(receipt, journal_id=record)
            # This tool cannot dispatch Chat. Keep actual counts even when a
            # summary-only result is within budget, then stop as NOT over.
            # Ordinary execution still requires raw proof to approve Chat.
            restore_measurement(receipt.evidence, context.texts,
                raw_required=receipt.response_digest is None, expected_model=profile.model_name)
            if len(receipt.counts) != 8 or receipt.counts[0] <= 0 or receipt.counts[1] <= 0:
                raise ExactCountUnavailable('INVALID_RESPONSE')
            journal.finish(record, profile, operation_time(None), status='SUCCEEDED', measurement=receipt.evidence)
            predicted = sum(receipt.counts[:2])+catalog.collaboration.counting['framing_reserve']
            over = predicted > catalog.collaboration.counting['input_limit']
            append(report, '\ncount_batches=1; Chat=0; exact eight counts='+str(list(receipt.counts))
                +'; predicted_input='+str(predicted)+'; over_budget='+str(over)+'.\n')
            return 0 if over else 1
        except ExactCountUnavailable as error:
            journal.finish(record, profile, operation_time(None),
                status='INTERRUPTED' if error.reason == 'TRANSPORT_ERROR' else 'FAILED',
                failure_reason=error.reason, http_status=error.http_status, provider_error=error.provider_error)
            append(report, '\nStopped: '+error.reason+'; HTTP status='+str(error.http_status)+'; Chat=0. No retry.\n')
            if error.reason == 'PROVIDER_INPUT_LIMIT':
                append(report, '\nLocal capacity rejection; Tokenization sent=0; Chat=0.\n')
            if error.provider_error is not None:
                detail = error.provider_error
                append(report, '\nPrivate diagnostic saved; body_state='+detail['body_state']+'; category='+detail['category']
                    +'; code='+str(detail['code'])+'; parameter='+str(detail['parameter'])
                    +'; request_id='+str(detail['request_id'])+'; fields='+str(detail.get('body_keys'))
                    +'. Provider message is private journal data, not copied here.\n')
            return 1
        except BaseException as error:
            # Unknown local/transport outcome never permits automatic replay.
            # Do not persist exception text, provider payloads or credentials.
            if not journal._file(record, 'finished').exists():
                journal.finish(record, profile, operation_time(None), status='INTERRUPTED')
            append(report, '\nStopped: '+type(error).__name__+'; unknown outcome retained; Chat=0. No retry.\n')
            raise
        finally:
            result = cancel_guide_run(Idempotency(database, lock), {'guide_run_id': identity, 'idempotency_key': str(uuid4())})
            append(report, '\nNormal isolated run release='+result['code']+'. No Chat was dispatched.\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--credential-file', type=Path)
    parser.add_argument('--allow-count-batches', type=int)
    parser.add_argument('--allow-chat-calls', type=int)
    args = parser.parse_args(argv)
    supplied = [value for key, value in vars(args).items() if key != 'execute']
    if not args.execute:
        if any(value is not None for value in supplied):parser.error('Execution arguments require --execute')
        return inputs().main(['--domain', 'movie', '--case', 'analysis-required-over-budget'])
    if any(value is None for value in supplied) or args.allow_count_batches != 1 or args.allow_chat_calls != 0:
        parser.error('Explicit new paths, credential source and exactly 1 count / 0 Chat required')
    try:
        from backend.app.infrastructure.local_credentials import read_local_credential
        from backend.app.infrastructure.model_profile import ModelProfile
        from backend.app.infrastructure.resources import ResourceCatalog
        if not args.credential_file.is_absolute():raise ValueError('Absolute credential file required')
        profile = ModelProfile.from_environment({**os.environ, 'WALLE_MODEL_API_KEY': read_local_credential(args.credential_file)})
        return count_once(args.output_dir, args.report, profile, ResourceCatalog())
    except Exception as error:
        print('count_diagnostic_stopped='+type(error).__name__, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
