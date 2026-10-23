"""Effective admission backed by existing immutable call/count evidence.

The frozen release keeps its initial OFFLINE_READY bytes. An explicit local
administrative import records only a reference and verified measurements, never
raw test reports or credentials. A later bad actual usage remains a durable
suspension because the original LLMUse is its source of truth.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
from uuid import uuid4

from backend.app.documents.snapshot import _time
from backend.app.shared.validation import object_fields, strict_integer
from .collaboration_resources import sha256
from .counting_journal import CountingJournal
from .database import Database, StorageUnavailable
from .idempotency import canonical_input
from .model_profile import ModelProfile
from .resources import ConfigInvalid
from .schema_transport import compact


def _profile_digest(snapshot):
    return sha256(compact(ModelProfile.from_snapshot(snapshot).snapshot))


class AdmissionEvidence:
    """Private verified value; no HTTP deserializer constructs this object."""
    def __init__(self, value):
        self._value = deepcopy(value)

    @property
    def value(self):
        return deepcopy(self._value)


class CollaborationAdmission:
    def __init__(self, database, process_lock, catalog):
        self.database, self.process_lock, self.catalog = database, process_lock, catalog
        self.resources = catalog.collaboration
        self.journal = CountingJournal(database, process_lock)
        self.path = self.journal.root / ('collaboration-'+self.resources.release_sha256+'.admission.json')

    def _path(self):
        if self.journal.root.is_symlink() or self.path.is_symlink() or self.path.resolve().parent != self.journal.root.resolve():
            raise StorageUnavailable('Admission state cannot be redirected')
        return self.path

    def _saved(self, path, identity):
        source = Path(path)
        if not source.is_absolute() or not source.is_file():
            raise ConfigInvalid('The original evidence database must remain available')
        with Database(source).transaction() as connection:
            row = connection.execute('SELECT * FROM llm_uses WHERE id=?', (identity,)).fetchone()
            if row is None:
                raise ConfigInvalid('The original admitted call is unavailable')
            return dict(row)

    def _observation(self, row, profile_snapshot):
        from backend.app.guide.collaboration_counting import restore_counted, verify_counted
        from .practical_usage import validate_collaboration_usage
        try:
            snapshot = json.loads(row['request_snapshot_json'])
            if snapshot['profile'] != profile_snapshot or row['function_type'] != 'collaboration_v1' or row['call_status'] != 'SUCCEEDED' or row['ended_at'] is None:
                raise ConfigInvalid('Admission must refer to an actual completed provider call')
            profile = ModelProfile.from_snapshot(snapshot['profile'])
            context = restore_counted(snapshot, self.catalog, profile)
            counts = verify_counted(context, self.catalog, profile)['count_attempts'][-1]['measurement']
            raw = json.loads(row['raw_response_json'])
            validate_collaboration_usage(raw, profile=profile, context=context, catalog=self.catalog,
                input_tokens=row['input_tokens'], output_tokens=row['output_tokens'])
            values = counts['counts'];incoming = raw['usage']['prompt_tokens']
            admission = {'state': 'LIVE_VERIFIED', 'profile_sha256': _profile_digest(profile_snapshot),
                'release_sha256': self.resources.release_sha256, 'evidence_ref': 'llm-use:'+str(row['id']),
                'count_request_sha256': counts['request_sha256'], 'chat_request_sha256': sha256(compact(profile.request(context))),
                'actual_input_tokens': incoming, 'counted_system_tokens': values[0], 'counted_user_tokens': values[1],
                'framing_gap': incoming-values[0]-values[1], 'reserve': self.resources.counting['framing_reserve']}
            if admission['profile_sha256'] != self.resources.release['model_profile_sha256']:
                raise ConfigInvalid('Observation differs from the frozen release model')
            return self.resources.validate('Admission', admission)
        except (ValueError, KeyError, TypeError, IndexError) as error:
            raise ConfigInvalid('Saved observation does not prove this release admission') from error

    def _suspended(self, path, profile_snapshot):
        """Read only small saved usage fields, never recompile old contexts."""
        from .practical_usage import validate_collaboration_measurements
        reference = self.resources.reference('collaboration.release')
        with Database(path).transaction() as connection:
            rows = connection.execute("""SELECT input_tokens,output_tokens,
                json_extract(raw_response_json,'$.model') AS actual_model,
                json_extract(raw_response_json,'$.object') AS actual_object,
                json_extract(raw_response_json,'$.usage') AS actual_usage,
                json_extract(request_snapshot_json,'$.counting.count_attempts[#-1].measurement.counts') AS counted
                FROM llm_uses WHERE function_type='collaboration_v1' AND call_status='SUCCEEDED'
                AND json_extract(request_snapshot_json,'$.protocol.release.digest')=?
                AND json_extract(request_snapshot_json,'$.profile')=?""",
                (reference['digest'], canonical_input(profile_snapshot))).fetchall()
        for row in rows:
            try:
                raw = {'model': row['actual_model'], 'object': row['actual_object'],
                    'usage': None if row['actual_usage'] is None else json.loads(row['actual_usage'])}
                counts = None if row['counted'] is None else json.loads(row['counted'])
                validate_collaboration_measurements(raw, model=profile_snapshot['model_name'], release=self.resources.counting,
                    counts=counts, input_tokens=row['input_tokens'], output_tokens=row['output_tokens'])
            except (ConfigInvalid, ValueError, TypeError):
                return True
        return False

    def current(self, profile_snapshot):
        baseline = self.resources.validate('Admission', self.resources.release['admission'])
        if _profile_digest(profile_snapshot) != baseline['profile_sha256']:
            raise ConfigInvalid('Admission model profile differs from the release')
        path = self._path()
        source = Path(self.database.path)
        if path.exists():
            try:
                if path.stat().st_size > 32768:
                    raise ValueError('Admission record exceeds capacity')
                record = json.loads(path.read_text(encoding='utf-8'))
                object_fields(record, 'admission', ('schema_version', 'source_database', 'llm_use_id', 'approved_at', 'admission'),
                    ('schema_version', 'source_database', 'llm_use_id', 'approved_at', 'admission'))
                if type(record['schema_version']) is not int or record['schema_version'] != 1:
                    raise ValueError('Unsupported admission record')
                strict_integer(record['llm_use_id'], 'llm_use_id');_time(record['approved_at'])
                source = Path(record['source_database'])
                proved = self._observation(self._saved(source, record['llm_use_id']), profile_snapshot)
                if self.resources.validate('Admission', record['admission']) != proved:
                    raise ValueError('Admission does not match its original receipts')
                baseline = proved
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise ConfigInvalid('Admission evidence cannot be verified') from error
        # A suspension is derived again from durable original calls on every
        # dispatch, including after restart and when this config write failed.
        if self._suspended(source, profile_snapshot) or source.resolve() != Path(self.database.path).resolve() and self._suspended(self.database.path, profile_snapshot):
            baseline = {**baseline, 'state': 'SUSPENDED'}
        return AdmissionEvidence(self.resources.validate('Admission', baseline))

    def approve_saved_call(self, source_database, identity, at):
        """Explicit administrative operation; never performs provider I/O."""
        _time(at);strict_integer(identity, 'llm_use_id');self.process_lock.assert_owned()
        source = Path(source_database)
        if not source.is_absolute():
            raise ConfigInvalid('Evidence must name an absolute original database')
        row = self._saved(source, identity);snapshot = json.loads(row['request_snapshot_json'])
        proved = self._observation(row, snapshot['profile'])
        if at < row['ended_at']:
            raise ConfigInvalid('Approval cannot precede its occurred observation')
        if self._suspended(source, snapshot['profile']) or self._suspended(self.database.path, snapshot['profile']):
            raise ConfigInvalid('A suspended release requires a revised release and a new observation')
        record = {'schema_version': 1, 'source_database': str(source.resolve()), 'llm_use_id': identity,
            'approved_at': at, 'admission': proved}
        temporary = self.journal.root / (uuid4().hex+'.tmp')
        try:
            with self.journal._guard():
                self.journal.root.mkdir(exist_ok=True);path = self._path()
                if path.exists():
                    existing = self.current(snapshot['profile']).value
                    if existing != proved:
                        raise ConfigInvalid('An existing admission cannot be silently replaced')
                    return existing
                with temporary.open('xb') as handle:
                    handle.write(canonical_input(record).encode('utf-8'));handle.flush();os.fsync(handle.fileno())
                self.process_lock.assert_owned();os.replace(temporary, path)
        finally:
            if temporary.exists(): temporary.unlink()
        return proved
