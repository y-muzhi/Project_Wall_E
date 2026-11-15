"""Self-contained local HTTP service fixture for the real original Testing Job."""

import hashlib
import shutil
from base64 import b64encode
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import pytest

from backend.app.infrastructure.check_case_pack import CaseAssertion, CaseStep, CheckCase
from backend.app.infrastructure.owned_check_http import allocate_http_endpoint
from backend.app.infrastructure.project_check_dispatch import ProjectCheckDispatch
from backend.app.infrastructure.project_check_journal import ProjectCheckJournal
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal, TestingLaunchScope
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.infrastructure.windows_project_check_command import ProjectCheckCommand
from backend.app.infrastructure.windows_task_directories import ProjectCheckInput
from backend.app.testing.http_evidence import original_http_outcome
from backend.tests.infrastructure.test_v20_windows_lpac_profile import (
    check_limits,
    make_check_candidate,
)

_PROGRAM = r"""
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const [host, port, workspace] = process.argv.slice(2);
const body = fs.readFileSync(path.join(workspace, "src", "input.bin"));
const server = http.createServer((request, response) => {
  response.setHeader("Connection", "close");
  response.setHeader("Content-Length", body.length);
  if (request.url === "/redirect") {
    response.statusCode = 302;
    response.setHeader("Location", "http://127.0.0.1:8000/forbidden");
  }
  response.end(body);
});
server.listen({host, port: Number(port), exclusive: true});
"""


def service_definition():
    return ProjectCheckCommand.decode(
        {
            'command_id': 'owned-http',
            'executable_ref': 'fixture:http-service',
            'argument_template': [
                '-e',
                'eval(Buffer.from(process.argv[1], "base64").toString("utf8"))',
                b64encode(_PROGRAM.encode('ascii')).decode('ascii'),
                '{CHECK_HOST}',
                '{CHECK_PORT}',
                '{CHECK_INPUT}',
            ],
            'working_directory': '.',
            'purpose': 'SERVICE',
            'timeout_seconds': 30,
            'network_scope_ref': 'product',
        }
    )


def build_service(directory):
    installed = shutil.which('node.exe')
    if installed is None:
        pytest.skip('Local Windows Node executable is unavailable')
    target = directory / 'owned-http.exe'
    shutil.copyfile(Path(installed), target)
    return target


def run_native_http(root, binding, lock, frames):
    candidate, _, raw = make_check_candidate(root)
    limits, git_limits = check_limits()
    scope = TestingLaunchScope(binding.controller_ref, 17, 3, '4' * 32, 9, 2)
    check = ProjectCheckInput(
        'TESTING',
        9,
        2,
        13,
        14,
        candidate.seal.binding.candidate_id,
        candidate.seal.manifest_sha256,
    )
    case = CheckCase(
        'get-product',
        'Observe the original application',
        (),
        (
            CaseStep('first', 'REQUEST', ('product', '/redirect', 'GET', (), b'')),
            CaseStep('second', 'REQUEST', ('product', '/actual', 'GET', (), b'')),
        ),
        (
            CaseAssertion('redirect', 'STATUS', ('first', 302)),
            CaseAssertion('ready', 'STATUS', ('second', 200)),
            CaseAssertion('original', 'BODY_BYTES', ('second', raw)),
        ),
        25,
    )
    endpoint = allocate_http_endpoint('product')
    original = SimpleNamespace(fixed={'endpoint_ref': endpoint.endpoint_ref})
    with (
        PrivatePackageGuard(root / 'task-source') as source,
        LaunchJournal(create_private_package(root / 'check-evidence')) as journal,
    ):
        evidence = ProjectCheckJournal(journal, scope, binding.owner_epoch, lambda: None)

        dispatch = ProjectCheckDispatch(
            binding,
            lock,
            scope,
            check,
            definition=service_definition(),
            runner_ref='fixture:project-runner',
            active_process_limit=2,
            job_memory_limit_bytes=128 * 1024 * 1024,
            journal=evidence,
        )
        complete = dispatch.run(
            frames,
            source,
            candidate,
            limits=limits,
            git_limits=git_limits,
            max_output_bytes=4096,
            deadline=monotonic() + 30,
            cleanup_seconds=20,
            active=lambda: None,
            cancelled=lambda: False,
            http=(case, endpoint, 128),
        )
        recovered = evidence.read_completion(check, 4096)
        assert recovered == complete and complete.result.source_integrity == 'VERIFIED'
        assert not list(source.path.iterdir())
        outcome, status, reason = original_http_outcome(recovered, original, case)
        candidate_sha256 = hashlib.sha256(raw).hexdigest()
        if status == 'FAILED' and reason == 'ISOLATION_UNAVAILABLE':
            # A host that cannot initialize this LPAC listener must issue no bytes.
            assert outcome is None and complete.http['steps'] == []
            assert complete.result.stop_receipt_sha256 and complete.result.cleanup_ref
            return {'result': 'endpoint_unavailable', 'candidate_sha256': candidate_sha256}
        assert status == 'SUCCEEDED' and reason is None, (complete.http, complete.result)
        assert complete.released['check']['exit']['terminated'] is True
        assert outcome['result'] == 'PASSED'
        assert outcome['capture_status'] == 'REDACTED'
        assert (
            outcome['assertion_results'][-1]['actual_value']
            == 'sha256:' + hashlib.sha256(raw).hexdigest()
        )
        return {'result': 'verified', 'candidate_sha256': candidate_sha256}
