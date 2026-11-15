"""Explicit fixed real browser closure through the original native Guard fixture."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest
from backend.tests.infrastructure.test_v20_guard_browser_driver import (
    program_port,
    test_native_browser_driver_runs_with_separate_lpac_and_result_pipe as run_native_driver,
)


@pytest.fixture
def tmp_path():
    # A CHECK_DRIVER adds its own nonce/runtime names; retain the original 240-unit limit.
    with TemporaryDirectory(prefix='cb-') as temporary:
        yield Path(temporary)


@pytest.mark.parametrize('scenario', ['matrix', 'cancel', 'application'])
def test_fixed_actual_chromium_in_original_check_driver_lpac(
    tmp_path, program_port, monkeypatch, scenario
):
    configured = os.environ.get('WALLE_TEST_CHECK_BROWSER_PACKAGE')
    if not configured:
        pytest.skip('Explicit prepared fixed browser package is required for this resource check')
    package = Path(configured).resolve(strict=True)
    application = os.environ.get('WALLE_TEST_BROWSER_APPLICATION')
    if scenario == 'application' and not application:
        pytest.skip('Owned isolated backend application must be explicitly provided')

    if os.environ.get('WALLE_TEST_PRIVATE_BROWSER_CONTROLLER') != '1':
        from backend.tests.infrastructure.v20_private_logon_worker import run_in_private_logon
        from tempfile import gettempdir

        source = (
            'import os,subprocess,sys\n'
            + 'env=dict(os.environ)\n'
            + 'env.update(WALLE_TEST_CHECK_BROWSER_PACKAGE='
            + repr(str(package))
            + ',WALLE_TEST_PRIVATE_BROWSER_CONTROLLER="1",WALLE_TEST_BROWSER_SCENARIO='
            + repr(scenario)
            + ',WALLE_TEST_BROWSER_APPLICATION='
            + repr(application or '')
            + ',TEMP='
            + repr(gettempdir())
            + ',TMP='
            + repr(gettempdir())
            + ',TMPDIR='
            + repr(gettempdir())
            + ')\n'
            + 'result=subprocess.run([sys.executable,"-B","tools/python-v20.py","tools/quality_python.py",'
            + repr(
                __file__
                + '::test_fixed_actual_chromium_in_original_check_driver_lpac['
                + scenario
                + ']'
            )
            + ',"-q","-s","-p","no:cacheprovider","--tb=short",'
            + '"--basetemp",PRIVATE_LOGON_TEMP+"/pytest"],env=env,timeout=600)\n'
            + 'sys.exit(result.returncode)\n'
        )
        code, output = run_in_private_logon(source, timeout=630)
        print(output.decode('utf-8', 'replace'), flush=True)
        assert code == 0, 'Actual private-logon CHECK_DRIVER browser failed'
        return
    assert os.environ.get('WALLE_TEST_BROWSER_SCENARIO') == scenario
    from time import monotonic
    from backend.app.infrastructure import check_runner_bundle, windows_check_driver_program

    started = monotonic()

    def measured_scan(label, original):
        def run(*args, **kwargs):
            before = monotonic()
            try:
                return original(*args, **kwargs)
            finally:
                print(
                    'BROWSER_STAGE',
                    label,
                    round(monotonic() - before, 3),
                    round(monotonic() - started, 3),
                    flush=True,
                )

        return run

    for module in (check_runner_bundle, windows_check_driver_program):
        name = '_scan_task_workspace_tree'
        monkeypatch.setattr(module, name, measured_scan(module.__name__, getattr(module, name)))
    original_copy = windows_check_driver_program.BrowserDriverProgram._copy_member
    copies = 0

    def copy_member(*args, **kwargs):
        nonlocal copies
        value = original_copy(*args, **kwargs)
        copies += 1
        if copies % 100 == 0:
            print('BROWSER_COPIED', copies, round(monotonic() - started, 3), flush=True)
        return value

    monkeypatch.setattr(
        windows_check_driver_program.BrowserDriverProgram, '_copy_member', copy_member
    )
    run_native_driver(tmp_path, program_port, monkeypatch, True, real_package=package)
