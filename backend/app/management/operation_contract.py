"""Fixed management inputs and the administrator-installed catalog."""

import re
from dataclasses import dataclass, field
from ipaddress import IPv4Address
from pathlib import Path
from urllib.parse import urlsplit

from backend.app.infrastructure.content_manifest import git_oid
from backend.app.infrastructure.environment_files import (
    MAX_REVISION,
    EnvironmentFailure,
    absolute,
    canonical,
    decode,
    digest,
    exact,
    read_protected,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value

INVALID = 'MANAGEMENT_INPUT_INVALID'
DENIED = 'MANAGEMENT_ACCESS_DENIED'
RESOURCE = 'MANAGEMENT_RESOURCE_UNVERIFIED'
SCOPE = 'MANAGEMENT_SCOPE_MISMATCH'
CONFLICT = 'MANAGEMENT_OPERATION_CONFLICT'
VERSION = 'MANAGEMENT_VERSION_CONFLICT'
MISSING = 'MANAGEMENT_RECORD_NOT_FOUND'
UNAVAILABLE = 'ACTION_NOT_AVAILABLE'
SCOPE_FIELDS = ('manager_id', 'host_id', 'registry_generation')
PRINCIPAL = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}')
PURPOSES = ('DEVELOPMENT', 'INTEGRATION')
RELEASE = 'RELEASE'
RECONFIGURE = 'RECONFIGURE'
ROLLBACK_CODE = 'ROLLBACK_CODE'
RELEASE_ACTIONS = (RELEASE, ROLLBACK_CODE, RECONFIGURE)


def version(value):
    return type(value) is int and 1 <= value <= MAX_REVISION


def text(value, *, minimum=1, maximum=2000):
    require(
        type(value) is str
        and minimum <= len(value) <= maximum
        and value == value.strip()
        and all(
            character in '\n\t' or ord(character) >= 32 and ord(character) != 127
            for character in value
        ),
        INVALID,
    )
    return value


def https_origin(value):
    require(
        type(value) is str
        and len(value) <= 267
        and re.fullmatch(r'https://[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?::[1-9][0-9]{0,4})?', value)
        is not None,
        INVALID,
    )
    parts = urlsplit(value)
    hostname = parts.hostname
    port = parts.netloc.partition(':')[2]
    require(
        hostname == parts.netloc.split(':')[0]
        and all(
            re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
            for label in hostname.split('.')
        )
        and len(hostname) <= 253
        and (not port or int(port) <= 65535),
        INVALID,
    )
    last_label = hostname.rsplit('.', 1)[-1]
    if re.fullmatch(r'(?:[0-9]+|0x[0-9a-f]*)', last_label):
        try:
            require(str(IPv4Address(hostname)) == hostname, INVALID)
        except ValueError as error:
            raise EnvironmentFailure(INVALID) from error
    return value


def commit(value):
    require(type(value) is str and len(value) in (40, 64) and value != '0' * len(value), INVALID)
    try:
        return git_oid(value, 'sha1' if len(value) == 40 else 'sha256')
    except ValueError as error:
        raise EnvironmentFailure(INVALID) from error


def identity_scope(installation):
    return {field: getattr(installation, field) for field in SCOPE_FIELDS}


def installed_record(path, expected=None, *, code=RESOURCE):
    raw = read_protected(path)
    if expected is not None:
        require(sha_value(expected) and digest(raw) == expected, code)
    return decode(raw, code)


@dataclass(frozen=True)
class Principal:
    id: str
    role: str
    visible: tuple[str, ...]


@dataclass(frozen=True)
class Catalog:
    directory: Path
    scope: dict
    principals: dict[str, Principal]
    candidates: dict[str, str]
    resources: dict[str, str]
    checks: dict[str, str]
    registry_anchor_sha256: str
    capacity_policy_sha256: str | None
    release_candidates: dict[str, str]
    backup_indexes: dict[str, tuple[Path, str]] = field(default_factory=dict)
    release_configurations: dict[str, str] = field(default_factory=dict)
    backup_policies: dict[str, str] = field(default_factory=dict)
    business_entries: dict[str, dict] = field(default_factory=dict)
    prior_result_grants: dict[tuple[str, str], dict] = field(default_factory=dict)
    restore_configurations: dict[str, str] = field(default_factory=dict)
    capacity_policy_location: str | None = None

    def access(self, identifier):
        require(type(identifier) is str and identifier in self.principals, DENIED)
        return self.principals[identifier]

    def installed_candidate_pin(self, reference):
        require(uuid_value(reference), RESOURCE)
        if reference in self.candidates:
            return self.candidates[reference]
        path = self.directory / RESTORE_ATTACHMENTS / reference / RESTORE_ATTACHMENT
        return digest(read_protected(path))

    def candidate(self, reference, expected):
        require(uuid_value(reference) and sha_value(expected), RESOURCE)
        if reference in self.candidates:
            require(self.candidates[reference] == expected, RESOURCE)
            path = self.directory / 'candidates' / (reference + '.json')
            return candidate_record(installed_record(path, expected), reference)
        path = self.directory / RESTORE_ATTACHMENTS / reference / RESTORE_ATTACHMENT
        try:
            return candidate_record(installed_record(path, expected), reference)
        except FileNotFoundError as error:
            raise EnvironmentFailure(RESOURCE) from error


