"""Independently attest one actual selected program under a closed release transition."""

from contextlib import ExitStack
import fcntl
from functools import partial
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from backend.app.management.attachment_observation import now
from backend.app.management.registry import is_timestamp

from .environment_backup_package import private_root, read_policy, validate_location
from .environment_control import read_control, read_release_transition
from .environment_files import (
    MAX_REVISION,
    canonical,
    check_ext4,
    decode,
    digest,
    identity,
    persisted_write,
    protected_directory,
    read_entry,
    require,
)
from .environment_installation import ANCHOR_NAME, sha_value, uuid_value, validate_target_file
from .environment_lock import NativeEnvironmentFiles
from .environment_command import admission_inputs
from .environment_recovery_installation import checked_ref
from .environment_recovery_probe import check_application
from .environment_recovery_read import TUPLE_FIELDS, file_signature
from .environment_recovery_verify import FixedReadProbe, probe_fixed_reader
from .environment_release_check import CHECK_SOCKET, POLICY as CHECK_POLICY, check_inputs
from .environment_release_preflight import read_reference

POLICY = 'release-verification-policy.v1.json'
INVALID = 'RELEASE_VERIFICATION_INTENT_MISMATCH'
UNVERIFIED = 'RELEASE_VERIFICATION_UNVERIFIED'
CONFLICT = 'RELEASE_VERIFICATION_CONFLICT'


def verification_subject(args):
    plan = read_policy(
        args.anchor,
        args.anchor_sha256,
        POLICY,
        (
            'operation_id',
            'verification_id',
            'installation',
            'check_policy',
            'home',
            'home_identity',
            'temporary',
            'temporary_identity',
            'evidence',
            'evidence_identity',
            'requirement_id',
            'document_id',
            'markdown_sha256',
        ),
    )
    require(
        all(uuid_value(plan[key]) for key in ('operation_id', 'verification_id'))
        and plan['operation_id'] != plan['verification_id']
        and sha_value(plan['markdown_sha256'])
        and all(
            type(plan[key]) is int and 1 <= plan[key] <= MAX_REVISION
            for key in ('requirement_id', 'document_id')
        ),
        INVALID,
    )
    anchor, pin = checked_ref(plan['installation'], ANCHOR_NAME)
    policy, check_pin = checked_ref(plan['check_policy'], CHECK_POLICY)
    installation, _ = admission_inputs(
        SimpleNamespace(anchor=anchor, anchor_sha256=pin, project=args.project),
        SimpleNamespace(runtime_manifest_sha256=args.sha256),
        args.program_sha256,
        offline=True,
    )
    parameters = check_inputs(installation, plan['operation_id'], policy, check_pin)
    reserved = (
        installation.environment_root,
        args.project,
        args.root,
        args.anchor.parent,
        installation.schema,
    )
    home = validate_location(plan, 'home', 'home_identity', reserved)
    temporary = validate_location(plan, 'temporary', 'temporary_identity', (*reserved, home))
    evidence = validate_location(
        plan, 'evidence', 'evidence_identity', (*reserved, home, temporary, policy.parent)
    )
    return plan, installation, home, temporary, evidence, policy, check_pin, parameters


def checked_selected_state(installation, native, check, lock):
    installation.check_hold(offline=True)
    with installation.directory(native, 'control') as fd:
        control = read_control(fd, installation)
        transition = read_release_transition(fd, installation, check['operation_id'])
        require(
            control == transition['after']
            and transition['after_sha256'] == check['control_sha256']
            and digest(canonical(transition)) == check['transition_sha256'],
            UNVERIFIED,
        )
    with installation.directory(native, 'data') as fd:
        facts = os.stat(installation.database.name, dir_fd=fd, follow_symlinks=False)
        require(
            validate_target_file(installation, facts) == transition['database_identity']
            and all(
                not os.path.lexists(
                    installation.database.with_name(installation.database.name + suffix)
                )
                for suffix in ('-wal', '-shm', '-journal')
            ),
            UNVERIFIED,
        )
    require(
        all(
            not os.path.lexists(installation.path('runtime') / name)
            for name in ('walle.sock', CHECK_SOCKET)
        ),
        UNVERIFIED,
    )
    lock.assert_owned()
    return control, transition, file_signature(facts)


def selected_state(installation, native, check):
    with installation.lock(native) as lock:
        return checked_selected_state(installation, native, check, lock)


def verified_subject(installation, transition):
    return {
        'operation_id': transition['operation_id'],
        'target_installation_sha256': installation.anchor_sha256,
        **{key: getattr(installation, key) for key in TUPLE_FIELDS},
        'control_revision': transition['after']['control_revision'],
        'control_sha256': transition['after_sha256'],
        'transition_sha256': digest(canonical(transition)),
        'runtime_manifest_sha256': installation.description['runtime_manifest_sha256'],
        'schema_manifest_sha256': installation.description['schema_manifest_sha256'],
        'program_sha256': installation.description['program_source']['sha256'],
        'frontend_index_sha256': installation.description['deployment_slot'][
            'frontend_index_sha256'
        ],
        'logical_content_sha256': transition['logical_content_sha256'],
        'outbound_hold_required': True,
    }


