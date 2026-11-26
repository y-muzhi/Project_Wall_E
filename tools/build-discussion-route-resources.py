"""Build the three immutable V2.11 discussion releases from their pinned predecessors."""

import hashlib
import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.infrastructure.schema_transport import compact, named_schema
from backend.app.infrastructure.collaboration_resources import CollaborationResources, OUTPUTS

PROMPT = """
文档主线讨论（本节细化前述自动形成规则）。本轮先区分探索、建议、明确指令和采用。阅读当前 route_context 的有效路线、焦点、已定结论、开放问题、最近可采用的提案。用户说“继续”时承接焦点与开放问题；临时插问不改变持久焦点。询问影响、比较、引述他人、反对、假设、请求建议时只回答或提供可采用的路线卡，不能据此提交主线。区分同一句中被否定的部分与明确执行的部分。不因自动判断讨论充分而新建、改线、结束步骤或写正文。
若用户明确指令，formation_delta 使用用户原话绑定。directive.user_ref 必须是 current_request.message_ref，directive.quote 必须逐字摘取当前消息中包含动作及目标的完整指令。只给出文档用途时先提出建议；明确要求建线时用带 directive 的 ordinary changes INITIALIZE_PATH。一般问题、依据、评估仍可沿原结构更新。更新现有路线用 EXECUTE，复用 FormationPathChange 与 result_routes，focus.mode 分为 KEEP、STEP、DOCUMENT。调序默认 KEEP；“先聊 B，顺序不动”用空 changes 和 STEP；拆并可指向同批 new_step_N。旧成果、依赖或问题去向不明时只问缺失的一项。不要在同轮再发布待采用路线卡。仅在确有唯一、上一轮仍可采用的路线方案且本轮明确同意时用 ADOPT，原样引用其 proposal_ref 与 payload_digest；切勿重写其内容或借普通认可写正文。未执行的建议、材料不足和失败不得写成“已经修改”。route_context.order 是阅读用位置；不为未携带必要依据的对象取得写权限。
"""


def ref(name):
    return {'$ref': '#/$defs/' + name}


def obj(**properties):
    return {
        'type': 'object',
        'properties': properties,
        'required': list(properties),
        'additionalProperties': False,
    }


def nullable(value):
    return {'anyOf': [value, {'type': 'null'}]}


def schema_for_route(bundle):
    defs = bundle['$defs']
    string = {'type': 'string', 'minLength': 1}
    directive = obj(user_ref=ref('FormationAliasRef'), quote={**string, 'maxLength': 10000})
    ordinary = defs['FormationDelta']
    bound = deepcopy(ordinary)
    bound['properties']['directive'] = directive
    bound['required'].append('directive')
    focus = {
        'anyOf': [
            obj(mode={'const': mode}, step_ref={'type': 'null'}) for mode in ('KEEP', 'DOCUMENT')
        ]
        + [obj(mode={'const': 'STEP'}, step_ref=ref('PathStepRef'))]
    }
    path = defs['FormationPathPayload']['properties']
    proposal = defs['FormationProposalContext']['properties']['proposal_ref']
    digest = {'type': 'string', 'pattern': '^[a-f0-9]{64}$'}
    execute = obj(
        intent={'const': 'EXECUTE'},
        basis=ref('FormationBasis'),
        directive=directive,
        changes={**deepcopy(path['changes']), 'minItems': 0},
        result_routes=deepcopy(path['result_routes']),
        focus=focus,
    )
    adopt = obj(
        intent={'const': 'ADOPT'},
        basis=ref('FormationBasis'),
        directive=directive,
        proposal_ref=proposal,
        payload_digest=digest,
    )
    defs['FormationDelta'] = {'anyOf': [ordinary, bound, execute, adopt]}
    for name, source in (
        ('CanonicalFormation', 'SourceRef'),
        ('WireFormation', 'FormationAliasRef'),
    ):
        sources = {'type': 'array', 'items': ref(source)}
        decision = obj(evidence_ref=string, text=string, source_refs=sources)
        order_item = obj(
            step_ref=ref('FormationStepRef'),
            title=ref('FormationTitle'),
            position=ref('ID'),
            dependencies={'type': 'array', 'items': ref('FormationStepRef')},
        )
        route = obj(
            order={'type': 'array', 'items': order_item, 'maxItems': 100},
            step_total={'type': 'integer', 'minimum': 0},
            focus_step_ref=nullable(ref('FormationStepRef')),
            decisions={'type': 'array', 'items': decision, 'maxItems': 3},
            previous_proposal=nullable(
                obj(proposal_ref=proposal, payload_digest=digest, summary=string)
            ),
        )
        defs[name]['properties']['route_context'] = route
        defs[name]['required'].append('route_context')


