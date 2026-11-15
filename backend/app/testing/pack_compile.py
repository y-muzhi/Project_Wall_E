"""Deterministic compilation of a fixed Testing plan to CHECK20 resources."""

from dataclasses import dataclass
from hashlib import sha256

from backend.app.code_tasks.check_set_content import (
    PROTOCOL,
    STAGES,
    CheckSetContent,
    parse_check_set_content,
)
from backend.app.code_tasks.design_revisions import design_revision_choice
from backend.app.infrastructure.check_case_pack import (
    CaseBasis,
    CasePack,
    CasePackLimits,
    decode_case_pack,
    validate_draft_operations,
)
from backend.app.infrastructure.check_runner_bundle import (
    CheckResourceError,
    reference,
    valid_sha256,
)
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.shared.validation import strict_enum, strict_integer

from .plan_content import PLAN_FIELDS, publication_gap

LIMITS = CasePackLimits(4096, 256, 1024 * 1024, 3600)
MAX_PACK_BYTES = 32 * 1024 * 1024


class CompileError(ValueError):
    def __init__(self, field, message):
        super().__init__(message)
        self.field = field


def encoded(value):
    return canonical_input(value).encode('utf-8')


def digest(value):
    return sha256(value).hexdigest()


def plan_digest(plan):
    return digest(encoded({field: plan[field] for field in PLAN_FIELDS}))


def basis_fingerprint(connection, plan):
    """Bind the fixed references and each stored Revision's actual UTF-8 source."""
    sources = [
        (plan['document_id'], plan['design_revision_id'], 'MAIN'),
        *[
            (item['document_id'], item['revision_id'], 'MATERIAL')
            for item in sorted(plan['material_refs'], key=lambda row: row['document_id'])
        ],
    ]
    original = []
    for document, revision, usage in sources:
        row = design_revision_choice(
            connection, document, revision, usage=usage, include_markdown=True
        )
        if row is None or not row['eligible'] or row['requirement_id'] != plan['requirement_id']:
            raise CompileError('design_revision_id', 'Original confirmed Testing basis differs')
        original.append(
            {
                'document_id': document,
                'revision_id': revision,
                'usage': usage,
                'source_sha256': digest(row['markdown_snapshot'].encode('utf-8')),
            }
        )
    return digest(encoded({'requirement_id': plan['requirement_id'], 'sources': original}))


def _refs(values, *, minimum=0):
    if type(values) is not tuple or not minimum <= len(values) <= 256:
        raise CheckResourceError('TESTING_TARGET_REFERENCES_INVALID')
    for value in values:
        reference(value)
    if len(set(values)) != len(values):
        raise CheckResourceError('TESTING_TARGET_DUPLICATE_REFERENCE')


@dataclass(frozen=True)
class CompilerTarget:
    target_ref: str
    driver_kind: str
    runner_ref: str
    runner_sha256: str
    fixture_ref: str
    fixture_sha256: str
    command_ids: tuple[str, ...]
    endpoint_refs: tuple[str, ...]
    environment_refs: tuple[str, ...]
    protected_input_refs: tuple[str, ...]
    external_dependency_mode: str

    def __post_init__(self):
        for value in (self.target_ref, self.runner_ref, self.fixture_ref):
            reference(value)
        if not valid_sha256(self.runner_sha256) or not valid_sha256(self.fixture_sha256):
            raise CheckResourceError('TESTING_TARGET_DIGEST_INVALID')
        strict_enum(self.driver_kind, 'driver_kind', ('CLI', 'HTTP', 'BROWSER'))
        strict_enum(
            self.external_dependency_mode, 'external_dependency_mode', ('NONE', 'OFFLINE_STUB')
        )
        _refs(self.command_ids, minimum=1)
        _refs(self.endpoint_refs, minimum=int(self.driver_kind != 'CLI'))
        _refs(self.environment_refs)
        _refs(self.protected_input_refs)
        if self.driver_kind == 'CLI' and self.endpoint_refs:
            raise CheckResourceError('TESTING_CLI_TARGET_NETWORK_NOT_ALLOWED')

    def wire(self):
        return {
            key: list(value) if isinstance(value, tuple) else value
            for key in self.__dataclass_fields__
            for value in (getattr(self, key),)
        }


@dataclass(frozen=True)
class CompiledPack:
    pack_id: int
    plan_version_id: int
    plan_sha256: str
    basis_sha256: str
    sha256: str
    files: tuple[tuple[str, bytes], ...]
    check_set: CheckSetContent
    targets: tuple[CompilerTarget, ...]
    case_ids: tuple[str, ...]
    case_packs: tuple[CasePack, ...]


