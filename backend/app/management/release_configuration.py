"""Bind a prepared release to its installed source, target and recovery policy."""

from dataclasses import dataclass

from backend.app.infrastructure.environment_files import exact, require
from backend.app.infrastructure.environment_installation import (
    sha_value,
    uuid_value,
    version_record,
)
from backend.app.infrastructure.environment_release_compatibility import COMPATIBILITY
from backend.app.infrastructure.environment_release_preflight import read_reference

from .operation_contract import INVALID, RESOURCE, UNAVAILABLE, installed_record, path_reference
from .release_artifacts import MANIFEST
from .release_candidates import installed_candidate

CHANGED = 'RELEASE_PLAN_CHANGED'
INCOMPATIBLE = 'RELEASE_COMPATIBILITY_UNVERIFIED'
ATTACHMENT_FIELDS = ('workspace', 'profile_ref', 'task_id', 'owner_principal')


@dataclass(frozen=True)
class ReleaseConfiguration:
    reference: str
    sha256: str
    source_reference: dict
    target_reference: dict
    source: dict
    target: dict
    release_ref: str
    candidate_sha256: str
    manifest_reference: dict
    compatibility_reference: dict
    recovery: dict
    recovery_sha256: str
    environment_id: str

    def public_references(self):
        return {
            'environment_id': self.environment_id,
            'release_ref': self.release_ref,
            'configuration_ref': self.reference,
            'compatibility_ref': self.compatibility_reference['ref'],
            'recovery_policy_ref': self.recovery['ref'],
        }


def attachment_reference(catalog, item):
    exact(item, ('candidate_ref', 'sha256'), INVALID)
    return catalog.candidate(item['candidate_ref'], item['sha256'])


def read_configuration(catalog, reference, *, supported=True):
    require(uuid_value(reference), INVALID)
    pin = catalog.release_configurations.get(reference)
    require(sha_value(pin), RESOURCE)
    record = installed_record(
        catalog.directory / 'release-configurations' / (reference + '.json'), pin
    )
    version_record(
        record,
        (
            *catalog.scope,
            'configuration_ref',
            'environment_id',
            'release_ref',
            'candidate_sha256',
            'source_attachment',
            'target_attachment',
            'compatibility',
            'recovery_policy',
        ),
        RESOURCE,
    )
    require(
        all(record[key] == value for key, value in catalog.scope.items())
        and record['configuration_ref'] == reference
        and uuid_value(record['environment_id']),
        RESOURCE,
    )
    source = attachment_reference(catalog, record['source_attachment'])
    target = attachment_reference(catalog, record['target_attachment'])
    require(
        source['installation'] != target['installation']
        and all(source[key] == target[key] for key in ATTACHMENT_FIELDS),
        RESOURCE,
    )
    candidate = installed_candidate(catalog, record['release_ref'], record['candidate_sha256'])
    manifest_reference = candidate['manifest_ref']
    path_reference(manifest_reference)
    compatibility = exact(record['compatibility'], ('ref', 'path', 'sha256'), RESOURCE)
    require(uuid_value(compatibility['ref']), RESOURCE)
    proof = read_reference(
        {key: compatibility[key] for key in ('path', 'sha256')}, name=COMPATIBILITY
    )
    require(
        proof.get('compatibility_id') == compatibility['ref']
        and proof.get('target_release_id') == record['release_ref']
        and proof.get('mode') == 'SAME_SCHEMA',
        INCOMPATIBLE,
    )
    policy = record['recovery_policy']
    recovery = read_recovery_policy(catalog, policy, supported=supported)
    return ReleaseConfiguration(
        reference,
        pin,
        record['source_attachment'],
        record['target_attachment'],
        source,
        target,
        record['release_ref'],
        record['candidate_sha256'],
        manifest_reference,
        compatibility,
        recovery,
        policy['sha256'],
        record['environment_id'],
    )


def read_recovery_policy(catalog, policy, *, supported=True):
    exact(policy, ('ref', 'sha256'), RESOURCE)
    require(uuid_value(policy['ref']) and sha_value(policy['sha256']), RESOURCE)
    recovery = installed_record(
        catalog.directory / 'release-recovery-policies' / (policy['ref'] + '.json'),
        policy['sha256'],
    )
    version_record(
        recovery, (*catalog.scope, 'ref', 'minimum_verification', 'preserve_source'), RESOURCE
    )
    require(
        all(recovery[key] == value for key, value in catalog.scope.items())
        and recovery['ref'] == policy['ref']
        and recovery['preserve_source'] is True
        and recovery['minimum_verification'] in ('LOCAL_VERIFIED', 'OFFHOST_VERIFIED'),
        RESOURCE,
    )
    if supported:
        require(recovery['minimum_verification'] == 'LOCAL_VERIFIED', UNAVAILABLE)
    return recovery


def compatibility_reference(config):
    return {key: config.compatibility_reference[key] for key in ('path', 'sha256')}


def manifest_path(config):
    path, pin = path_reference(config.manifest_reference)
    require(path.name == MANIFEST, RESOURCE)
    return path, pin
