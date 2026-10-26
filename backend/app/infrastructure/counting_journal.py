"""Private prepared/count outcome files, separate from Chat LLMUse attempts.

No database schema changes. PREPARED is not proof of a sent/paid request;
missing outcome after interruption remains unknown and never triggers replay.
Records are flushed before count I/O and after its observed result. The task
lease fences filesystem effects as well as SQL; raw count arrays retain 30 days.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta
import os
from pathlib import Path
import re
from uuid import uuid4

from .audit_data import audit_json, MAX_AUDIT_BYTES
from .database import StorageUnavailable
from .model_profile import ModelProfile
from .process_lock import ProcessLock
from .tokenization import ENDPOINT, measurement_summary, COUNT_FAILURE_REASONS, provider_error_value
from backend.app.documents.snapshot import _time
from backend.app.guide.context_builder import restore_transport_input
from backend.app.shared.validation import strict_integer, strict_json_object


class CountingJournal:
    def __init__(self, database, process_lock):
        self.database,self.process_lock=database,process_lock
        base=Path(database.path).resolve()
        self.root=base.with_name(base.name+'.count-audit')

    @contextmanager
    def _guard(self):
        def check():
            self.process_lock.assert_owned()
            if self.process_lock.path!=ProcessLock.for_database(self.database.path).path:raise RuntimeError('Counting audit lock must own this database')
            if self.root.is_symlink() or self.root.resolve()!=self.root:raise StorageUnavailable('Counting audit directory cannot be redirected')
        lease=getattr(self.database,'lease',None)
        if lease is None:
            check();yield
        else:
            with lease._gate:
                lease._check();check();yield

    def _file(self, identity, phase):
        if type(identity) is not str or not re.fullmatch(r'[0-9a-f]{32}',identity) or phase not in ('prepared','finished'):raise ValueError('Private count record identity')
        path=self.root/(identity+'.'+phase+'.json')
        if path.is_symlink() or path.resolve().parent!=self.root:raise StorageUnavailable('Counting audit file cannot be redirected')
        return path

    def _create(self, identity, phase, value, profile):
        if type(profile) is not ModelProfile:raise ValueError('Counting audit requires an approved immutable model profile')
        encoded=audit_json(value,credentials=(profile.api_key,)).encode('utf-8')
        try:
            with self._guard():
                self.root.mkdir(exist_ok=True)
                if phase=='finished':
                    with self._file(identity,'prepared').open('rb') as handle:raw=handle.read(MAX_AUDIT_BYTES+1)
                    if len(raw)>MAX_AUDIT_BYTES:raise StorageUnavailable('Prepared count audit exceeds capacity')
                    prepared=strict_json_object(raw)
                    _time(prepared['at'])
                    if prepared.get('request',{}).get('model')!=profile.model_name or prepared.get('id')!=identity or prepared.get('phase')!='PREPARED' or prepared.get('owner_epoch')!=self.process_lock.owner_epoch or value['at']<prepared['at']:
                        raise StorageUnavailable('Count outcome must belong to this process preparation')
                with self._file(identity,phase).open('xb') as handle:
                    handle.write(encoded);handle.flush();os.fsync(handle.fileno())
        except (OSError,ValueError,KeyError,TypeError) as error:raise StorageUnavailable('Private count audit could not be saved') from error

    def prepare(self, actual, function, profile, texts, at):
        _time(at);strict_integer(actual['run']['id'],'guide_run_id')
        wire = strict_json_object(texts[1])
        from backend.app.guide.context_projection import projected, basis_from_actual
        basis = basis_from_actual(actual, function, wire) if projected(function) else None
        value=restore_transport_input(wire,function,basis=basis)
        record={'schema_version':1,'id':uuid4().hex,'phase':'PREPARED','at':at,
                'guide_run_id':actual['run']['id'],'trigger_message_id':actual['user_input']['id'],
                'owner_epoch':self.process_lock.owner_epoch,'endpoint':ENDPOINT,
                'protocol':{'function_type':function.function_type,'prompt':function.prompt_reference,
                            'context_template':function.context_template,'manifest_sha256':function.manifest_sha256},
                'request':{'model':profile.model_name,'text':list(texts)},'read_manifest':value['read_manifest']}
        self._create(record['id'],'prepared',record,profile)
        return record['id']

    def prepare_collaboration(self, run_id, context, profile, at, resources):
        _time(at);strict_integer(run_id, 'guide_run_id')
        resources.validate('ContextBasis', context.basis)
        record = {'schema_version': 1, 'id': uuid4().hex, 'phase': 'PREPARED', 'at': at,
            'guide_run_id': run_id, 'trigger_message_id': context.canonical['current_message']['message_id'],
            'owner_epoch': self.process_lock.owner_epoch, 'endpoint': ENDPOINT,
            'protocol': {'function_type': 'collaboration_v1', 'release': resources.reference('collaboration.release'),
                'manifest_sha256': resources.manifest_sha256}, 'request': {'model': profile.model_name, 'text': list(context.texts)},
            'read_manifest': strict_json_object(context.manifest_json)}
        self._create(record['id'], 'prepared', record, profile)
        return record['id']

    def finish(self, identity, profile, at, *, status, measurement=None, failure_reason=None, http_status=None, provider_error=None):
        _time(at)
        if status not in ('SUCCEEDED','FAILED','INTERRUPTED') or (status=='SUCCEEDED')!=(measurement is not None):raise ValueError('Count outcome must be explicit')
        record={'schema_version':1,'id':identity,'phase':status,'at':at,'measurement':measurement}
        if status == 'SUCCEEDED' and type(measurement) is dict and 'response_sha256' in measurement and 'response' not in measurement:
            record['raw_omitted_reason'] = 'AUDIT_CAPACITY'
        if failure_reason is not None:
            if status == 'SUCCEEDED' or failure_reason not in COUNT_FAILURE_REASONS or (http_status is not None and
                    (failure_reason != 'HTTP_STATUS' or type(http_status) is not int or not 100 <= http_status <= 599)):
                raise ValueError('Count failure facts must be bounded')
            record.update(failure_reason=failure_reason, http_status=http_status)
        elif http_status is not None:
            raise ValueError('HTTP status requires a count failure reason')
        if provider_error is not None:
            if failure_reason != 'HTTP_STATUS' or http_status is None:
                raise ValueError('Provider details require a known failed HTTP status')
            record['provider_error'] = provider_error_value(provider_error)
        self._create(identity,'finished',record,profile)

    def prune_raw(self, at):
        """Keep request/count facts, remove only observed raw responses older 30d."""
        _time(at);cutoff=(datetime.fromisoformat(at[:-1]+'+00:00')-timedelta(days=30)).isoformat(timespec='milliseconds').replace('+00:00','Z')
        changed=0
        try:
            with self._guard():
                if not self.root.exists():return 0
                for path in self.root.iterdir():
                    match=re.fullmatch(r'([0-9a-f]{32})\.finished\.json',path.name)
                    if not match:continue
                    path=self._file(match[1],'finished')
                    with path.open('rb') as handle:raw=handle.read(MAX_AUDIT_BYTES+1)
                    if len(raw)>MAX_AUDIT_BYTES:raise StorageUnavailable('Counting audit record exceeds its capacity')
                    record=strict_json_object(raw);_time(record['at'])
                    if record.get('id')!=match[1] or record['at']>=cutoff:continue
                    if record.get('phase')=='SUCCEEDED' and type(record.get('measurement')) is dict and 'response' in record['measurement']:
                        record['measurement']=measurement_summary(record['measurement']);record['raw_pruned_at']=at
                    elif record.get('phase') in ('FAILED','INTERRUPTED') and type(record.get('provider_error')) is dict and record['provider_error'].get('message') is not None:
                        details=provider_error_value(record['provider_error']);details['message']=None
                        record['provider_error']=details;record['provider_message_pruned_at']=at
                    else:continue
                    encoded=audit_json(record).encode('utf-8')
                    temporary=self.root/(uuid4().hex+'.tmp')
                    # Both absolute paths are checked within this owned journal;
                    # one local file replacement, no recursive deletion/moving.
                    if temporary.resolve().parent!=self.root or path.resolve().parent!=self.root:raise StorageUnavailable('Counting prune path escaped')
                    with temporary.open('xb') as handle:handle.write(encoded);handle.flush();os.fsync(handle.fileno())
                    os.replace(temporary,path);changed+=1
        except (OSError,ValueError,KeyError,TypeError) as error:raise StorageUnavailable('Counting raw audit pruning failed') from error
        return changed
