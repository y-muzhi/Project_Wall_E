"""Only the original SDK's fixed sandboxed Chromium launch can receive DevTools pipes."""

import pytest
from backend.app.infrastructure.check_case_evidence import CheckEvidenceUnknown
from backend.app.infrastructure.check_driver_browser_process import browser_arguments


@pytest.mark.parametrize(
    'fault',
    [
        'foreign-executable',
        'foreign-profile',
        'duplicate-profile',
        'no-sandbox',
        'no-sandbox-value',
        'remote-port',
        'remote-handles',
        'subprocess-path',
        'renderer-prefix',
        'nul',
        'scalar-arguments',
    ],
)
def test_original_browser_pipe_rejects_launch_scope_changes(tmp_path, fault):
    runtime = tmp_path / 'runtime'
    profile = tmp_path / 'scratch' / 'browser-private'
    command = str(runtime / 'chrome-headless-shell-win64/chrome-headless-shell.exe')
    args = ['--remote-debugging-pipe', '--user-data-dir=' + str(profile), 'about:blank']
    if fault == 'foreign-executable':
        command = str(tmp_path / 'other.exe')
    elif fault == 'foreign-profile':
        args[1] = '--user-data-dir=' + str(tmp_path / 'other-profile')
    elif fault == 'duplicate-profile':
        args.append(args[1])
    elif fault == 'no-sandbox':
        args.append('--no-sandbox')
    elif fault == 'no-sandbox-value':
        args.append('--no-sandbox=1')
    elif fault == 'remote-port':
        args.append('--remote-debugging-port=9000')
    elif fault == 'remote-handles':
        args.append('--remote-debugging-io-pipes=1,2')
    elif fault == 'subprocess-path':
        args.append('--browser-subprocess-path=other.exe')
    elif fault == 'renderer-prefix':
        args.append('--renderer-cmd-prefix=other.exe')
    elif fault == 'nul':
        args.append('invalid\0argument')
    else:
        args = '--remote-debugging-pipe'
    with pytest.raises(CheckEvidenceUnknown, match='LAUNCH_ARGUMENTS_REQUIRED'):
        browser_arguments(runtime, profile, command, args)