RESTORE_ATTACHMENTS = 'restore-attachments'
RESTORE_ATTACHMENT = 'attachment.v1.json'


def index(values):
    require(type(values) is dict and len(values) <= 256, INVALID)
    require(all(uuid_value(key) and sha_value(value) for key, value in values.items()), INVALID)
    return values


def load_backup_indexes(values):
    require(type(values) is dict and len(values) <= 256, INVALID)
    references = {}
    for identifier, value in values.items():
        require(uuid_value(identifier), INVALID)
        path, expected = path_reference(value)
        require(path.name == identifier + '.json', INVALID)
        references[identifier] = path, expected
    return references


def load_business_entries(value):
    require(type(value) is dict and len(value) <= 256, INVALID)
    entries = {}
    origins = set()
    for environment, raw in value.items():
        entry = exact(
            raw, ('data_generation', 'deployment_id', 'configuration_sha256', 'origin'), INVALID
        )
        require(
            all(
                uuid_value(item)
                for item in (environment, entry['data_generation'], entry['deployment_id'])
            )
            and sha_value(entry['configuration_sha256']),
            INVALID,
        )
        origin = https_origin(entry['origin']).removesuffix(':443')
        require(origin not in origins, INVALID)
        origins.add(origin)
        entries[environment] = {**entry, 'origin': origin}
    return entries


def load_prior_result_grants(values, principals):
    require(type(values) is list and len(values) <= 256, INVALID)
    result = {}
    for item in values:
        exact(
            item, ('environment_id', 'source_data_generation', 'read_principals', 'index'), INVALID
        )
        key = (item['environment_id'], item['source_data_generation'])
        require(all(uuid_value(value) for value in key) and key not in result, INVALID)
        readers = item['read_principals']
        require(
            type(readers) is list
            and 0 < len(readers) <= len(principals)
            and all(type(name) is str and name in principals for name in readers)
            and len(set(readers)) == len(readers),
            INVALID,
        )
        reference = item['index']
        if reference is not None:
            path, pin = path_reference(reference)
            require(
                path.name == 'prior-command-index.v1.json' and path.parent.name == key[1], INVALID
            )
            reference = (path, pin)
        result[key] = {'read_principals': frozenset(readers), 'index': reference}
    return result


CATALOG_NAME = 'management-catalog.v1.json'


def load_catalog(path, expected, installation):
    require(isinstance(path, Path), INVALID)
    require(
        path.is_absolute() and path.name == CATALOG_NAME and sha_value(expected),
        INVALID,
    )
    return catalog_from_record(installed_record(path, expected), path.parent, installation)


def catalog_from_record(record, directory, installation):
    optional = tuple(
        key
        for key in (
            'capacity_policy_sha256',
            'capacity_policy_location',
            'release_candidates',
            'backup_indexes',
            'release_configurations',
            'backup_policies',
            'business_entries',
            'prior_result_grants',
            'restore_configurations',
        )
        if key in record
    )
    value = exact(
        record,
        (
            'format_version',
            'manager_id',
            'host_id',
            'registry_generation',
            'principals',
            'candidates',
            'resources',
            'checks',
            *optional,
        ),
        INVALID,
    )
    if 'capacity_policy_sha256' in value:
        require(sha_value(value['capacity_policy_sha256']), INVALID)
    if 'capacity_policy_location' in value:
        require(
            value['capacity_policy_location'] == 'CATALOG' and 'capacity_policy_sha256' in value,
            INVALID,
        )
    scope = identity_scope(installation)
    require(all(value[key] == actual for key, actual in scope.items()), SCOPE)
    require(type(value['format_version']) is int and value['format_version'] == 1, INVALID)
    require(type(value['principals']) is list and 0 < len(value['principals']) <= 128, INVALID)
    principals = {}
    for entry in value['principals']:
        exact(entry, ('id', 'role', 'environment_ids'), INVALID)
        name, role, visible = (entry[field] for field in ('id', 'role', 'environment_ids'))
        require(
            type(name) is str
            and PRINCIPAL.fullmatch(name) is not None
            and name not in principals
            and role in ('MANAGER', 'DEVELOPER', 'VIEWER')
            and type(visible) is list
            and len(visible) <= 256
            and all(uuid_value(item) for item in visible)
            and len(set(visible)) == len(visible),
            INVALID,
        )
        principals[name] = Principal(name, role, tuple(visible))
    return Catalog(
        directory,
        scope,
        principals,
        index(value['candidates']),
        index(value['resources']),
        index(value['checks']),
        installation.sha256,
        value.get('capacity_policy_sha256'),
        index(value.get('release_candidates', {})),
        load_backup_indexes(value.get('backup_indexes', {})),
        index(value.get('release_configurations', {})),
        index(value.get('backup_policies', {})),
        load_business_entries(value.get('business_entries', {})),
        load_prior_result_grants(value.get('prior_result_grants', []), principals),
        index(value.get('restore_configurations', {})),
        capacity_policy_location=value.get('capacity_policy_location'),
    )


