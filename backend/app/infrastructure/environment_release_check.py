"""Admit the selected ordinary program privately while release control stays closed."""

import os

from backend.app.management.attachment_observation import now

from .environment_backup_package import read_policy
from .environment_control import (
    read_control,
    read_release_transition,
    require_release_not_reverting,
)
from .environment_files import canonical, digest, require
from .environment_installation import sha_value, uuid_value, validate_target_file
from .environment_recovery_read import SCOPES, ClosedReadScope
from .environment_restore import reopen_archive

POLICY = 'release-check-policy.v1.json'
CHECK_SOCKET = 'walle-check.sock'
INVALID = 'RELEASE_CHECK_INTENT_MISMATCH'
UNVERIFIED = 'RELEASE_CHECK_UNVERIFIED'


def check_inputs(installation, operation, path, expected):
    plan = read_policy(
        path,
        expected,
        POLICY,
        (
            'operation_id',
            'run_id',
            'installation_sha256',
            'transition_sha256',
            'control_sha256',
        ),
    )
    require(
        'deployment_slot' in installation.description
        and 'recovery_replica' not in installation.description
        and operation == plan['operation_id']
        and uuid_value(operation)
        and uuid_value(plan['run_id'])
        and plan['installation_sha256'] == installation.anchor_sha256
        and all(sha_value(plan[key]) for key in ('transition_sha256', 'control_sha256'))
        and len(os.fsencode(installation.path('runtime') / CHECK_SOCKET)) <= 107,
        INVALID,
    )
    return {**plan, 'verified_scopes': list(SCOPES)}


class ReleaseCheckScope(ClosedReadScope):
    offline_host_check = True

    def __init__(self, installation, native, release, resources, operation, path, expected):
        installation.check_identity(maintenance=False)
        plan = check_inputs(installation, operation, path, expected)
        super().__init__(installation, native, release, resources, path, expected, plan)

    def check_control(self):
        record = read_control(self.control_fd, self.installation)
        transition = read_release_transition(
            self.control_fd, self.installation, self.plan['operation_id']
        )
        require_release_not_reverting(self.control_fd, transition, UNVERIFIED)
        require(
            record == transition['after']
            and digest(canonical(transition)) == self.plan['transition_sha256']
            and transition['after_sha256'] == self.plan['control_sha256']
            and not os.path.lexists(self.installation.path('runtime') / 'walle.sock'),
            UNVERIFIED,
        )
        self.transition = transition
        return record

    def check_database_file(self, facts):
        measured = validate_target_file(self.installation, facts)
        require(
            measured == self.transition['database_identity'] and 0 < facts.st_size <= 1024**4,
            UNVERIFIED,
        )

    def start(self):
        self.check_installation()
        self.database_signature = self.snapshot_signature(verify_header=True)
        _, contents = reopen_archive(
            self.installation.database, self.release, self.database.binding
        )
        require(
            contents.sha256 == self.transition['logical_content_sha256']
            and self.snapshot_signature() == self.database_signature,
            UNVERIFIED,
        )
        self.check_installation()
        self.observed_at = now()
        self.active = True
