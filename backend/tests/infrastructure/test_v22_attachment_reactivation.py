"""Protect reactivation of an archived environment's original ownership and resources."""

import sqlite3
from contextlib import closing
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.infrastructure.environment_files import EnvironmentFailure


def identifier():
    return str(uuid4())


@pytest.fixture
def archived_subject(monkeypatch):
    pytest.importorskip('fcntl')
    from backend.app.management import operation_store as store
    from backend.app.management.attachment_observation import ATTACHMENT_RESOURCE_KINDS, PATH_SCOPE
    from backend.app.management.operation_contract import Principal
    from backend.app.management.registry_schema import SCHEMA_VERSION, STATEMENTS

    gid, manager, host, environment, task, profile, repository = (identifier() for _ in range(7))
    principal = Principal('manager', 'MANAGER', ())
    observed = '2026-11-22T14:40:00.000Z'
    work = {
        'repository_ref': repository,
        'branch': 'refs/heads/codex/fixture',
        'data_generation': identifier(),
        'deployment_id': identifier(),
        'goal': 'Original work',
        'scope': 'Scope',
        'checks': 'Check',
        'owner_label': 'Owner',
        'baseline_commit': 'a' * 40,
    }
    candidate = {
        **{key: work[key] for key in ('goal', 'scope', 'checks', 'owner_label')},
        'baseline_commit': 'b' * 40,
        'display_name': 'Fixture',
        'owner_principal': 'manager',
        'task_id': task,
        'profile_ref': profile,
    }
    intent = {
        'action': 'ATTACH',
        'environment_id': environment,
        'expected_record_version': 7,
        'candidate_ref': identifier(),
        'expected_candidate_sha256': 'c' * 64,
    }
    paths = ATTACHMENT_RESOURCE_KINDS - {'GIT_BRANCH', 'PUBLIC_ORIGIN'}
    claims = [
        {
            'kind': kind,
            'scope': PATH_SCOPE,
            'locator': 'owned/' + kind.lower(),
            'object_identity': {'device': '1', 'inode': str(index + 2)},
        }
        for index, kind in enumerate(sorted(paths))
    ]
    claims.extend(
        (
            {
                'kind': 'GIT_BRANCH',
                'scope': 'REPOSITORY:' + repository,
                'locator': work['branch'],
                'object_identity': None,
            },
            {
                'kind': 'PUBLIC_ORIGIN',
                'scope': 'HTTPS',
                'locator': 'fixture.walle-dev.test:9443',
                'object_identity': None,
            },
        )
    )
    proof = {
        **{
            key: work[key]
            for key in ('repository_ref', 'branch', 'data_generation', 'deployment_id')
        },
        'environment_id': environment,
        'host_id': host,
        'purpose': 'DEVELOPMENT',
        'configuration_sha256': 'd' * 64,
        'program_sha256': 'e' * 64,
        'worktree_evidence_sha256': 'f' * 64,
        'proof_id': identifier(),
        'observed_at': observed,
        'claims': claims,
    }
    with closing(sqlite3.connect(':memory:', isolation_level=None)) as database:
        database.row_factory = sqlite3.Row
        database.execute('PRAGMA foreign_keys=ON')
        for statement in STATEMENTS:
            database.execute(statement)
        database.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
        database.execute(
            'INSERT INTO manager_state VALUES (1,1,?,?,?,?)', (manager, host, gid, observed)
        )
        database.execute(
            'INSERT INTO managed_environments VALUES '
            "(?,?,?,?,?,?,'ARCHIVED','PREPARED',?,?,?,?,?,?,?,'OPEN',NULL)",
            (
                environment,
                'DEVELOPMENT',
                'Fixture',
                host,
                7,
                4,
                proof['configuration_sha256'],
                store.stored({'candidate_ref': identifier(), 'sha256': '0' * 64}),
                proof['program_sha256'],
                profile,
                task,
                store.stored(work),
                'manager',
            ),
        )
        original = store.insert_operation(
            database, gid, identifier(), principal, {'action': 'ATTACH'}, environment, observed
        )
        store.register_resources(database, environment, original, claims)
        monkeypatch.setattr(store, 'require_fresh', lambda _: None)
        yield SimpleNamespace(
            store=store,
            db=database,
            principal=principal,
            environment=environment,
            generation=gid,
            intent=intent,
            candidate=candidate,
            proof=proof,
            work=work,
            lock=SimpleNamespace(assert_owned=lambda: None),
        )


@pytest.mark.parametrize('change', ('none', 'branch', 'locator', 'data', 'program', 'missing'))
def test_reattach_matches_bound_resources_and_preserves_work(archived_subject, change):
    case = archived_subject
    if change == 'branch':
        case.proof['branch'] = 'refs/heads/other'
    if change == 'locator':
        worktree = next(claim for claim in case.proof['claims'] if claim['kind'] == 'WORKTREE')
        worktree['locator'] += '-replacement'
    if change == 'data':
        case.proof['data_generation'] = identifier()
    if change == 'program':
        case.proof['program_sha256'] = '0' * 64
    if change == 'missing':
        case.proof['claims'].pop()

    def reactivate():
        with case.store.mutation(case.db, case.lock):
            case.store.save_attachment(
                case.db,
                case.generation,
                case.principal,
                identifier(),
                case.intent,
                case.candidate,
                case.proof,
            )

    if change == 'none':
        reactivate()
    else:
        with pytest.raises(EnvironmentFailure):
            reactivate()

    row = case.store.environment_row(case.db, case.environment)
    assert row['record_version'] == (8 if change == 'none' else 7)
    assert row['registration_state'] == ('ACTIVE' if change == 'none' else 'ARCHIVED')
    assert row['assignment_generation'] == 4
    assert case.store.decoded(row['work_package_json']) == case.work
    assert case.db.execute('SELECT COUNT(*) FROM resource_claims').fetchone()[0] == 9
    assert case.db.execute('SELECT COUNT(*) FROM management_operations').fetchone()[0] == (
        2 if change == 'none' else 1
    )