def path_reference(value):
    exact(value, ('path', 'sha256'), INVALID)
    require(sha_value(value['sha256']), INVALID)
    return absolute(value['path'], INVALID), value['sha256']


def candidate_record(value, reference):
    exact(
        value,
        (
            'format_version',
            'candidate_ref',
            'installation',
            'workspace',
            'profile_ref',
            'task_id',
            'display_name',
            'owner_principal',
            'owner_label',
            'goal',
            'scope',
            'baseline_commit',
            'checks',
        ),
        INVALID,
    )
    require(
        type(value['format_version']) is int
        and value['format_version'] == 1
        and value['candidate_ref'] == reference
        and uuid_value(value['profile_ref'])
        and uuid_value(value['task_id'])
        and type(value['owner_principal']) is str
        and PRINCIPAL.fullmatch(value['owner_principal']) is not None,
        INVALID,
    )
    path_reference(value['installation'])
    path_reference(value['workspace'])
    for key in ('display_name', 'owner_label'):
        text(value[key], maximum=120)
    for key in ('goal', 'scope', 'checks'):
        text(value[key])
    commit(value['baseline_commit'])
    return value


def operation_request(value, catalog):
    exact(
        value,
        (
            'format_version',
            'manager_id',
            'host_id',
            'registry_generation',
            'principal',
            'request_key',
            'input',
        ),
        INVALID,
    )
    require(type(value['format_version']) is int and value['format_version'] == 1, INVALID)
    require(all(value[key] == actual for key, actual in catalog.scope.items()), SCOPE)
    principal = catalog.access(value['principal'])
    require(uuid_value(value['request_key']) and type(value['input']) is dict, INVALID)
    require(len(canonical(value)) <= 64 * 1024, INVALID)
    return principal, value['request_key'], value['input']


def attach_intent(raw):
    fields = ('action', 'candidate_ref', 'expected_candidate_sha256')
    if 'environment_id' in raw or 'expected_record_version' in raw:
        fields += ('environment_id', 'expected_record_version')
    exact(raw, fields, INVALID)
    require(
        raw['action'] == 'ATTACH'
        and uuid_value(raw['candidate_ref'])
        and sha_value(raw['expected_candidate_sha256'])
        and (
            'environment_id' not in raw
            or (uuid_value(raw['environment_id']) and version(raw['expected_record_version']))
        ),
        INVALID,
    )
    return raw


def uuid_refs(value, *, minimum=0):
    require(type(value) is list and minimum <= len(value) <= 64, INVALID)
    require(all(uuid_value(item) for item in value) and len(set(value)) == len(value), INVALID)


def delivery_intent(raw):
    fields = (
        'action',
        'environment_id',
        'expected_record_version',
        'expected_assignment_generation',
        'commit',
        'resource_refs',
        'check_refs',
        'manual_notes',
        'not_covered',
    )
    with_sources = 'source_environment_ids' in raw or 'source_commits' in raw
    if with_sources:
        fields += ('source_environment_ids', 'source_commits')
    exact(raw, fields, INVALID)
    require(
        raw['action'] == 'REGISTER_DELIVERY'
        and uuid_value(raw['environment_id'])
        and version(raw['expected_record_version'])
        and version(raw['expected_assignment_generation']),
        INVALID,
    )
    commit(raw['commit'])
    for key in ('resource_refs', 'check_refs'):
        uuid_refs(raw[key])
    text(raw['manual_notes'], minimum=0)
    uncovered = raw['not_covered']
    require(type(uncovered) is list and len(uncovered) <= 64, INVALID)
    for item in uncovered:
        text(item)
    if with_sources:
        sources, commits = raw['source_environment_ids'], raw['source_commits']
        uuid_refs(sources, minimum=1)
        require(
            raw['environment_id'] not in sources
            and type(commits) is list
            and len(commits) == len(sources),
            INVALID,
        )
        for oid in commits:
            commit(oid)
    return raw