def _case_target(case, targets):
    commands = {step['command_id'] for step in case['steps'] if step['op'] == 'RUN'}
    endpoints = {
        step['endpoint_ref'] for step in case['steps'] if step['op'] in ('NAVIGATE', 'REQUEST')
    }
    return [
        item
        for item in targets
        if item.driver_kind == case['driver_kind']
        and commands.issubset(item.command_ids)
        and endpoints.issubset(item.endpoint_refs)
    ]


def case_targets(plan, targets):
    if not plan['cases']:
        raise CompileError('cases', 'No controlled case is available to compile')
    if any(type(item) is not CompilerTarget for item in targets) or len(
        {item.target_ref for item in targets}
    ) != len(targets):
        raise CompileError('cases', 'Testing target registration is ambiguous')
    selected = []
    for index, case in enumerate(plan['cases']):
        matches = _case_target(case, targets)
        if len(matches) != 1:
            raise CompileError(f'cases[{index}]', 'Case needs one exact registered Testing target')
        try:
            validate_draft_operations(case, case['driver_kind'], LIMITS, complete=True)
        except (CheckResourceError, TypeError, ValueError) as error:
            raise CompileError(
                f'cases[{index}]', 'Case does not satisfy the CHECK20 closed grammar'
            ) from error
        selected.append(matches[0])
    return tuple(selected)


def _sources(rows):
    selected = set()
    for row in rows:
        for ref in row['basis_refs']:
            selected.add((ref['document_id'], ref['revision_id'], ref['quote']))
            if len(selected) > 256:
                raise CompileError('cases', 'Case basis exceeds the CHECK20 reference limit')
    return [
        {'document_id': document, 'revision_id': revision, 'quote': quote}
        for document, revision, quote in sorted(selected)
    ]


def _check_item(identity, name, stages, target, pack_ref=None, timeout=1):
    controlled = pack_ref is not None
    return {
        'check_id': identity,
        'name': name,
        'stages': list(stages),
        'required': True,
        'check_kind': 'CONTROLLED_ASSERTION',
        'command_id': None,
        'runner_ref': target.runner_ref,
        'case_pack_ref': pack_ref,
        'expected_exit_codes': None,
        'environment_refs': list(target.environment_refs),
        'protected_input_refs': list(target.protected_input_refs),
        'target': {
            'application_mode': 'REAL_CANDIDATE',
            'external_dependency_mode': target.external_dependency_mode,
            'command_ids': list(target.command_ids),
            'fixture_ref': target.fixture_ref,
        }
        if controlled
        else None,
        'timeout_seconds': timeout,
        'evidence_rule': {'kind': 'CONTROLLED_CASES' if controlled else 'CONTENT_INTEGRITY'},
    }


def _case_group(cases, sources, target, *, bundle, version):
    fixed = []
    for case, basis in cases:
        fixed.append(
            {
                'case_id': case['case_id'],
                'name': case['name'],
                'basis_refs': basis,
                'steps': case['steps'],
                'assertions': case['assertions'],
                'timeout_seconds': case['timeout_seconds'],
            }
        )
    raw = encoded(
        {
            'schema_version': 1,
            'protocol_version': PROTOCOL,
            'bundle_id': bundle,
            'version': str(version),
            'driver_kind': target.driver_kind,
            'basis_refs': sources,
            'cases': fixed,
        }
    )
    parsed = decode_case_pack(
        raw,
        limits=LIMITS,
        basis_refs=tuple(CaseBasis(**ref) for ref in sources),
        command_ids=target.command_ids,
        endpoint_refs=target.endpoint_refs,
    )
    return raw, parsed


