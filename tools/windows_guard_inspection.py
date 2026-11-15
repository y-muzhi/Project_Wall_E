"""Inspect a pinned Guard bootstrap and original packages without installing anything."""

import argparse
import hashlib
import os
import re
from time import monotonic

from backend.app.infrastructure.deployment_manifest import absolute_path, digest
from backend.app.infrastructure.program_manifest import (
    BACKEND_PROGRAM_POLICY,
    GUARD_PROGRAM_POLICY,
    MAX_MEMBERS,
)
from backend.app.infrastructure.program_package import ProgramPackageLease
from backend.app.infrastructure.runtime_launch_journal import _bytes, _resource
from backend.app.infrastructure.windows_access_check import (
    ControllerAccessQuery,
    require_controller_read_only,
)
from backend.app.infrastructure.windows_config_source import LockedFileSource
from backend.app.infrastructure.windows_controller_token import ControllerPrimaryToken
from backend.app.infrastructure.windows_file_streams import require_default_data_stream
from backend.app.infrastructure.windows_local_paths import LocalPathGuard, local_absolute_path
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.app.shared.strict_objects import exact
from backend.app.shared.validation import strict_json_object
from tools.windows_guard_bootstrap import _backend_sid, _new_directory
from tools.windows_guard_plan import (
    DEPLOYMENT_NAME,
    PLAN_NAME,
    PLAN_POLICY,
    PLAN_SCOPE,
    REQUIRED_STEPS,
    GuardBootstrapPlanError,
    require_exact_bootstrap_plan,
)
from tools.windows_program_package import validate_program_destination

MAX_PLAN_BYTES = 128 * 1024
_INPUTS = {PLAN_NAME: MAX_PLAN_BYTES, DEPLOYMENT_NAME: 2 * 1024**2, 'README.md': 64 * 1024}


def read_plan_header(raw):
    value = exact(
        strict_json_object(raw),
        (
            'schema_version',
            'policy_version',
            'installation_ref',
            'backend_sid',
            'installation_root',
            'sources',
            'deployment_sha256',
            'service',
            'scope',
            'required_steps',
        ),
    )
    if (
        type(value['schema_version']) is not int
        or value['schema_version'] != 1
        or value['policy_version'] != PLAN_POLICY
        or value['scope'] != PLAN_SCOPE
        or value['required_steps'] != list(REQUIRED_STEPS)
        or _bytes(value) != raw
    ):
        raise GuardBootstrapPlanError('BOOTSTRAP_CANONICAL_FIXED_PLAN_REQUIRED')
    sources = exact(value['sources'], ('guard', 'backend'))
    for row in sources.values():
        row = exact(row, ('root', 'program_ref', 'manifest_sha256', 'member_count'))
        absolute_path(row['root'])
        digest(row['manifest_sha256'])
        _resource(row['program_ref'])
        if type(row['member_count']) is not int or not 1 <= row['member_count'] <= MAX_MEMBERS:
            raise GuardBootstrapPlanError('BOOTSTRAP_PROGRAM_MEMBER_COUNT_REQUIRED')
    digest(value['deployment_sha256'])
    absolute_path(value['installation_root'])
    return value