EXTENDED_PROMPT = """
未建线时，如用户只在探索，可用 SUGGEST_INITIAL 给出一份可采用的步骤方案，并在回复中说明目标及每步建议。它不会建线。仅在紧邻上一轮有 initial_proposal 且用户明确采用时用 ADOPT_INITIAL，保留原目标、步骤、顺序和预期成果。若用户直接提出自己的明确建线要求，仍可用 INITIALIZE_PATH。
用户要求恢复上次顺序时，RESTORE_ORDER 引用 previous_order 的 batch_id，只恢复受影响位置，默认保留当前焦点和其间业务结论。无对应记录或要求指向不同批次时，先解释需要确认哪次顺序。
用户明确结束、暂停、重开步骤或处置支线时使用 LIFECYCLE，按实际带入的证据和身份选择 command。只说“聊清楚了”时建议收尾，未明确结束不执行。COMPLETE_STEP 的 result_dispositions 只覆盖明确裁定的事项，未明确落地不要标为已写入。未处置的真实遗留项由程序保留。next_step_ref 仅用于用户指定的下一目标。暂时插问不触发状态转换。所有动作只作用于本轮文档。
"""


def schema_for_lifecycle(bundle):
    defs = bundle['$defs']
    variants = defs['FormationDelta']['anyOf']
    directive = variants[-1]['properties']['directive']

    def entry(intent, **fields):
        return obj(intent={'const': intent}, basis=ref('FormationBasis'), **fields)

    def array(item):
        return {'type': 'array', 'items': item, 'maxItems': 20}

    def enum(*values):
        return {'type': 'string', 'enum': list(values)}

    def action(kind, **fields):
        return obj(action={'const': kind}, **fields)

    initial = defs['FormationChange']['oneOf'][0]['properties']
    step = ref('FormationStepRef')
    branch = ref('FormationBranchRef')
    issue = ref('FormationIssueRef')
    digest = {'type': 'string', 'pattern': '^[a-f0-9]{64}$'}
    variants.extend(
        [
            entry('SUGGEST_INITIAL', goal=ref('FormationText'), steps=deepcopy(initial['steps'])),
            entry(
                'ADOPT_INITIAL', directive=directive, message_id=ref('ID'), payload_digest=digest
            ),
            entry(
                'RESTORE_ORDER',
                directive=directive,
                batch_id=ref('ID'),
                focus=deepcopy(variants[2]['properties']['focus']),
            ),
        ]
    )

    def remaining(kind):
        return array(
            obj(
                ref=kind,
                disposition=enum('KEEP_OPEN', 'TRANSFER', 'DEFERRED', 'DROPPED'),
                to_step_ref=nullable(step),
                reason=nullable(ref('FormationText')),
            )
        )

    commands = [
        obj(action=enum('START_STEP', 'PAUSE_STEP', 'RESUME_STEP', 'REOPEN_STEP'), step_ref=step),
        action('ENTER_BRANCH', step_ref=step, branch_ref=branch),
        action('RETURN_FROM_BRANCH', branch_ref=branch),
        action(
            'DISPOSE_BRANCH',
            branch_ref=branch,
            disposition=enum('DEFERRED', 'DROPPED'),
            reason=ref('FormationText'),
        ),
        action(
            'RESUME_BRANCH',
            step_ref=step,
            branch_ref=branch,
            expected_branch_status=enum('DEFERRED', 'RESOLVED'),
            expected_branch_event_id=ref('ID'),
            enter_after_resume={'type': 'boolean'},
        ),
        action('RESUME_ISSUE', issue_ref=issue),
        action(
            'COMPLETE_STEP',
            step_ref=step,
            next_step_ref=nullable(step),
            result_dispositions=array(
                obj(
                    result_ref=ref('FormationResultRef'),
                    status=enum('OUTSTANDING', 'LANDED', 'ANALYZED'),
                    artifact_refs=array(ref('FormationArtifactRef')),
                    source_refs=array(ref('FormationAliasRef')),
                )
            ),
            issue_dispositions=remaining(issue),
            branch_dispositions=remaining(branch),
        ),
    ]
    variants.append(entry('LIFECYCLE', directive=directive, command={'anyOf': commands}))
    for name in ('CanonicalFormation', 'WireFormation'):
        route = defs[name]['properties']['route_context']
        route['properties'].update(
            initial_proposal=nullable(
                obj(
                    message_id=ref('ID'),
                    payload_digest=digest,
                    goal=ref('FormationText'),
                    titles=array(ref('FormationTitle')),
                )
            ),
            previous_order=nullable(
                obj(
                    batch_id=ref('ID'),
                    moves={
                        'type': 'array',
                        'maxItems': 100,
                        'items': obj(step_ref=step, before=ref('ID'), after=ref('ID')),
                    },
                )
            ),
        )
        route['required'].extend(['initial_proposal', 'previous_order'])