def compile_pack(plan, targets, *, pack_id, version, basis_sha256):
    """Convert structured values only. Test execution and resource admission are separate."""
    strict_integer(pack_id, 'pack_id')
    strict_integer(version, 'version')
    if not valid_sha256(basis_sha256):
        raise CompileError('design_revision_id', 'Original basis digest is unavailable')
    if plan['unresolved_questions'] or not plan['behaviors']:
        raise CompileError('behaviors', 'A fixed reviewed behavior matrix is required')
    gap = publication_gap(plan)
    if gap is not None:
        raise CompileError(gap, 'Original plan is incomplete')
    case_registrations = case_targets(plan, targets)
    by_id = {row['behavior_id']: row for row in plan['behaviors']}
    selected = {}
    groups = {}
    case_bytes = 0
    for case, target in zip(plan['cases'], case_registrations, strict=True):
        selected[target.target_ref] = target
        rows = [by_id[identity] for identity in case['behavior_ids']]
        stages = tuple(stage for stage in STAGES if any(stage in row['stages'] for row in rows))
        key = (target.target_ref, stages, case['visibility'])
        sources = _sources(rows)
        case_bytes += len(encoded({'basis_refs': sources})) + len(encoded(case))
        if case_bytes > MAX_PACK_BYTES:
            raise CompileError('cases', 'Compiled pack exceeds the fixed byte limit')
        groups.setdefault(key, []).append((case, sources))
    applicable = {
        stage
        for row in plan['behaviors']
        if row['mode'] != 'NOT_APPLICABLE'
        for stage in row['stages']
    }
    covered = {stage for _, stages, _ in groups for stage in stages}
    if not applicable.issubset(covered):
        raise CompileError('cases', 'Every applicable stage requires controlled cases')

    members = []
    member_bytes = 0
    manifest_groups = []
    case_packs = []
    items = [
        _check_item(
            'content-integrity',
            '固定输入完整性',
            [stage for stage in STAGES if stage in applicable],
            selected[min(selected)],
        )
    ]
    check_by_case = {}
    for number, ((target_ref, stages, visibility), cases) in enumerate(sorted(groups.items()), 1):
        target = selected[target_ref]
        sources = _sources([{'basis_refs': basis} for _, basis in cases])
        bundle = f'testing-pack-{pack_id}-{number}'
        try:
            raw, parsed = _case_group(cases, sources, target, bundle=bundle, version=version)
        except (CheckResourceError, ValueError, TypeError) as error:
            raise CompileError(
                'cases', 'Fixed case does not satisfy the CHECK20 closed grammar'
            ) from error
        member_bytes += len(raw)
        if member_bytes > MAX_PACK_BYTES:
            raise CompileError('cases', 'Compiled pack exceeds the fixed byte limit')
        filename = f'cases-{number}.json'
        member_digest = digest(raw)
        members.append((filename, raw))
        case_packs.append(parsed)
        manifest_groups.append(
            {
                'path': filename,
                'sha256': member_digest,
                'byte_count': len(raw),
                'driver_kind': target.driver_kind,
                'target_ref': target_ref,
                'stages': list(stages),
                'visibility': visibility,
            }
        )
        check_id = f'controlled-{number}'
        for case, _ in cases:
            check_by_case[case['case_id']] = check_id
        items.append(
            _check_item(
                check_id,
                '受控测试用例 ' + str(number),
                stages,
                target,
                'casepack:sha256:' + member_digest,
                sum(case['timeout_seconds'] for case, _ in cases),
            )
        )
    coverage = [
        {
            'coverage_id': row['behavior_id'],
            'basis_refs': row['basis_refs'],
            'stages': row['stages'],
            'mode': row['mode'],
            'check_ids': sorted({check_by_case[case_id] for case_id in row['case_ids']}),
            'explanation': row['explanation'],
        }
        for row in plan['behaviors']
        if row['mode'] != 'UNCOVERED'
    ]
    try:
        check_set = parse_check_set_content(
            {'protocol_version': PROTOCOL, 'items': items, 'coverage_plan': coverage},
            owner_module='TESTING',
            max_input_bytes=8 * 1024 * 1024,
        )
    except (TypeError, ValueError) as error:
        raise CompileError('cases', 'Compiled CheckSet is outside the closed grammar') from error
    check_bytes = encoded(check_set.value())
    members.append(('check-set.json', check_bytes))
    content_sha256 = plan_digest(plan)
    manifest = encoded(
        {
            'schema_version': 1,
            'protocol_version': PROTOCOL,
            'pack_id': pack_id,
            'version': version,
            'plan_version_id': plan['id'],
            'plan_sha256': content_sha256,
            'basis_fingerprint': basis_sha256,
            'check_set': {
                'path': 'check-set.json',
                'sha256': digest(check_bytes),
                'byte_count': len(check_bytes),
            },
            'targets': [selected[key].wire() for key in sorted(selected)],
            'case_packs': manifest_groups,
            'uncovered_behavior_ids': [
                row['behavior_id'] for row in plan['behaviors'] if row['mode'] == 'UNCOVERED'
            ],
        }
    )
    members.append(('manifest.json', manifest))
    if sum(len(raw) for _, raw in members) > MAX_PACK_BYTES:
        raise CompileError('cases', 'Compiled pack exceeds the fixed byte limit')
    return CompiledPack(
        pack_id,
        plan['id'],
        content_sha256,
        basis_sha256,
        digest(manifest),
        tuple(sorted(members)),
        check_set,
        tuple(selected[key] for key in sorted(selected)),
        tuple(sorted(check_by_case)),
        tuple(case_packs),
    )
