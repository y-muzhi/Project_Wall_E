"""Opt-in diagnostics requiring the retained fixed local runtime archives."""

import os
import pytest
from backend.tests.infrastructure.v20_primary_lpac_probe import primary_probe
from backend.tests.infrastructure.test_v20_windows_lpac_profile import (
    controller,
    ordinary_controller,
    tmp_path,
    lpac_scope,
)

pytestmark = pytest.mark.skipif(
    os.environ.get('WALLE_TEST_RUNTIME_DIAGNOSTICS') != '1',
    reason='Explicit fixed local runtime diagnostics, not default product tests',
)


def test_primary_lpac_socket_initialization_is_denied(lpac_scope):
    observed = primary_probe(lpac_scope, 'python')
    assert observed == {'2': 10013, '23': 10013, 'overlapped': 10013}


def test_primary_lpac_node_can_initialize_without_a_network_capability(lpac_scope):
    observed = primary_probe(lpac_scope, 'node')
    assert observed['pipeOnly'] is True


def test_fixed_node_sdk_imports_under_original_lpac_without_socket_capability(lpac_scope):
    observed = primary_probe(lpac_scope, 'node-sdk')
    assert observed == {'browser': 'chromium', 'pipeOnly': True}


def test_primary_python_and_fixed_sdk_exchange_private_frames_without_network(lpac_scope):
    observed = primary_probe(lpac_scope, 'python-sdk-pipe')
    assert observed['error'] == 'ORIGINAL_SDK_OPERATION_FAILED', observed
    assert observed['last']['code'] == 'SDK_OPERATION_FAILED'
    assert observed['last']['message'] == 'SDK_CONTEXT_REQUIRED'
    assert observed['diagnostic'] == ''


def test_lpac_profile_creation_must_inherit_existing_private_directory_acl(lpac_scope):
    observed = primary_probe(lpac_scope, 'python-directory-modes')
    assert observed == {'448': 5, '511': 0}, observed


def test_official_node_child_pipe_creation_cannot_progress_under_original_primary_lpac(lpac_scope):
    observed = primary_probe(lpac_scope, 'node-spawn')
    assert observed == {'stage': 'before-spawn', 'native_timeout': True}, observed


def test_fixed_node_async_temp_creation_under_primary_lpac(lpac_scope):
    observed = primary_probe(lpac_scope, 'node-temp')
    assert observed == {'stage': 'async-temp', 'created': True}, observed


def test_primary_lpac_named_pipe_creation_requires_local_namespace(lpac_scope):
    observed = primary_probe(lpac_scope, 'python-pipe-namespace')
    assert observed == {'global': 5, 'local': 0}, observed
