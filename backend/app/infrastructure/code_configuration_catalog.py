"""Frozen nonsecret ConfigurationOption metadata; no runtime/provider probing.

The initial release registers the real fixed Git archive and existing immutable
model Profile identities. Neither has V2 execution/price admission: ready=false.
Managed task read roots carry pinned abstract semantics, with runtime admission closed.
Other resource kinds require real preparation/validation before registration.
"""

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp

from backend.app.shared.validation import strict_enum, strict_json_object

from .content_secret_policy import CAPABILITIES, CONTENT_VALUE, REFERENCE, load_secret_policy
from .git_bundle import (
    BUNDLE_PARENT,
    GIT_MANIFEST_SHA256,
    SOURCE_COMMIT,
    VERSION,
    verify_bundle_bytes,
)
from backend.app.shared.json_canonical import canonical_input
from .managed_read_scopes import (
    RESOURCE_SHA256 as MANAGED_READ_SCOPES_SHA256,
)
from .managed_read_scopes import (
    load_managed_read_scopes,
    scope_options,
)
from .model_profile import PROFILES
from .resources import ConfigInvalid

KINDS = (
    'EXECUTOR',
    'MODEL',
    'RUNTIME',
    'COMMAND',
    'RUNNER',
    'SCOPE',
    'PRICE',
    'SECRET_REF',
    'CAPABILITY',
    'CONTENT_POLICY',
    'GIT',
    'CASE_PACK',
)
ROOT = Path(__file__).resolve().parents[2] / 'resources' / 'code'
MAX_BYTES = 1024 * 1024


def _encoded(value):
    return (canonical_input(value) + '\n').encode('utf-8')


def _read(path, *, canonical=True):
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if not raw or len(raw) > MAX_BYTES:
        raise ConfigInvalid('Code catalogue resource size differs')
    value = strict_json_object(raw)
    if canonical and _encoded(value) != raw:
        raise ConfigInvalid('Code catalogue resource is not canonical')
    return raw, value