LINK_PROMPT = """
结论与步骤有明确归属时，在本轮 progress_delta.step_evidence_links 列出 step_ref、evidence_ref。可用本轮新步骤／新依据的临时身份，也可引用实际带入的有效步骤和依据。只关联有用户来源、内容已定且确实适用于该步的事实或决定。仅为文档整体的决定、临时插问与 AI 建议不自动归到当前步骤；一个决定可明确关联多步。已存在的真实主题关联继续有效。只建立关联不是更改路线、写正文或结束步骤。
"""


def schema_for_links(bundle):
    definitions = bundle['$defs']
    linked = deepcopy(definitions['Progress'])
    linked['properties']['step_evidence_links'] = {
        'type': 'array',
        'minItems': 1,
        'maxItems': 100,
        'items': obj(step_ref=ref('PathStepRef'), evidence_ref=ref('Ref')),
    }
    linked['required'].append('step_evidence_links')
    definitions['DiscussionProgressWithLinks'] = linked
    definitions['OutputDiscussion']['properties']['progress_delta']['anyOf'].append(
        ref('DiscussionProgressWithLinks')
    )


INITIAL_FOCUS_PROMPT = """
用户明确指定建线后的讨论目标时，可在 ADOPT_INITIAL 给出原建议中的 focus_position（从 1 数起），按原顺序创建全部步骤并进入该步。用户直接指定具体主线和起始步骤时，用 CREATE_INITIAL，注明原话、goal、steps 和 focus_position。不得为了切换焦点重排或重写已建议的步骤。采用现成路线卡且用户另指定焦点时，ADOPT 可同时给出 focus，原提案内容仍须原样采用。未指定讨论目标时沿用已有规则。
"""


def schema_for_initial_focus(bundle):
    variants = bundle['$defs']['FormationDelta']['anyOf']
    intents = {
        v['properties']['intent']['const']: v['properties']
        for v in variants
        if 'intent' in v['properties']
    }
    position = {'type': 'integer', 'minimum': 1, 'maximum': 20}
    variants.extend(
        [
            obj(**deepcopy(intents['ADOPT_INITIAL']), focus_position=position),
            obj(**deepcopy(intents['ADOPT']), focus=deepcopy(intents['EXECUTE']['focus'])),
            obj(
                intent={'const': 'CREATE_INITIAL'},
                basis=ref('FormationBasis'),
                directive=deepcopy(intents['ADOPT']['directive']),
                goal=ref('FormationText'),
                steps=deepcopy(intents['SUGGEST_INITIAL']['steps']),
                focus_position=position,
            ),
        ]
    )


