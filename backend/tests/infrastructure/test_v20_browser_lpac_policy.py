"""Pinned per-driver OS policy, exact native capabilities and default-deny boundaries."""

from hashlib import sha256
from time import monotonic

import pytest

from backend.app.infrastructure.browser_driver_lpac_policy import (
    POLICY_FILE,
    decode_browser_lpac_policy,
    runner_lpac_capability_names,
)
from backend.app.infrastructure.check_runner_bundle import (
    CheckResourceError,
    RegisteredCheckRunner,
    hold_check_runner_bundle,
)
from backend.app.infrastructure.windows_lpac_capabilities import (
    LpacCapabilityError,
    validate_lpac_capability_names,
)
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.shared.validation import InvalidInput
from backend.tests.infrastructure.test_v20_check_runner_bundle import document, member
from backend.tests.requirements.test_v15_foundation import tmp_path


def wire(value):
    from backend.app.infrastructure.idempotency import canonical_input

    return canonical_input(value).encode('utf-8')


@pytest.mark.parametrize('names', [[], ['registryRead'], ['registryRead', 'lpacCom']])
def test_policy_accepts_only_the_fixed_read_capability(names):
    assert decode_browser_lpac_policy(
        wire(
            {
                'schema_version': 1,
                'capability_names': names,
            }
        )
    ) == tuple(names)


@pytest.mark.parametrize(
    'value',
    [
        {'schema_version': True, 'capability_names': []},
        {'schema_version': 2, 'capability_names': []},
        {'schema_version': 1, 'capability_names': 'registryRead'},
        {'schema_version': 1, 'capability_names': ['registryRead', 'registryRead']},
        {'schema_version': 1, 'capability_names': ['internetClient']},
        {'schema_version': 1, 'capability_names': ['lpacCom']},
        {'schema_version': 1, 'capability_names': ['lpacCom', 'registryRead']},
        {'schema_version': 1, 'capability_names': ['registryRead', 'lpacCom', 'internetClient']},
        {'schema_version': 1, 'capability_names': ['registryRead', 'lpacAppExperience']},
        {'schema_version': 1, 'capability_names': ['registryRead'], 'ready': True},
        {'schema_version': 1, 'capability_names': [None]},
    ],
)
def test_policy_cannot_request_arbitrary_capabilities_or_self_admit(value):
    with pytest.raises((CheckResourceError, InvalidInput)):
        decode_browser_lpac_policy(wire(value))


@pytest.mark.parametrize(
    'raw',
    [
        b'',
        b' ' * 1025,
        b'[]',
        b'{"schema_version":1,"capability_names":[],"capability_names":["registryRead"]}',
    ],
)
def test_policy_rejects_invalid_or_ambiguous_bytes(raw):
    with pytest.raises((CheckResourceError, InvalidInput)):
        decode_browser_lpac_policy(raw)


@pytest.mark.parametrize(
    'names',
    [
        [],
        ['registryRead'],
        ('internetClient',),
        ('registryRead', 'registryRead'),
        ('REGISTRYREAD',),
    ],
)
def test_native_capability_names_require_exact_internal_tuple(names):
    with pytest.raises(LpacCapabilityError):
        validate_lpac_capability_names(names)


def fixed_bundle(root, *, policy=None, registered=True):
    path = create_private_package(root)
    (path / 'bin').mkdir()
    (path / 'bin/entry').write_bytes(b'runner')
    (path / 'zero').write_bytes(b'')
    files = [member('bin/entry', b'runner'), member('zero', b'')]
    if policy is not None:
        (path / POLICY_FILE).write_bytes(policy)
        if registered:
            files.append(member(POLICY_FILE, policy))
    raw = wire(document(capabilities=['BROWSER', 'CONTENT_INTEGRITY'], file_entries=files))
    (path / 'manifest.json').write_bytes(raw)
    with PrivatePackageGuard(path) as held:
        registration = RegisteredCheckRunner(
            held.verify(), sha256(raw).hexdigest(), 'native-check-runner', '1.0.0'
        )
    return registration


@pytest.mark.parametrize('names', [None, [], ['registryRead'], ['registryRead', 'lpacCom']])
def test_only_manifest_pinned_policy_affects_driver_capabilities(tmp_path, names):
    policy = None if names is None else wire({'schema_version': 1, 'capability_names': names})
    registration = fixed_bundle(tmp_path / 'runner', policy=policy)
    with hold_check_runner_bundle(
        registration, deadline=monotonic() + 10, cancelled=lambda: False
    ) as closure:
        assert runner_lpac_capability_names(closure, lambda: None) == (
            () if names is None else tuple(names)
        )


def test_unregistered_side_file_never_grants_a_capability(tmp_path):
    registration = fixed_bundle(
        tmp_path / 'runner',
        registered=False,
        policy=wire({'schema_version': 1, 'capability_names': ['registryRead']}),
    )
    with pytest.raises(CheckResourceError, match='TREE_DIFFERS'):
        with hold_check_runner_bundle(
            registration, deadline=monotonic() + 10, cancelled=lambda: False
        ):
            raise AssertionError('Unregistered policy must not be accepted')