def verified_release_receipt(reference, installation, transition):
    proof = read_reference(reference)
    expected = verified_subject(installation, transition)
    require(
        set(proof)
        == {
            'format_version',
            'status',
            'verification_id',
            'run_id',
            'verification_policy_sha256',
            'check_policy_sha256',
            'verified_scopes',
            'document_lookup',
            'verified_at',
            *expected,
        }
        and type(proof['format_version']) is int
        and proof['format_version'] == 1
        and proof['status'] == 'RELEASE_DEPLOYMENT_VERIFIED_CLOSED'
        and all(canonical(proof[key]) == canonical(value) for key, value in expected.items())
        and uuid_value(proof['verification_id'])
        and uuid_value(proof['run_id'])
        and all(
            sha_value(proof[key]) for key in ('verification_policy_sha256', 'check_policy_sha256')
        )
        and proof['verified_scopes'] == ['DOCUMENT_CONTENT', 'DOCUMENT_HISTORY']
        and is_timestamp(proof['verified_at']),
        UNVERIFIED,
    )
    require(
        Path(reference['path']).name == f'release-verified-{proof["verification_id"]}.v1.json',
        UNVERIFIED,
    )
    sample = proof['document_lookup']
    require(
        type(sample) is dict
        and set(sample) == {'requirement_id', 'document_id', 'markdown_sha256'}
        and all(
            type(sample[key]) is int and 1 <= sample[key] <= MAX_REVISION
            for key in ('requirement_id', 'document_id')
        )
        and sha_value(sample['markdown_sha256']),
        UNVERIFIED,
    )
    return proof


def verify_release_deployment(args, entry):
    require(os.geteuid() == 0, INVALID)
    plan, installation, home, temporary, evidence, policy, check_pin, parameters = (
        verification_subject(args)
    )
    native = NativeEnvironmentFiles(args.root)
    principal = SimpleNamespace(
        maintenance_uid=installation.application_uid, group=installation.group
    )
    with ExitStack() as resources:
        fd = resources.enter_context(protected_directory(evidence))
        require(identity(os.fstat(fd)) == plan['evidence_identity'], INVALID)
        check_ext4(fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        resources.enter_context(private_root(home, plan['home_identity'], principal))
        resources.enter_context(private_root(temporary, plan['temporary_identity'], principal))
        before = selected_state(installation, native, parameters)
        _, transition, _ = before
        sample = {key: plan[key] for key in ('requirement_id', 'document_id', 'markdown_sha256')}
        subject = {
            'format_version': 1,
            'status': 'RELEASE_DEPLOYMENT_VERIFIED_CLOSED',
            **verified_subject(installation, transition),
            'verification_id': plan['verification_id'],
            'run_id': parameters['run_id'],
            'verification_policy_sha256': args.anchor_sha256,
            'check_policy_sha256': check_pin,
            'verified_scopes': parameters['verified_scopes'],
            'document_lookup': sample,
        }
        name = f'release-verified-{plan["verification_id"]}.v1.json'
        try:
            previous = read_entry(fd, name, owner=0, reject_writers=0o222)
        except FileNotFoundError:
            previous = None
        if previous is not None:
            observed = decode(previous, CONFLICT)
            require(
                is_timestamp(observed.get('verified_at'))
                and canonical({**subject, 'verified_at': observed['verified_at']}) == previous,
                CONFLICT,
            )
            os.fsync(fd)
            return observed
        probe = FixedReadProbe(
            '_serve-release-check',
            CHECK_SOCKET,
            '--release-check-policy',
            policy,
            check_pin,
            parameters['operation_id'],
            private_socket=True,
        )
        exposed = {
            **parameters,
            **{key: subject[key] for key in TUPLE_FIELDS},
            'control_revision': subject['control_revision'],
        }
        previous_generation = transition['before']['data_generation']
        wrong_generation = (
            previous_generation
            if previous_generation != installation.data_generation
            else str(uuid4())
        )
        read = partial(
            check_application,
            policy=exposed,
            read_sha=check_pin,
            wrong_generation=wrong_generation,
            plan=sample,
        )
        require(
            probe_fixed_reader(args, entry, installation, home, temporary, probe, read) == sample
            and selected_state(installation, native, parameters) == before,
            UNVERIFIED,
        )
        result = {**subject, 'verified_at': now()}
        raw = canonical(result)
        persisted_write(fd, name, raw, mode=0o444)
        require(read_entry(fd, name, owner=0, reject_writers=0o222) == raw, UNVERIFIED)
        return result
