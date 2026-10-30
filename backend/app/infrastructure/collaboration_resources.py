"""V1.5 resource internals used by the existing ResourceCatalog.

No database, provider or mutable release state. All access uses fixed identities
and verified bytes. Offline readiness never grants permission to dispatch Chat.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType

from jsonschema import Draft202012Validator

from .resources import ConfigInvalid, _validate
from .schema_transport import compact, named_schema, declared_json
from backend.app.shared.validation import strict_json_object

ROOT = Path(__file__).resolve().parents[2] / 'resources' / 'v15'
MANIFEST_SHA256 = 'a8c5087236d8e4b4b40d62a92643832fe37cc2b5e426725f1ddde7d5670abc40'
LONG_MANIFEST_SHA256 = '8a4a16de358eb66a6d057ffba4e54fd3b2e696d4673754cfe1435b0bb79ebc5e'
OUTPUTS = MappingProxyType(
    {
        'DISCUSS': 'OutputDiscuss',
        'GENERATE': 'OutputGenerate',
        'REVISE': 'OutputRevise',
        'PROPOSE_CHANGES': 'OutputPropose',
        'COMPARE': 'OutputCompare',
        'REVIEW': 'OutputReview',
    }
)
GUIDE_FIELDS = (
    'goal',
    'mainlines',
    'outcome_requirements',
    'design_methods',
    'questioning_policy',
    'convergence_policy',
    'redirection_policy',
)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class CollaborationResources:
    """Detached projections prevent callers from modifying frozen content."""

    manifest_sha256: str
    _texts: object
    _references: object

    @classmethod
    def load(cls, root: Path = ROOT):
        try:
            root = root.resolve(strict=True)
            manifest_bytes = (root / 'manifest.json').read_bytes()
            digest = hashlib.sha256(manifest_bytes).hexdigest()
            if digest not in (MANIFEST_SHA256, LONG_MANIFEST_SHA256):
                raise ValueError('Collaboration manifest identity changed')
            manifest = strict_json_object(manifest_bytes)
            texts, references = {}, {}
            for file in manifest['files']:
                path = (root / file['path']).resolve(strict=True)
                if not path.is_relative_to(root) or file['path'] in texts:
                    raise ValueError('Unsafe or duplicate resource path')
                content = path.read_bytes()
                digest = hashlib.sha256(content).hexdigest()
                if (
                    len(content) != file['bytes']
                    or digest != file['sha256']
                    or digest != file['resource_ref']['digest']
                ):
                    raise ValueError('Frozen collaboration resource changed')
                key = (file['resource_ref']['key'], file['resource_ref']['version'])
                if key in references:
                    raise ValueError('Duplicate resource identity')
                texts[file['path']] = content.decode('utf-8', errors='strict')
                references[key] = (file['path'], compact(file['resource_ref']))
            value = cls(digest, MappingProxyType(texts), MappingProxyType(references))
            value._check(manifest)
            return value
        except ConfigInvalid:
            raise
        except Exception as error:
            raise ConfigInvalid('Collaboration resource release is missing or invalid') from error

    @property
    def bundle(self):
        return strict_json_object(self.content(self.reference('collaboration.contract')))

    @property
    def release(self):
        return strict_json_object(self.content(self.reference('collaboration.release')))

    @property
    def release_sha256(self):
        return self.release['admission']['release_sha256']

    def schema(self, entry: str) -> dict:
        return named_schema(self.bundle, entry).schema

    def validate(self, entry: str, value):
        # _validate shares the project's strict integer, safe JSON and Unicode
        # checks. Its detached sorted result is not the transport serialization.
        return _validate(named_schema(self.bundle, entry).schema_json, value)

    def validate_cards(self, value):
        return self.validate(
            'StoredCardGroup' if 'program_binding' in value else 'ModelCardGroup', value
        )

    def validate_patch(self, value):
        return self.validate('legacy_patch', value)

    def validate_responses(self, value):
        return self.validate('StoredResponses', value)

    def serialize(self, entry: str, value) -> str:
        return declared_json(self.schema(entry), value)

    def reference(self, key: str, version: str | None = None) -> dict:
        try:
            if version is None:
                matches = [identity for identity in self._references if identity[0] == key]
                if len(matches) != 1:
                    raise KeyError(key)
                version = matches[0][1]
            return strict_json_object(self._references[(key, version)][1])
        except (KeyError, TypeError):
            raise ConfigInvalid('Unknown collaboration resource identity') from None

    def content(self, reference: dict) -> str:
        try:
            path, frozen = self._references[(reference['key'], reference['version'])]
            if reference != strict_json_object(frozen):
                raise ValueError('Resource digest mismatch')
            return self._texts[path]
        except (KeyError, TypeError, ValueError):
            raise ConfigInvalid('Resource identity or digest does not match') from None

    def guide(self, phase_kind: str) -> dict:
        for item in self.release['guides']:
            if item['phase_kind'] == phase_kind:
                return strict_json_object(self.content(item['resource_ref']))
        raise ConfigInvalid('Unknown collaboration phase')

    def structure(self, document_kind: str) -> dict:
        ref = self.reference('structure.' + document_kind)
        return strict_json_object(self.content(ref))

    @property
    def prompt(self):
        return self.content(self.release['prompt'])

    @property
    def counting(self):
        return strict_json_object(self.content(self.release['counting']))

    def output_schema(self, operation: str) -> str:
        if operation not in OUTPUTS:
            raise ConfigInvalid('Unknown collaboration operation')
        for item in self.release['output_schemas']:
            if item['operation'] == operation:
                return self.content(item['schema_ref'])
        raise ConfigInvalid('Missing operation output schema')

    def system(self, phase_kind: str, operation: str) -> str:
        guide = self.guide(phase_kind)
        projection = {key: guide[key] for key in GUIDE_FIELDS}
        return (
            self.prompt
            + '\n\n阶段指引 '
            + guide['key']
            + '@'
            + guide['version']
            + '\n'
            + compact(projection)
            + '\n\n任务输出协议 '
            + operation
            + '\n'
            + self.output_schema(operation)
        )

    def require_live(self, profile_snapshot: dict, *, admission=None) -> None:
        """Offline schema success cannot be passed off as live admission.

        The initial fixed release is OFFLINE_READY. A future authorized live
        evidence path must bind the release/profile and actual call receipts.
        """
        release = self.release
        if sha256(compact(profile_snapshot)) != release['model_profile_sha256']:
            raise ConfigInvalid('Model profile differs from the collaboration release')
        effective = release['admission']
        if admission is not None:
            from .collaboration_admission import AdmissionEvidence

            if type(admission) is not AdmissionEvidence:
                raise ConfigInvalid('Admission must come from verified saved evidence')
            effective = self.validate('Admission', admission.value)
            if (
                effective['release_sha256'] != self.release_sha256
                or effective['profile_sha256'] != release['model_profile_sha256']
            ):
                raise ConfigInvalid('Admission belongs to another release or profile')
        if effective['state'] != 'LIVE_VERIFIED':
            raise ConfigInvalid('Collaboration release has no verified live admission')

    def _check(self, manifest):
        bundle = self.bundle
        Draft202012Validator.check_schema(bundle)
        if len(bundle['$defs']) != 89 or len(self._texts) != 21:
            raise ValueError('Incomplete collaboration release')
        release = self.validate('Release', self.release)
        # Validation returns a detached object sorted for identity checks; the
        # release digest must instead use the declared Release field order.
        frozen = self.release
        digest_body = {key: value for key, value in frozen.items() if key != 'admission'}
        if (
            sha256(compact(digest_body)) != release['admission']['release_sha256']
            or release['admission']['release_sha256'] != manifest['release_sha256']
        ):
            raise ValueError('Release digest is inconsistent')
        if release['admission']['profile_sha256'] != release['model_profile_sha256']:
            raise ValueError('Admission profile is inconsistent')
        if release['admission']['state'] != 'OFFLINE_READY':
            raise ValueError('Initial resource batch cannot declare live evidence')
        phase_kinds = ('DISCOVERY', 'SOLUTION', 'SPECIFICATION', 'REVIEW')
        if [item['phase_kind'] for item in frozen['guides']] != list(phase_kinds):
            raise ValueError('Each phase must be defined exactly once')
        for kind in phase_kinds:
            guide = self.validate('GuideDefinition', self.guide(kind))
            if guide['key'] != 'collaboration.' + kind.lower() or guide['phase_kind'] != kind:
                raise ValueError('Phase resource mapping mismatch')
            self.content(self.reference(guide['key'], guide['version']))
        for kind in ('brief', 'design', 'specification'):
            profile = self.validate('StructureProfile', self.structure(kind))
            if profile['key'] != 'structure.' + kind or profile['document_kind'] != kind:
                raise ValueError('Structure key and document kind mismatch')
        specification = self.structure('specification')
        template = ROOT.parent / 'v7/templates/new-requirement.v4.md'
        if hashlib.sha256(template.read_bytes()).hexdigest() != specification['template_sha256']:
            raise ValueError('Specification template source changed')
        self.validate('CountingDefinition', self.counting)
        expected_schemas = {
            'canonical_schema': 'Canonical',
            'wire_schema': 'Wire',
            'message_schema': 'MessageStructures',
        }
        for key, entry in expected_schemas.items():
            if self.content(frozen[key]) != named_schema(bundle, entry).schema_json:
                raise ValueError('Named schema differs from its complete closure')
        if [item['operation'] for item in frozen['output_schemas']] != list(OUTPUTS):
            raise ValueError('Each operation must be defined exactly once')
        for operation, entry in OUTPUTS.items():
            if self.output_schema(operation) != named_schema(bundle, entry).schema_json:
                raise ValueError('Operation schema differs from its complete closure')
