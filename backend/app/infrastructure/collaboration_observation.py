"""Private capability for one explicitly budgeted isolated observation.

No Worker option or HTTP input constructs this object. The observation tool
claims a new output directory before creating the normal database/audits;
re-running that directory cannot repeat an unknown external request.
"""
from pathlib import Path

from .collaboration_admission import AdmissionEvidence, _profile_digest
from .resources import ConfigInvalid


class CollaborationObservation:
    def __init__(self, database, identity, catalog, profile, *, count_batches, chat_calls, total_tokens):
        if type(count_batches) is not int or not 1 <= count_batches <= 3 or type(chat_calls) is not int or chat_calls != 1:
            raise ConfigInvalid('Observation requires an explicit bounded count/Chat allowance')
        if type(total_tokens) is not int or total_tokens != catalog.collaboration.counting['total_limit']:
            raise ConfigInvalid('Observation must explicitly retain the complete approved token budget')
        self.database = database;self.identity = identity;self.path = Path(database.path).resolve()
        self.manifest = catalog.collaboration.manifest_sha256;self.release = catalog.collaboration.release_sha256
        self.profile = profile.snapshot;self.count_limit = count_batches;self.chat_limit = chat_calls
        self.count_calls = self.chat_calls = 0

    def check(self, database, identity, catalog, profile):
        if Path(database.path).resolve() != self.path or identity != self.identity or profile.snapshot != self.profile:
            raise ConfigInvalid('Observation cannot change database, run or profile')
        with database.transaction() as connection:
            return self.check_connection(connection, identity, catalog, profile)

    def check_connection(self, connection, identity, catalog, profile):
        actual = connection.execute('PRAGMA database_list').fetchall()
        if not any(row[1] == 'main' and Path(row[2]).resolve() == self.path for row in actual) or identity != self.identity or profile.snapshot != self.profile:
            raise ConfigInvalid('Observation preparation must use its actual isolated database and run')
        resources = catalog.collaboration
        if resources.manifest_sha256 != self.manifest or resources.release_sha256 != self.release or _profile_digest(profile.snapshot) != resources.release['model_profile_sha256']:
            raise ConfigInvalid('Observation cannot change its release')
        run = connection.execute('SELECT * FROM guide_runs WHERE id=?', (identity,)).fetchone()
        if run is None or run['status'] != 'RUNNING' or run['operation'] != 'DISCUSS' or run['target_document_id'] is not None:
            raise ConfigInvalid('Only the single isolated discussion observation is permitted')
        if connection.execute('SELECT count(*) FROM requirements').fetchone()[0] != 1 or connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0] != 1 or connection.execute('SELECT count(*) FROM requirement_documents').fetchone()[0] != 0:
            raise ConfigInvalid('Observation must use its isolated new workspace')
        return AdmissionEvidence(resources.release['admission'])

    @property
    def budget(self):
        return {'count_batches': self.count_limit, 'chat_calls': self.chat_limit,
            'input_tokens': 131072, 'output_tokens': 8192, 'total_tokens': 139264,
            'framing_reserve': 1024, 'transport_retries': 0}

    def counter(self, delegate):
        permit = self
        class Counter:
            async def count(self, profile, texts):
                if profile.snapshot != permit.profile or permit.count_calls >= permit.count_limit:
                    raise ConfigInvalid('Observation count allowance is exhausted')
                permit.count_calls += 1
                return await delegate.count(profile, texts)
        return Counter()

    def gateway(self, delegate):
        permit = self
        class Gateway:
            async def send(self, profile, context):
                if profile.snapshot != permit.profile or permit.chat_calls >= permit.chat_limit:
                    raise ConfigInvalid('Observation Chat allowance is exhausted')
                permit.chat_calls += 1
                return await delegate.send(profile, context)
        return Gateway()
