"""Develop-only model dispatch through the real bound HTTP application, offline."""

import asyncio
import json
import sqlite3
import sys
from contextlib import closing, contextmanager
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.documents.markdown import parse_markdown
from backend.app.infrastructure import environment_http
from backend.app.infrastructure import schema_v22_release as schema
from backend.app.infrastructure.database import Database
from backend.app.infrastructure.environment_binding import (
    EnvironmentBinding,
    verify_binding,
    write_initial_schema,
)
from backend.app.infrastructure.model_profile import OPENAI_PROFILE
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.service import create_app
from backend.tests.formation.test_openai_execution import PROFILE, adapters
from backend.tests.guide.test_v15_acceptance import body
from backend.tests.guide.test_v15_execution import output


class BoundTestDatabase(Database):
    def __init__(self, path, release, binding):
        super().__init__(path, schema_release=release)
        self.environment_lock = ProcessLock.for_database(path)
        self.binding = binding
        self.idempotency_generation = binding.data_generation

    def _check_schema(self, connection):
        verify_binding(connection, self.schema_release, self.binding)
        return 2

    @contextmanager
    def frozen_admission_transaction(self):
        self.frozen_reads += 1
        with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro&immutable=1', uri=True)) as view:
            view.execute('PRAGMA query_only=ON')
            yield view


class BoundTestScope:
    recover_on_start = True
    recover_local_commands = True

    def __init__(self, database):
        self.database = database
        self.lock = database.environment_lock
        self.installation = SimpleNamespace(
            description={'purpose': 'DEVELOPMENT'},
            environment_id=database.binding.environment_id,
            data_generation=database.binding.data_generation,
            deployment_id=str(uuid4()),
            configuration_sha256='a' * 64,
        )
        self.control = {'control_revision': 1, 'outbound_hold': False}
        self.run_id = str(uuid4())
        self.observed_at = '2026-11-27T01:00:00.000Z'
        self.active = False

    def preflight(self):
        with self.database.transaction():
            self.lock.assert_owned()

    def before_recovery(self):
        self.lock.assert_owned()

    def start(self):
        self.control['outbound_hold'] = False
        self.active = True

    def drain(self):
        self.active = False

    def close(self):
        self.lock.assert_owned()