def schema_for_review_groups(bundle):
    defs = bundle['$defs']
    group = obj(
        title={'type': 'string', 'minLength': 1, 'maxLength': 120},
        reason={'type': 'string', 'minLength': 1, 'maxLength': 600},
        suggestion_orders={
            'type': 'array',
            'items': {'type': 'integer', 'minimum': 1, 'maximum': 100},
            'minItems': 1,
            'maxItems': 100,
            'uniqueItems': True,
        },
    )
    analysis = deepcopy(defs['OutputAnalysis'])
    proposals = defs['OutputProposals']
    proposals['properties']['suggestion_groups'] = {
        'type': 'array',
        'items': group,
        'minItems': 1,
        'maxItems': 100,
    }
    proposals['required'].append('suggestion_groups')
    analysis['properties']['suggestion_groups'] = {'type': 'null'}
    analysis['required'].append('suggestion_groups')
    defs['OutputProposalAnalysis'] = analysis
    defs['OutputPropose']['oneOf'][1]['allOf'][0] = ref('OutputProposalAnalysis')


def build(
    old,
    version,
    *,
    extended=False,
    links=False,
    initial_focus=False,
    document_output=False,
    review_groups=False,
):
    directory = ROOT / 'backend/resources'
    predecessor = directory / old
    resources = CollaborationResources.load(predecessor)
    original = json.loads((predecessor / 'manifest.json').read_bytes())
    files = {}
    refs = {}
    bundle = deepcopy(resources.bundle)
    bundle['$id'] = 'urn:walle:collaboration-contract:' + version
    if document_output:
        from backend.app.infrastructure.model_profile import OPENAI_DOCUMENT_PROFILE, ModelProfile

        profile = ModelProfile('offline-resource-build-only', OPENAI_DOCUMENT_PROFILE)
        counting = deepcopy(resources.counting)
        counting['output_limit'] = profile.output_limit
        counting['total_limit'] = counting['input_limit'] + counting['output_limit']
        for key in ('output_limit', 'total_limit'):
            bundle['$defs']['CountingDefinition']['properties'][key]['const'] = counting[key]
        if review_groups:
            schema_for_review_groups(bundle)
    elif initial_focus:
        schema_for_initial_focus(bundle)
    elif links:
        schema_for_links(bundle)
    elif extended:
        schema_for_lifecycle(bundle)
    else:
        schema_for_route(bundle)
    named = {
        'collaboration.' + key: entry
        for key, entry in (
            ('canonical', 'Canonical'),
            ('wire', 'Wire'),
            ('basis', 'ContextBasis'),
            ('messages', 'MessageStructures'),
        )
    }
    named.update({'collaboration.output.' + key.lower(): value for key, value in OUTPUTS.items()})
    release = deepcopy(resources.release)
    metadata = []

    def record(row, content):
        previous = row['resource_ref']
        key = previous['key']
        data = content.encode('utf-8')
        digest = hashlib.sha256(data).hexdigest()
        changed = previous['digest'] != digest
        path = Path(row['path'])
        if changed:
            path = path.with_name(key + '.' + version + path.suffix)
        reference = dict(
            key=key, version=version if changed else previous['version'], digest=digest
        )
        refs[key] = reference
        metadata.append(
            dict(path=path.as_posix(), bytes=len(data), sha256=digest, resource_ref=reference)
        )
        files[path] = data

    for row in original['files']:
        key = row['resource_ref']['key']
        if key == 'collaboration.release':
            release_row = row
            continue
        if key == 'collaboration.contract':
            content = compact(bundle)
        elif key in named:
            content = named_schema(bundle, named[key]).schema_json
        elif key == 'collaboration.counting' and document_output:
            content = compact(counting)
        elif key == 'collaboration.common' and review_groups:
            content = resources.prompt.rstrip() + (
                '\n\nPROPOSE_CHANGES 的 CHANGE_PROPOSALS 必须返回 suggestion_groups。按修改意图分组，'
                '每组给出标题、原因和 suggestions 数组中从 1 起的序号。每条建议恰好归一组，'
                '组内保持原顺序。没有可执行补丁时用 ANALYSIS，suggestion_groups 为 null。\n'
            )
        elif key == 'collaboration.common' and not document_output:
            content = (
                resources.prompt.rstrip()
                + '\n\n'
                + (
                    INITIAL_FOCUS_PROMPT
                    if initial_focus
                    else LINK_PROMPT
                    if links
                    else EXTENDED_PROMPT
                    if extended
                    else PROMPT
                ).strip()
                + '\n'
            )
        else:
            content = resources.content(row['resource_ref'])
        record(row, content)
    if old.startswith('openai-'):
        from backend.app.infrastructure.openai_schema import schema_for

        for block_refs in (None, [], ['d1v1b1']):
            schema_for(named_schema(bundle, 'OutputDiscuss').schema_json, block_refs=block_refs)
            if review_groups:
                schema_for(named_schema(bundle, 'OutputPropose').schema_json, block_refs=block_refs)
    release['version'] = version
    if document_output:
        profile_hash = hashlib.sha256(compact(profile.snapshot).encode()).hexdigest()
        release['model_profile_sha256'] = profile_hash
        release['admission']['profile_sha256'] = profile_hash
        release['counting'] = refs['collaboration.counting']
    for name in ('canonical_schema', 'wire_schema', 'message_schema', 'prompt'):
        release[name] = refs[release[name]['key']]
    for row in release['output_schemas']:
        row['schema_ref'] = refs[row['schema_ref']['key']]
    digest = hashlib.sha256(
        compact({k: v for k, v in release.items() if k != 'admission'}).encode()
    ).hexdigest()
    release['admission']['release_sha256'] = digest
    record(release_row, compact(release))
    # SHA-256 of V2.11 item 20, revision 3, at resource freeze.
    design_hash = 'c956878365a6d2ded8ed357eba9de2f802a178c9e8cac17abe65adfcc60c59a5'
    if review_groups:
        design_hash = '4354df77fc637047202c33d1a2b78572d320fc72d60ad4c67ad42d82b1c1db13'
    if not document_output:
        design = ROOT / 'docs/iterations/pending/v2.11/WALL-E.进展简化与讨论主线迭代V1_V_2.11.md'
        design_hash = hashlib.sha256(design.read_bytes()).hexdigest()
    manifest = {
        **original,
        'version': version,
        'design_sha256': design_hash,
        'release_sha256': digest,
        'files': metadata,
    }
    files[Path('manifest.json')] = compact(manifest).encode()
    target = directory / version
    if target.exists():
        if {
            path.relative_to(target): path.read_bytes()
            for path in target.rglob('*')
            if path.is_file()
        } != files:
            raise ValueError('Installed resource differs from reproducible build: ' + version)
    else:
        with TemporaryDirectory(dir=directory) as temporary:
            staged = Path(temporary) / version
            for path, content in files.items():
                out = staged / path
                out.parent.mkdir(parents=True, exist_ok=True)
                with out.open('xb') as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
            os.rename(staged, target)
    print(version, hashlib.sha256(files[Path('manifest.json')]).hexdigest())


if __name__ == '__main__':
    for old, version in [('v37', 'v39'), ('v38', 'v40'), ('openai-v2', 'openai-v3')]:
        build(old, version)
    for old, version in [('v39', 'v41'), ('v40', 'v42'), ('openai-v3', 'openai-v4')]:
        build(old, version, extended=True)
    for old, version in [('v41', 'v43'), ('v42', 'v44'), ('openai-v4', 'openai-v5')]:
        build(old, version, links=True)
    for old, version in [('v43', 'v45'), ('v44', 'v46'), ('openai-v5', 'openai-v6')]:
        build(old, version, initial_focus=True)
    build('openai-v6', 'openai-v7', document_output=True)
    build('openai-v7', 'openai-v8', document_output=True, review_groups=True)
