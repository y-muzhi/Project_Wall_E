"""V1.5 resource internals used by the existing ResourceCatalog.

No database, provider or mutable release state. All access uses fixed identities
and verified bytes. Offline readiness never grants permission to dispatch Chat.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from jsonschema import Draft202012Validator

from backend.app.shared.validation import strict_json_object

from .resources import ConfigInvalid, _validate
from .schema_transport import compact, declared_json, named_schema

ROOT = Path(__file__).resolve().parents[2] / 'resources' / 'v17'
MANIFEST_SHA256 = 'a8c5087236d8e4b4b40d62a92643832fe37cc2b5e426725f1ddde7d5670abc40'
LONG_MANIFEST_SHA256 = '8a4a16de358eb66a6d057ffba4e54fd3b2e696d4673754cfe1435b0bb79ebc5e'
DOCUMENT_MANIFEST_SHA256 = '91797e9b16c7d6849b2cc739d4f9267a3b11c34a2282aa771f7d8ec62ee461cd'
DOCUMENT_LONG_MANIFEST_SHA256 = '931c7c1d5423a0863cdca3cbf295ed787c3ce688d5ece150bec21031a694178c'
FORMATION_MANIFEST_SHA256 = 'b767b5d83c75a767fb6e4d67e35cdbe6f4af8865bce0ef7244ae6771e99e6eff'
FORMATION_LONG_MANIFEST_SHA256 = '2ceae18bf41655413447d416be870f5b22f54e4d4dd0f7eae41ef1917859b7d9'
FORMATION_CONTEXT_MANIFEST_SHA256 = (
    'f5505794725e072071e3c5f777dfb6b4744f84f13544cd22fb86cd8947cb7e23'
)
FORMATION_CONTEXT_LONG_MANIFEST_SHA256 = (
    '2e52b3a4507eee0b61f901dd5f6a6ef07191feedbc2deae0a94424b3fbd8d3ea'
)
FORMATION_GRAPH_MANIFEST_SHA256 = '8874e28f664dee2017fdb673bd6f8798af66f315eb5b82f808debc29852967d5'
FORMATION_GRAPH_LONG_MANIFEST_SHA256 = (
    'a6adc95e6f263d3c74e445017f6ee9db97a5961ed682ef9c5367851819334c45'
)
FORMATION_ADOPTION_MANIFEST_SHA256 = (
    '0aad8f147f1cc5a279d2370c83632ce30dffc4fab70541c895a01be94cdfd498'
)
FORMATION_ADOPTION_LONG_MANIFEST_SHA256 = (
    '5be0fe0590d41dfbdb5899a06d2addcd8f67e604ca3a1c5e961da1ad600b8dc9'
)
FORMATION_PROVENANCE_MANIFEST_SHA256 = (
    '6afecca289a6369d94abe5d1a9c03ca7f6ff479d6cb4c2c25bff591fd1f3208c'
)
FORMATION_PROVENANCE_LONG_MANIFEST_SHA256 = (
    '2bc51b4e8b90602331dadcb750743ab4f835d3d6ed83c7e2a4048523df53cc44'
)
FORMATION_RULES_MANIFEST_SHA256 = 'a2264f7ba58c7bca3a5b662c972a9bf3f866e7496ccf07b92c8fd2f7298ec08a'
FORMATION_RULES_LONG_MANIFEST_SHA256 = (
    '1ae4a50c73ebf7ebd3e7c177625a3d0e836058da0808de8bbfee404e7767785c'
)
FORMATION_TRANSPORT_MANIFEST_SHA256 = (
    '19fc9e798a9bfb9027638f5e581bc54d7090615a4e71a449f51f1ab45736b046'
)
FORMATION_TRANSPORT_LONG_MANIFEST_SHA256 = (
    '2dae5d4a369eadb8556165c8867abe2a83f5f8bb1e20b58b4a537161b5d7f468'
)
FORMATION_SCHEMA_COUNT_MANIFEST_SHA256 = (
    'cebba2a6deb7a6084584272624ad21ab29760d369a9f8449e84679b22b6f3c24'
)
FORMATION_SCHEMA_COUNT_LONG_MANIFEST_SHA256 = (
    'a3ff49a7787d8f81de2827152fff45896f3c86e84c9b50bef6b3b804169b1f26'
)
FORMATION_FRAMING_MANIFEST_SHA256 = (
    '84290d277cc220452ce3e7889eb8a8a5275c957e8f868018ca884516d1c167fc'
)
FORMATION_FRAMING_LONG_MANIFEST_SHA256 = (
    '60dc7351f1fbac1886b7ace1a8765ff698b8118f543b129a296beed51068266c'
)
FORMATION_FRAMING_BINDING_MANIFEST_SHA256 = (
    'bf4376487589a057492b0aedd872ebb134b151612caba492b39679052b18e4fb'
)
FORMATION_FRAMING_BINDING_LONG_MANIFEST_SHA256 = (
    '14b1b626f891b65d325d0b449aaf64a9e9a3a288514995ed2440f0fba5a3e09d'
)
OPENAI_MANIFEST_SHA256 = '9ddea44727ed60fe6e792708b3f109c7acbd33cb279c5e4e43c446a7dd6a9880'
OPENAI_ARRAY_MANIFEST_SHA256 = '3b10a730eb5fcd346cec68b163bc4a2ee9ef1023674e513a369616bedaeaa543'
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
            if digest not in (
                MANIFEST_SHA256,
                LONG_MANIFEST_SHA256,
                DOCUMENT_MANIFEST_SHA256,
                DOCUMENT_LONG_MANIFEST_SHA256,
                FORMATION_MANIFEST_SHA256,
                FORMATION_LONG_MANIFEST_SHA256,
                FORMATION_CONTEXT_MANIFEST_SHA256,
                FORMATION_CONTEXT_LONG_MANIFEST_SHA256,
                FORMATION_GRAPH_MANIFEST_SHA256,
                FORMATION_GRAPH_LONG_MANIFEST_SHA256,
                FORMATION_ADOPTION_MANIFEST_SHA256,
                FORMATION_ADOPTION_LONG_MANIFEST_SHA256,
                FORMATION_PROVENANCE_MANIFEST_SHA256,
                FORMATION_PROVENANCE_LONG_MANIFEST_SHA256,
                FORMATION_RULES_MANIFEST_SHA256,
                FORMATION_RULES_LONG_MANIFEST_SHA256,
                FORMATION_TRANSPORT_MANIFEST_SHA256,
                FORMATION_TRANSPORT_LONG_MANIFEST_SHA256,
                FORMATION_SCHEMA_COUNT_MANIFEST_SHA256,
                FORMATION_SCHEMA_COUNT_LONG_MANIFEST_SHA256,
                FORMATION_FRAMING_MANIFEST_SHA256,
                FORMATION_FRAMING_LONG_MANIFEST_SHA256,
                FORMATION_FRAMING_BINDING_MANIFEST_SHA256,
                FORMATION_FRAMING_BINDING_LONG_MANIFEST_SHA256,
                OPENAI_MANIFEST_SHA256,
                OPENAI_ARRAY_MANIFEST_SHA256,
            ):
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

    @property
    def formation_driven(self):
        return self.release.get('formation_protocol') == 'formation_v21_1'

    @property
    def layout(self):
        return self.counting['layout']

    @property
    def document_driven(self):
        return 'document_kind' in self.release['guides'][0]

    def guide(self, kind: str) -> dict:
        field = 'document_kind' if self.document_driven else 'phase_kind'
        for item in self.release['guides']:
            if item[field] == kind:
                return strict_json_object(self.content(item['resource_ref']))
        raise ConfigInvalid('Unknown collaboration guide')

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

    def system(self, kind: str, operation: str) -> str:
        guide = self.guide(kind)
        projection = {key: guide[key] for key in GUIDE_FIELDS}
        return (
            self.prompt
            + ('\n\n文档指引 ' if self.document_driven else '\n\n阶段指引 ')
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
        expected_files = 20 if self.document_driven else 21
        if len(self._texts) != expected_files:
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
        kinds = (
            ('brief', 'design', 'specification')
            if self.document_driven
            else ('DISCOVERY', 'SOLUTION', 'SPECIFICATION', 'REVIEW')
        )
        field = 'document_kind' if self.document_driven else 'phase_kind'
        if [item[field] for item in frozen['guides']] != list(kinds):
            raise ValueError('Each guide must be defined exactly once')
        for kind in kinds:
            guide = self.validate('GuideDefinition', self.guide(kind))
            if guide['key'] != 'collaboration.' + kind.lower() or guide[field] != kind:
                raise ValueError('Guide resource mapping mismatch')
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