@pytest.mark.parametrize('release_opening', [False, True])
def test_development_http_dispatches_openai_and_persists_a_document(
    tmp_path, monkeypatch, release_opening
):
    directory = (tmp_path / 'ai-release').resolve()
    directory.mkdir()
    runtime = '1' * 64
    files = schema.build_candidate(directory.name, runtime, document_ai=True)
    for name, value in files.items():
        (directory / name).write_bytes(value)
    release = schema.load_release(directory, schema.digest(files[schema.MANIFEST]), runtime)
    binding = EnvironmentBinding(str(uuid4()), str(uuid4()))
    path = Path(tmp_path) / 'development.sqlite'
    with closing(sqlite3.connect(path, isolation_level=None)) as connection:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('BEGIN IMMEDIATE')
        write_initial_schema(connection, release, binding)
        connection.commit()
    database = BoundTestDatabase(path, release, binding)
    scope = BoundTestScope(database)
    database.frozen_reads = 0
    scope.document_ai_release_opening = release_opening
    scope.recover_on_start = not release_opening
    scope.recover_local_commands = not release_opening
    scope.control['outbound_hold'] = release_opening
    catalog = ResourceCatalog().for_formation_profile(OPENAI_PROFILE)
    monkeypatch.setenv(
        'WALLE_ACTIVATED_OPENAI_RELEASE_SHA256', catalog.collaboration.release_sha256
    )
    monkeypatch.setenv(
        'WALLE_ACTIVATED_OPENAI_DOCUMENT_RELEASE_SHA256',
        catalog.for_document_operation('GENERATE').collaboration.release_sha256,
    )
    origin = 'https://walle.example.test'
    roles = {
        'editor': {'client_kind': 'WEB', 'permission': 'DEVELOP'},
        'reader': {'client_kind': 'WEB', 'permission': 'READ_ONLY'},
    }
    monkeypatch.setattr(environment_http, 'installed_identities', lambda _value: (origin, roles))
    markdown = '# Mock document\n\nSaved from the normal HTTP dispatch path.\n'
    revision = '# Mock document\n\nSaved a second time using the same environment.\n'
    operation = 'GENERATE'
    suggestion = None

    def written(context):
        if operation == 'DISCUSS':
            return output(context)
        if operation == 'PROPOSE_CHANGES':
            return output(
                context,
                response_type='CHANGE_PROPOSALS',
                suggestions=[suggestion],
                suggestion_groups=[
                    {
                        'title': 'Suggested paragraph',
                        'reason': 'Review requested',
                        'suggestion_orders': [1],
                    }
                ],
            )
        return output(
            context,
            response_type='DOCUMENT_RESULT',
            document_result={
                'name': 'Generated document' if operation == 'GENERATE' else 'Existing document',
                'document_kind': 'design',
                'markdown_content': markdown if operation == 'GENERATE' else revision,
                'change_summary': 'Generate requested document',
            },
        )

    def forbid_network():
        raise AssertionError('This bound HTTP test permits only in-process provider responses')

    monkeypatch.setattr(
        'backend.app.infrastructure.openai_counting.create_transport', forbid_network
    )
    monkeypatch.setattr(
        'backend.app.infrastructure.openai_gateway.create_transport', forbid_network
    )
    counter, gateway, seen = adapters(None, make=written)
    monkeypatch.setattr(
        'backend.app.infrastructure.openai_counting.OpenAIInputCounter', lambda: counter
    )
    monkeypatch.setattr('backend.app.guide.collaboration_execution.ModelGateway', lambda: gateway)
    headers = {
        'X-WALL-E-Auth-Principal': 'editor',
        'X-WALL-E-Client': 'web-v1',
        'Sec-Fetch-Site': 'same-origin',
        'Origin': origin,
        'X-WALL-E-Environment-ID': binding.environment_id,
        'X-WALL-E-Data-Generation': binding.data_generation,
        'X-WALL-E-Binding-Protocol': '1',
    }
    app = create_app(ordinary=scope, document_ai_profile=PROFILE)

    async def exercise():
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=ASGITransport(app=app), base_url=origin) as client,
        ):
            assert database.frozen_reads == (2 if release_opening else 0)
            await round_trip(client)
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=ASGITransport(app=app), base_url=origin) as client,
        ):
            history = await client.get(
                '/api/v1/requirements/1/guide-runs?document_id=2', headers=headers
            )
            assert history.status_code == 200, history.text
            assert len(seen) == 8
            assert database.frozen_reads == (4 if release_opening else 0)

    async def round_trip(client):
        nonlocal operation, suggestion
        result = await client.get('/api/v1/environment', headers=headers)
        assert result.status_code == 200, result.text
        capabilities = {
            item['code']: item['state'] for item in result.json()['data']['capabilities']
        }
        assert capabilities['DOCUMENT_AI'] == 'READY'
        assert capabilities['INTERNAL_EXECUTION'] == 'DISABLED'

        async def post(route, data):
            return await client.post(
                route, headers={**headers, 'Idempotency-Key': str(uuid4())}, json=data
            )

        requirement = await post(
            '/api/v1/requirements', {'title': 'Document work', 'requirement_type': 'NEW'}
        )
        assert requirement.status_code == 201, requirement.text
        original = await post(
            '/api/v1/requirements/1/documents',
            {
                'name': 'Existing document',
                'document_kind': 'DESIGN',
                'template_ref': None,
            },
        )
        assert original.status_code == 201, original.text
        payload = body(
            operation='GENERATE',
            target={
                'kind': 'NEW',
                'name': 'Generated document',
                'document_kind': 'design',
                'template_ref': None,
            },
        )
        del payload['requirement_id'], payload['idempotency_key']
        route = '/api/v1/requirements/1/guide-runs'
        rejected = await client.post(
            route, headers={**headers, 'X-WALL-E-Auth-Principal': 'reader'}, json=payload
        )
        assert rejected.status_code == 403
        assert not seen

        async def run_request(data):
            accepted = await post(route, data)
            assert accepted.status_code == 202, accepted.text
            identity = accepted.json()['data']['guide_run_id']
            limit = monotonic() + 8
            latest = None
            while monotonic() < limit:
                actual = await client.get(f'/api/v1/guide-runs/{identity}', headers=headers)
                assert actual.status_code == 200, actual.text
                latest = actual.json()['data']
                if latest['status'] != 'RUNNING':
                    break
                await asyncio.sleep(0.03)
            assert latest is not None
            if latest['status'] != 'COMPLETED':
                raise AssertionError(
                    (
                        latest['status'],
                        latest.get('current_step'),
                        list(app.state.walle_worker.events),
                        [kind for kind, _ in seen],
                    )
                )
            return latest

        created = await run_request(payload)
        assert created['document_effect']['result'] == 'CREATED'

        async def discussion_version(document):
            with database.transaction() as connection:
                return connection.execute(
                    'SELECT discussion_version FROM requirement_documents WHERE id=?', (document,)
                ).fetchone()[0]

        operation = 'REVISE'
        changed = await run_request(
            {
                **payload,
                'expected_discussion_version': await discussion_version(1),
                'operation': operation,
                'target': {'kind': 'EXISTING', 'document_id': 1, 'expected_content_version': 1},
                'scope': {'scope_type': 'DOCUMENT', 'scope_ref': None},
            }
        )
        assert changed['document_effect']['result'] == 'UPDATED'

        with database.transaction() as connection:
            generated = connection.execute(
                'SELECT markdown_content,block_state_json FROM requirement_documents WHERE id=2'
            ).fetchone()
            original_text = parse_markdown(generated['markdown_content']).blocks[1].markdown
            block = json.loads(generated['block_state_json'])['blocks'][1]['block_id']
        suggestion = {
            'title': 'Adjust existing paragraph',
            'explanation': 'Review requested',
            'impact': None,
            'patch_operation': 'REPLACE_BLOCK',
            'target_ref': {'block_id': block},
            'selector_json': None,
            'original_content': original_text,
            'proposed_markdown': 'Paragraph approved after review.\n',
            'proposed_data_json': None,
        }
        operation = 'PROPOSE_CHANGES'
        proposed = await run_request(
            {
                **payload,
                'document_id': 2,
                'expected_discussion_version': await discussion_version(2),
                'operation': 'REVISE',
                'target': {'kind': 'EXISTING', 'document_id': 2, 'expected_content_version': 1},
                'scope': {'scope_type': 'DOCUMENT', 'scope_ref': None},
            }
        )
        assert proposed['operation'] == 'PROPOSE_CHANGES'
        assert proposed['document_effect'] is None
        batch = proposed['suggestion_batch_id']
        assert batch is not None, proposed['final_result']
        decision = await client.put(
            f'/api/v1/suggestion-batches/{batch}/groups/1/decision',
            headers={**headers, 'Idempotency-Key': str(uuid4())},
            json={'expected_decision_version': 1, 'decision': 'ACCEPTED'},
        )
        assert decision.status_code == 200, decision.text
        applied = await post(
            f'/api/v1/suggestion-batches/{batch}/complete',
            {
                'expected_content_version': 1,
                'expected_decision_version': decision.json()['data']['decision_version'],
            },
        )
        assert applied.status_code == 200, applied.text

        operation = 'DISCUSS'
        discussion = await run_request(
            {
                **payload,
                'document_id': 2,
                'expected_discussion_version': await discussion_version(2),
                'operation': operation,
                'proposal_intent': None,
                'target': {
                    'discussion_step_ref': None,
                    'discussion_branch_ref': None,
                    'branch_intent': None,
                    'branch_resume_basis': None,
                },
            }
        )
        assert discussion['document_effect'] is None
        assert [kind for kind, _ in seen] == ['count', 'model'] * 4

    asyncio.run(exercise())
    assert not scope.active
    assert scope.lock.owner_epoch is None
    with database.transaction() as connection:
        row = connection.execute(
            'SELECT markdown_content FROM requirement_documents WHERE id=2'
        ).fetchone()
        assert 'Paragraph approved after review.' in row['markdown_content']
        revised = connection.execute(
            'SELECT markdown_content FROM requirement_documents WHERE id=1'
        ).fetchone()
        assert revised['markdown_content'] == revision
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 4

    if sys.platform == 'linux':
        from backend.app.infrastructure.environment_backup_coverage import (
            AUDIT_UNSUPPORTED,
            require_supported_tables,
        )
        from backend.app.infrastructure.environment_files import EnvironmentFailure
        from backend.app.infrastructure.environment_result_archive import (
            collect_receipts,
            scope_key,
        )
        from backend.app.infrastructure.idempotency import generation_namespace

        with closing(sqlite3.connect(path)) as archive:
            require_supported_tables(archive, document_ai=True)
            with pytest.raises(EnvironmentFailure, match=AUDIT_UNSUPPORTED):
                require_supported_tables(archive)
            discussion_target, discussion_id = archive.execute(
                'SELECT target_identity,idempotency_key FROM idempotency_records '
                "WHERE capability_id='formation.discuss'"
            ).fetchone()
            archive.execute('SAVEPOINT unsupported')
            archive.execute('CREATE TABLE unsupported_external_assets(id INTEGER PRIMARY KEY)')
            archive.execute('INSERT INTO unsupported_external_assets VALUES (1)')
            with pytest.raises(EnvironmentFailure, match=AUDIT_UNSUPPORTED):
                require_supported_tables(archive, document_ai=True)
            archive.execute('ROLLBACK TO unsupported')
            archive.execute('RELEASE unsupported')

        prefix = generation_namespace(binding.data_generation)
        assert discussion_target.startswith(prefix)
        results, count = collect_receipts(
            path,
            {'environment_id': binding.environment_id, 'data_generation': binding.data_generation},
            30,
            generation_scoped=True,
        )
        fingerprint = scope_key(
            'formation.discuss', discussion_target[len(prefix) :], discussion_id, 'TEST_UNVERIFIED'
        )
        assert count > 1
        assert results[fingerprint[:2]][fingerprint]['record_status'] == 'SUCCEEDED'