def _exact(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        raise ConfigInvalid('Code catalogue fields differ')
    return value


def _git_value():
    raw, manifest = _read(BUNDLE_PARENT / 'win-x64/manifest.json', canonical=False)
    if (
        hashlib.sha256(raw).hexdigest() != GIT_MANIFEST_SHA256
        or manifest['expected_version'] != VERSION
        or manifest['source_commit'] != SOURCE_COMMIT
        or manifest['state'] != 'ARCHIVE_BYTES_VERIFIED'
        or manifest['runtime_admitted'] is not False
    ):
        raise ConfigInvalid('Registered Git archive authority differs')
    entry = next(row for row in manifest['members'] if row['path'] == 'cmd/git.exe')
    return {
        'version': VERSION,
        'source_commit': SOURCE_COMMIT,
        'protocol_version': 'GIT20-LOCAL-1',
        'binary_ref': 'git-binary:sha256:' + entry['sha256'],
        'runtime_bundle_ref': 'git-bundle:sha256:' + GIT_MANIFEST_SHA256,
    }


def option(value):
    row = _exact(
        value,
        (
            'option_id',
            'kind',
            'label',
            'ready',
            'unresolved_capability_codes',
            'value',
        ),
    )
    if (
        type(row['option_id']) is not str
        or not row['option_id']
        or type(row['label']) is not str
        or not row['label']
        or type(row['kind']) is not str
        or row['kind'] not in KINDS
        or row['ready'] is not False
    ):
        raise ConfigInvalid('Initial catalogue cannot claim V2 runtime admission')
    if row['kind'] == 'GIT':
        if (
            row['option_id'] != 'git:mingit-' + VERSION
            or type(row['value']) is not dict
            or set(row['value'])
            != {'version', 'binary_ref', 'runtime_bundle_ref', 'source_commit', 'protocol_version'}
            or row['value']['version'] != VERSION
            or row['value']['source_commit'] != SOURCE_COMMIT
            or row['value']['protocol_version'] != 'GIT20-LOCAL-1'
            or type(row['value']['binary_ref']) is not str
            or re.fullmatch('git-binary:sha256:[0-9a-f]{64}', row['value']['binary_ref']) is None
            or row['value']['runtime_bundle_ref'] != 'git-bundle:sha256:' + GIT_MANIFEST_SHA256
            or row['unresolved_capability_codes'] != ['Q20-GIT', 'Q20-WINDOWS']
        ):
            raise ConfigInvalid('Code Git option differs from the registered archive')
    elif row['kind'] == 'MODEL':
        fields = _exact(row['value'], ('model_profile_ref',))
        profile = fields['model_profile_ref']
        if (
            type(profile) is not str
            or profile not in PROFILES
            or row['option_id'] != 'model:' + profile
            or row['unresolved_capability_codes'] != ['Q20-MODEL']
        ):
            raise ConfigInvalid('Code model option is not an existing Profile identity')
    elif row['kind'] == 'SCOPE':
        if row not in scope_options():
            raise ConfigInvalid('Read-root option differs from pinned managed scopes')
    elif row['kind'] == 'CONTENT_POLICY':
        load_secret_policy(REFERENCE)
        if (
            row['option_id'] != 'content-policy:' + REFERENCE
            or row['value'] != CONTENT_VALUE
            or row['unresolved_capability_codes'] != CAPABILITIES
        ):
            raise ConfigInvalid('Content policy option differs from pinned program resource')
    else:
        raise ConfigInvalid('Resource kind has not been prepared in this catalogue release')
    # Detached JSON: no credentials, provider endpoints or host paths are loaded.
    return json.loads(canonical_input(row))


@dataclass(frozen=True)
class CodeCatalogue:
    release_id: str
    manifest_sha256: str
    entries_json: str

    def items(self, kind):
        strict_enum(kind, 'kind', KINDS)
        return [entry for entry in json.loads(self.entries_json)['items'] if entry['kind'] == kind]


def load_verified_catalogue(root, expected_sha256):
    try:
        raw, manifest = _read(root / 'manifest.json')
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ConfigInvalid('Code catalogue manifest digest differs')
        version = manifest.get('schema_version')
        fields = ('schema_version', 'release_id', 'files', 'git_manifest_sha256', 'model_profiles')
        if type(version) is int and version == 2:
            fields += ('managed_read_scopes_sha256',)
        _exact(manifest, fields)
        if (
            type(version) is not int
            or version not in (1, 2)
            or type(manifest['release_id']) is not str
            or re.fullmatch('[a-z][a-z0-9-]{0,63}', manifest['release_id']) is None
            or manifest['git_manifest_sha256'] != GIT_MANIFEST_SHA256
            or type(manifest['files']) is not list
            or len(manifest['files']) != 1
        ):
            raise ConfigInvalid('Code catalogue authority is invalid')
        descriptor = _exact(manifest['files'][0], ('path', 'bytes', 'sha256'))
        if descriptor['path'] != 'options.json':
            raise ConfigInvalid('Code catalogue file name is not registered')
        data_raw, data = _read(root / 'options.json')
        if (
            type(descriptor['bytes']) is not int
            or descriptor['bytes'] != len(data_raw)
            or descriptor['sha256'] != hashlib.sha256(data_raw).hexdigest()
        ):
            raise ConfigInvalid('Code catalogue bytes differ')
        _exact(data, ('schema_version', 'items'))
        if (
            type(data['schema_version']) is not int
            or data['schema_version'] != 1
            or type(data['items']) is not list
        ):
            raise ConfigInvalid('Code catalogue item list is invalid')
        profiles = manifest['model_profiles']
        if type(profiles) is not list:
            raise ConfigInvalid('Code catalogue Profile source list is invalid')
        expected_model_ids = set()
        for entry in profiles:
            _exact(entry, ('profile_ref', 'model_id', 'model_version'))
            ref = entry['profile_ref']
            if (
                type(ref) is not str
                or ref in expected_model_ids
                or ref not in PROFILES
                or (entry['model_id'], entry['model_version']) != PROFILES[ref]
            ):
                raise ConfigInvalid('Code catalogue Profile source differs')
            expected_model_ids.add(ref)
        entries = [option(entry) for entry in data['items']]
        actual_git = _git_value()
        if any(entry['value'] != actual_git for entry in entries if entry['kind'] == 'GIT'):
            raise ConfigInvalid('Code catalogue Git file source differs')
        ids = [entry['option_id'] for entry in entries]
        if ids != sorted(set(ids)):
            raise ConfigInvalid('Code catalogue identities must be unique and sorted')
        actual_models = {
            entry['value']['model_profile_ref'] for entry in entries if entry['kind'] == 'MODEL'
        }
        if (
            actual_models != expected_model_ids
            or sum(entry['kind'] == 'GIT' for entry in entries) != 1
        ):
            raise ConfigInvalid('Code catalogue registered source coverage differs')
        scopes = [entry for entry in entries if entry['kind'] == 'SCOPE']
        if version == 1:
            if scopes:
                raise ConfigInvalid('Legacy catalogue cannot publish managed read scopes')
        elif manifest['managed_read_scopes_sha256'] != MANAGED_READ_SCOPES_SHA256 or sorted(
            scopes, key=lambda row: row['option_id']
        ) != sorted(scope_options(), key=lambda row: row['option_id']):
            raise ConfigInvalid('Managed read-scope source coverage differs')
        policies = [entry for entry in entries if entry['kind'] == 'CONTENT_POLICY']
        if len(policies) != 1 and not (version == 1 and manifest['release_id'] == 'code20-r1'):
            raise ConfigInvalid('Ambiguous content policy registration')
        return CodeCatalogue(
            manifest['release_id'], expected_sha256, canonical_input({'items': entries})
        )
    except ConfigInvalid:
        raise
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as error:
        raise ConfigInvalid('Code catalogue cannot be read or verified') from error


def load_code_catalogue():
    from .code_catalogue_admission import MANIFEST_SHA256, RELEASE_DIRECTORY

    return load_verified_catalogue(ROOT / RELEASE_DIRECTORY, MANIFEST_SHA256)


def prepare_catalogue(release_id):
    """Register a NEW frozen metadata release; never mark runtime/model ready."""
    if type(release_id) is not str or re.fullmatch('[a-z][a-z0-9-]{0,63}', release_id) is None:
        raise ValueError('Explicit safe catalogue release identity required')
    # Preparation verifies all official ZIP/member bytes once, never executes Git.
    if verify_bundle_bytes()[2] != GIT_MANIFEST_SHA256:
        raise ConfigInvalid('Actual Git resource differs from the catalogue authority')
    entries = [
        {
            'option_id': 'git:mingit-' + VERSION,
            'kind': 'GIT',
            'label': 'MinGit ' + VERSION,
            'ready': False,
            'unresolved_capability_codes': ['Q20-GIT', 'Q20-WINDOWS'],
            'value': _git_value(),
        }
    ]
    load_secret_policy(REFERENCE)
    entries.append(
        {
            'option_id': 'content-policy:' + REFERENCE,
            'kind': 'CONTENT_POLICY',
            'label': 'CONTENT20 secret checks v1',
            'ready': False,
            'unresolved_capability_codes': CAPABILITIES,
            'value': dict(CONTENT_VALUE),
        }
    )
    load_managed_read_scopes()
    entries.extend(scope_options())
    sources = []
    for ref, (model, version) in PROFILES.items():
        entries.append(
            {
                'option_id': 'model:' + ref,
                'kind': 'MODEL',
                'label': ref + ' / ' + model,
                'ready': False,
                'unresolved_capability_codes': ['Q20-MODEL'],
                'value': {'model_profile_ref': ref},
            }
        )
        sources.append({'profile_ref': ref, 'model_id': model, 'model_version': version})
    data = _encoded(
        {'schema_version': 1, 'items': sorted(entries, key=lambda item: item['option_id'])}
    )
    manifest = _encoded(
        {
            'schema_version': 2,
            'managed_read_scopes_sha256': MANAGED_READ_SCOPES_SHA256,
            'release_id': release_id,
            'files': [
                {
                    'path': 'options.json',
                    'bytes': len(data),
                    'sha256': hashlib.sha256(data).hexdigest(),
                }
            ],
            'git_manifest_sha256': GIT_MANIFEST_SHA256,
            'model_profiles': sorted(sources, key=lambda item: item['profile_ref']),
        }
    )
    sha = hashlib.sha256(manifest).hexdigest()
    ROOT.mkdir(parents=True, exist_ok=True)
    target = ROOT / release_id
    if target.exists():
        raise FileExistsError('A catalogue release is immutable')
    temporary = Path(mkdtemp(prefix='.code-catalogue-', dir=ROOT))
    try:
        for name, raw in (('options.json', data), ('manifest.json', manifest)):
            with (temporary / name).open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        load_verified_catalogue(temporary, sha)
        os.rename(temporary, target)  # Windows rename never replaces an existing directory.
        return target, sha
    finally:
        if temporary.exists():
            resolved = temporary.resolve()
            if resolved.parent != ROOT.resolve() or not resolved.name.startswith(
                '.code-catalogue-'
            ):
                raise RuntimeError('Refuse cleanup outside original owned publication root')
            shutil.rmtree(resolved)