class GuardBootstrapSources:
    """Own all original inputs; source integrity is not trusted installation admission."""

    def __init__(
        self,
        root,
        expected_sha256,
        *,
        timeout_ms=120000,
        cancelled=lambda: False,
        reader=None,
        allow_existing_target=False,
    ):
        self.root = local_absolute_path(root)
        self._plan = None
        self.guard = None
        self.backend = None
        self._owners = []
        self._orphans = []
        self._inputs = {}
        self._reader = None
        self._target_guard = None
        self._allow_existing_target = allow_existing_target
        self._closed = False
        self._close_failed = False
        if (
            type(timeout_ms) is not int
            or not 1 <= timeout_ms <= 300000
            or not callable(cancelled)
            or type(allow_existing_target) is not bool
            or reader is not None
            and type(reader) is not ObservedProcess
        ):
            raise GuardBootstrapPlanError('BOOTSTRAP_INSPECTION_BOUNDARY_REQUIRED')
        self._deadline = monotonic() + timeout_ms / 1000
        self._cancelled = cancelled
        self.expected_sha256 = digest(expected_sha256)
        try:
            self._checkpoint()
            if reader is None:
                reader_sid = _backend_sid()
            else:
                self._reader = self._own(reader.duplicate)
                original = self._reader.observe()
                token = self._own(ControllerPrimaryToken, self._reader, expected=original.identity)
                reader_sid = token.identity.user_sid
            self._root = self._own(LocalPathGuard, self.root, directory=True)
            self._inventory()
            for name, limit in _INPUTS.items():
                self._inputs[name] = self._own(
                    LockedFileSource,
                    self.root / name,
                    max_file_bytes=limit,
                    checkpoint=self._checkpoint,
                )
            raw = self._inputs[PLAN_NAME].snapshot.raw
            if hashlib.sha256(raw).hexdigest() != self.expected_sha256:
                raise GuardBootstrapPlanError('BOOTSTRAP_ORIGINAL_PLAN_DIGEST_DIFFERS')
            self._plan = read_plan_header(raw)
            if self._plan['backend_sid'] != reader_sid:
                raise GuardBootstrapPlanError('BOOTSTRAP_ORDINARY_BACKEND_SID_DIFFERS')
            self._inputs['README.md'].snapshot.raw.decode('utf-8', errors='strict')
            self._target = absolute_path(self._plan['installation_root'])
            self._check_roots()
            for kind, policy in (
                ('guard', GUARD_PROGRAM_POLICY),
                ('backend', BACKEND_PROGRAM_POLICY),
            ):
                source = self._plan['sources'][kind]
                held = self._own(
                    ProgramPackageLease,
                    absolute_path(source['root']),
                    expected_sha256=source['manifest_sha256'],
                    policy=policy,
                    timeout_ms=self._remaining_ms(),
                    cancelled=self._interrupted,
                )
                setattr(self, kind, held)
            self.verify()
        except BaseException as original:
            self._retain(original)
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    @property
    def plan(self):
        self._checkpoint()
        return strict_json_object(self._inputs[PLAN_NAME].snapshot.raw)

    def _interrupted(self):
        return self._cancelled() or monotonic() >= self._deadline

    def _checkpoint(self):
        if self._closed or self._close_failed:
            raise GuardBootstrapPlanError('BOOTSTRAP_SOURCE_OWNER_CLOSED')
        if self._orphans:
            raise GuardBootstrapPlanError('BOOTSTRAP_SOURCE_OWNER_UNVERIFIED')
        if self._interrupted():
            raise GuardBootstrapPlanError('BOOTSTRAP_INSPECTION_CANCELLED_OR_EXPIRED')

    def _remaining_ms(self):
        self._checkpoint()
        return max(1, int((self._deadline - monotonic()) * 1000))

    def _retain(self, error):
        owner = getattr(error, 'retained_owner', None)
        if (
            owner is not None
            and owner is not self
            and all(item is not owner for item in self._orphans)
        ):
            self._orphans.append(owner)
            self._owners = [item for item in self._owners if item is not owner]

    def _own(self, factory, *arguments, **options):
        try:
            owner = factory(*arguments, **options)
        except BaseException as error:
            self._retain(error)
            raise
        self._owners.append(owner)
        try:
            owner.__enter__()
        except BaseException as error:
            self._retain(error)
            raise
        return owner

    def _inventory(self):
        self._checkpoint()
        self._root.verify()
        require_default_data_stream(self._root._kernel, self._root._held[-1][0], directory=True)
        with os.scandir(self.root) as rows:
            if {row.name for row in rows} != set(_INPUTS):
                raise GuardBootstrapPlanError('BOOTSTRAP_INPUT_DIRECTORY_MEMBERS_DIFFER')

    def _check_roots(self):
        if self._allow_existing_target:
            if self._target_guard is None:
                self._target_guard = self._own(LocalPathGuard, self._target, directory=True)
            self._target_guard.verify()
        else:
            _new_directory(self._target)
        roots = [self.root, *(absolute_path(row['root']) for row in self._plan['sources'].values())]
        for root in roots:
            if self._target.is_relative_to(root) or root.is_relative_to(self._target):
                raise GuardBootstrapPlanError('BOOTSTRAP_INSTALLATION_OVERLAPS_INPUT')
        for name in ('guard', 'backend'):
            root = absolute_path(self._plan['sources'][name]['root'])
            if root.is_relative_to(self.root) or self.root.is_relative_to(root):
                raise GuardBootstrapPlanError('BOOTSTRAP_PROGRAM_OVERLAPS_PLAN_INPUT')

    def verify(self):
        self._checkpoint()
        if self._reader is not None and self._reader.observe().state != 'RUNNING':
            raise GuardBootstrapPlanError('BOOTSTRAP_ORIGINAL_READER_NOT_RUNNING')
        self._inventory()
        self._check_roots()
        for source in self._inputs.values():
            self._checkpoint()
            source.verify()
            require_default_data_stream(source._kernel, source._handle, directory=False)
        self.guard.verify(timeout_ms=self._remaining_ms(), cancelled=self._interrupted)
        self.backend.verify(timeout_ms=self._remaining_ms(), cancelled=self._interrupted)
        plan = require_exact_bootstrap_plan(
            self._inputs[PLAN_NAME].snapshot.raw,
            self._inputs[DEPLOYMENT_NAME].snapshot.raw,
            self.guard,
            self.backend,
        )
        for name, held, policy in (
            ('guard', self.guard, GUARD_PROGRAM_POLICY),
            ('backend', self.backend, BACKEND_PROGRAM_POLICY),
        ):
            validate_program_destination(
                self._target / name,
                held._sources[policy.manifest_name].snapshot.raw,
                held.spec.manifest_sha256,
                policy=policy,
            )
        self._inventory()
        return plan

    def bind_new_installation_root(self, original_guard):
        self._checkpoint()
        if (
            type(original_guard) is not LocalPathGuard
            or self._allow_existing_target
            or self._target_guard is not None
            or original_guard.path != self._target
        ):
            raise GuardBootstrapPlanError('BOOTSTRAP_ORIGINAL_NEW_INSTALLATION_GUARD_REQUIRED')
        original = original_guard.verify()
        held = self._own(LocalPathGuard, self._target, directory=True)
        if held.verify() != original:
            raise GuardBootstrapPlanError('BOOTSTRAP_ORIGINAL_NEW_INSTALLATION_ROOT_DIFFERS')
        self._target_guard = held
        self._allow_existing_target = True

    def verify_parent_access(self, reader):
        if type(reader) is not ObservedProcess:
            raise GuardBootstrapPlanError('BOOTSTRAP_ORIGINAL_READER_REQUIRED')
        self.verify()
        observed = reader.observe()
        if self._reader is not None and observed.identity != self._reader.identity:
            raise GuardBootstrapPlanError('BOOTSTRAP_ORIGINAL_READER_DIFFERS')
        if observed.state != 'RUNNING' or observed.identity.user_sid != self._plan['backend_sid']:
            raise GuardBootstrapPlanError('BOOTSTRAP_ORIGINAL_READER_DIFFERS')
        facts = []
        try:
            with (
                ControllerPrimaryToken(reader, expected=observed.identity) as token,
                ControllerAccessQuery(token) as access,
            ):
                for path in reversed(self._target.parents):
                    self._checkpoint()
                    with LocalPathGuard(path, directory=True) as held:
                        fact = require_controller_read_only(access.query(held), role='ANCESTOR')
                        if not fact.granted_access & 0x20:
                            raise GuardBootstrapPlanError('BOOTSTRAP_PARENT_TRAVERSE_REQUIRED')
                        facts.append(fact)
            if reader.observe().state != 'RUNNING':
                raise GuardBootstrapPlanError('BOOTSTRAP_ORIGINAL_READER_NOT_RUNNING')
            self.verify()
            return tuple(facts)
        except BaseException as error:
            self._retain(error)
            if self._orphans:
                error.retained_owner = self
            raise

    def close(self):
        if self._close_failed:
            error = GuardBootstrapPlanError('BOOTSTRAP_CLOSE_PREVIOUSLY_UNVERIFIED')
            error.retained_owner = self
            raise error
        if self._closed:
            return
        failures = []
        for owner in reversed(self._owners):
            try:
                owner.close()
            except BaseException as error:  # noqa: BLE001 -- Retain every failed original owner.
                failures.append(error)
        if failures or self._orphans:
            self._close_failed = True
            error = GuardBootstrapPlanError('BOOTSTRAP_CLOSE_UNVERIFIED')
            error.retained_owner = self
            raise error from (failures[0] if failures else None)
        self._owners.clear()
        self._closed = True

    def __enter__(self):
        try:
            self._checkpoint()
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise
        return self

    def __exit__(self, kind, error, traceback):
        self.close()


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--check-parent', action='store_true')
    parser.add_argument('--reader-pid', type=int)
    parser.add_argument('--reader-created-at')
    values = parser.parse_args(arguments)
    if values.check_parent:
        if (
            values.reader_pid is None
            or re.fullmatch('[0-9a-f]{16}', values.reader_created_at or '') is None
        ):
            parser.error('Parent inspection requires the original reader PID and creation time')
    elif values.reader_pid is not None or values.reader_created_at is not None:
        parser.error('Reader inputs require --check-parent')
    try:
        with GuardBootstrapSources(values.prepared, values.plan_sha256) as held:
            if values.check_parent:
                with ObservedProcess(values.reader_pid) as reader:
                    if reader.identity.creation_time_hex != values.reader_created_at:
                        raise GuardBootstrapPlanError('BOOTSTRAP_READER_CREATION_TIME_DIFFERS')
                    held.verify_parent_access(reader)
            else:
                held.verify()
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        if getattr(error, 'retained_owner', None) is not None:
            raise
        print('GUARD_BOOTSTRAP_INSPECTION_REJECTED')
        return 1
    print('GUARD_BOOTSTRAP_SOURCES_VERIFIED no_installation_service_acl_wfp_or_os_admission')
    if values.check_parent:
        print('EXISTING_PARENT_ACCESS_FOR_ORIGINAL_READER_VERIFIED target_not_created')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
