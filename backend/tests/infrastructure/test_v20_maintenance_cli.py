"""Real explicit CLI dispatch on isolated paths, no normal service or model IO."""

from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.app.infrastructure import schema_v20_cli as cli
from backend.app.infrastructure.schema_v20_release import SchemaMismatch
from backend.app.infrastructure.database import Database
from backend.app.infrastructure.data_retention import inspect_v151_source
from backend.app.infrastructure.windows_private_package import create_private_package
from backend.tests.infrastructure.test_v20_upgrade_engine import release
from backend.tests.requirements.test_v15_foundation import tmp_path, setup
from backend.tests.documents.test_v15_documents import workspace
from backend.tests.infrastructure.test_v20_schema_migration import seeded_source


def invoke(arguments, release):
    output = StringIO()
    with patch.object(cli, 'load_release', return_value=release), redirect_stdout(output):
        code = cli.main(arguments)
    return code, json.loads(output.getvalue())


def test_cli_plan_rehearse_apply_check_and_recover_all_keep_the_explicit_original_path(
    workspace, tmp_path, release
):
    source = workspace[0]
    original = seeded_source(workspace)
    working = source.backup_to(tmp_path / 'original-maintenance.sqlite')
    package = tmp_path / 'new-private-package'
    common = [
        '--database',
        str(working),
        '--package',
        str(package),
        '--maintenance-window-confirmed',
    ]
    code, plan = invoke(['plan', *common, '--no-config-references'], release)
    assert code == 0 and plan['status'] == 'PLAN_READY'
    bound = [*common, '--upgrade-id', plan['upgrade_id'], '--plan-sha256', plan['plan_sha256']]
    assert invoke(['rehearse', *bound], release)[1]['status'] == 'PASSED'
    assert inspect_v151_source(Database(working)).data == original
    assert invoke(['apply', *bound], release)[1]['status'] == 'UPGRADED'
    assert invoke(['check', *bound], release)[1]['status'] == 'ALREADY_COMMITTED'
    assert invoke(['recover', *bound], release)[1]['status'] == 'ALREADY_COMMITTED'
    assert invoke(['check-v20', '--database', str(working)], release) == (
        0,
        {'status': 'CHECKED', 'schema_version': 200},
    )
    assert inspect_v151_source(source).data == original
    assert str(working) not in json.dumps(plan)


def test_explicit_init_only_new_or_real_empty_never_rebuilds_151(workspace, tmp_path, release):
    target = tmp_path / 'fresh.sqlite'
    args = [
        'init-v20',
        '--database',
        str(target),
        '--package',
        str(tmp_path / 'init-package'),
        '--maintenance-window-confirmed',
    ]
    assert invoke(args, release) == (0, {'status': 'INITIALIZED', 'schema_version': 200})
    assert invoke(['check-v20', '--database', str(target)], release)[0] == 0
    existing = workspace[0]
    original = seeded_source(workspace)
    code, value = invoke(
        [
            'init-v20',
            '--database',
            str(existing.path),
            '--package',
            str(tmp_path / 'refused-package'),
            '--maintenance-window-confirmed',
        ],
        release,
    )
    assert code == 2 and value['status'] == 'BLOCKED'
    assert inspect_v151_source(existing).data == original


def test_missing_explicit_identity_window_and_config_declaration_fail_before_any_io(
    tmp_path, release, subtests
):
    missing = str(tmp_path / 'never-created.sqlite')
    package = str(tmp_path / 'never-created-package')
    invalid = (
        ['plan', '--database', missing],
        ['plan', '--database', missing, '--package', package],
        ['plan', '--database', missing, '--package', package, '--maintenance-window-confirmed'],
        ['apply', '--database', missing, '--package', package, '--maintenance-window-confirmed'],
        ['check-v20', '--database', missing, '--package', package],
    )
    for number, arguments in enumerate(invalid):
        with subtests.test(case=number):
            with redirect_stderr(StringIO()), pytest.raises(SystemExit) as error:
                cli.main(arguments)
            assert error.value.code == 2
    assert not Path(missing).exists() and not Path(package).exists()


def test_unproven_release_and_exception_messages_do_not_leak_private_data(tmp_path):
    stdout = StringIO()
    with (
        patch.object(
            cli, 'load_release', side_effect=SchemaMismatch('private path and credential fixture')
        ),
        redirect_stdout(stdout),
    ):
        assert cli.main(['check-v20', '--database', str(tmp_path / 'missing.sqlite')]) == 2
    assert json.loads(stdout.getvalue()) == {
        'status': 'BLOCKED',
        'reason_code': 'MAINTENANCE_UNVERIFIED',
    }
    assert 'credential' not in stdout.getvalue()
