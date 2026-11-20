"""Publish separate immutable V2.1 model resource batches without provider or service I/O."""

import hashlib
import json
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORMATION_BEHAVIOR_RULES = """V2.1本轮任务与引用规则
按current_request.content中明确标出的本轮任务执行；场景背景和历史材料用于理解。请求明确要求给STAGED_WRITE或FORMATION_PATH_CHANGE提案时，在DISCUSS下也可出该用途卡，由用户采用后程序执行。提案不直接写正文；不得把“操作为DISCUSS”解释为禁止给提案。实际指令仍有未消解冲突或必需材料不足时，说明具体缺口并给NEED_MATERIAL，不编造已完成。
形成步骤s/成果s.o、支线b、问题i、Artifact a与旧讨论主题t是不同身份域。formation的step_ref不能放进旧progress_delta的topic字段。topic_changes、focus_topic_ref、next_step.topic_ref、evidence_changes的topic_refs/applies_to及dependencies只用实际提供的t或本轮已完整声明的new_t。没有实际主题时focus_topic_ref=null、next_step.topic_ref=null；全局依据applies_to="GLOBAL"。不从s2生成t2，不为了给建议强造旧topic。形成步骤评估和下一步建议使用formation_delta中的ASSESS_STEP/RECOMMEND及真实step_ref。
没有实际讨论进展时progress_delta=null；有形成增量时保留完整六字段，可让topic_changes/evidence_changes为空、focus_topic_ref/next_step为null，同时填合法formation_delta。processed_user_message_ids仅取本次实际携带且pending的消息。formation_delta.basis及路线action_payload.basis取project_position.formation.basis中的四个公开冻结值，不读取/输出程序私有ContextBasis；源只引用实际Wire中的材料别名。
路线卡先逐一检查被取消步骤的每个expected_results。result_routes必须覆盖每一个原result_ref，不因其文字被新成果包含就省略映射；REPLACED目标只用本卡已声明的temp_result_ref，CONTENT继续承接CONTENT、ANALYSIS继续承接ANALYSIS。ADD_STEP使用temp_step_ref，步骤的expected_results使用temp_result_ref，依赖只能引用真实StepRef或本卡TempStepRef。不得让新旧有效步骤继续依赖将被取消的旧步骤；需要转交时明确SET_DEPENDENCIES。OPEN问题给明确去向，实际可见开放支线保留origin并明确return；未携带完整实体的暂缓问题保留原归属与DEFERRED并如实说明，不擅自MOVE/恢复。必需定义缺失则请求材料。路线卡同轮progress_delta的formation_delta必须null，不能边提案边实际改路线。
STAGED_WRITE只覆盖该步骤真实CONTENT成果。write_mode仅为FILL_EMPTY或PATCH_EXISTING：实际空文档提供完整markdown_content、DOCUMENT scope及空patches；已有内容给精确patches并让markdown_content=null。REPLACE_BLOCK的original_content逐字复制当前目标块，proposed_markdown恰好包含一个顶层区块并保持目标块类型；段落目标用一个段落，不拼入标题、列表、第二段或范围外反馈内容。目标身份、Revision、content_version、Goal及definition_version均取实际提供值。卡片只提出补丁，不能在message中声称已经写入。
ASSOCIATE_CONTENT使用当前Revision与实际块别名，原Artifact存在时给实际review_of。ASSESS_STEP区分程序匹配与语义充分，逐项检查预期CONTENT/ANALYSIS成果；材料不足用GAPS_REMAIN或UNCERTAIN，下一步只给RECOMMEND，不执行结束/重开。保持用户已确认范围及暂缓要求，不能把资料缺失写成需求不存在。
发送前核对：明确任务是否完成；九根及嵌套required齐全；t/s及TempStepRef/TempResultRef不混用；所有来源/引用实际可见；取消成果映射齐全、依赖无悬空；单块补丁只有一个顶层区块；本轮没有代用户执行保存、结束、恢复或处置。只输出规定JSON，不附加自检说明。"""


FORMATION_OUTPUT_RULES = 'V2.1严格区块引用与两类新增步骤\ndocument_refs专门表示本轮documents中当前目标Revision已经发送的区块ref，逐字复制如d42v2b12；d42v2只是文档别名，d42v2.b12也不是合法区块别名。旧Revision、参考文档及未发送块不能作为当前成果覆盖。空文档的ASSESS_STEP.document_refs必须[]，按材料给GAPS_REMAIN或UNCERTAIN；无当前块不能ASSOCIATE_CONTENT，应请求先写入内容。source_refs仍用实际携带的消息/区块/其他合法材料别名，不与document_refs混同。\n下面仅示范两套ADD_STEP对象形状，示例中的身份必须替换为本轮真实或本卡完整声明的身份：\n普通progress_delta.formation_delta.changes中的对象：\n{"type":"ADD_STEP","temp_ref":"new_step_1","title":"核对推荐流程","expected_results":[{"temp_ref":"new_result_1","description":"明确推荐流程","kind":"CONTENT"}],"dependencies":["s1"],"topic_refs":[],"before_step_ref":null}\nFORMATION_PATH_CHANGE卡action_payload.changes中的对象：\n{"type":"ADD_STEP","temp_step_ref":"new_step_1","title":"核对推荐流程","expected_results":[{"temp_result_ref":"new_result_1","description":"明确推荐流程","kind":"CONTENT"}],"dependencies":["s1"],"replaces_step_refs":["s2"],"before_step_ref":"s3"}\n普通增量没有temp_step_ref/temp_result_ref/replaces_step_refs；路线卡没有temp_ref/topic_refs。JSON Schema格式约束不代表权限，继续满足来源/成果映射/依赖/事务规则；不输出替代私有依据。'


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def build(source_batch, batch):
    from backend.app.formation.resource_schema import definitions
    from backend.app.infrastructure.resources import _validate
    from backend.app.infrastructure.schema_transport import named_schema

    source = ROOT / 'backend/resources' / source_batch
    manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    entries = {item['resource_ref']['key']: item for item in manifest['files']}

    def read(key):
        entry = entries[key]
        raw = (source / entry['path']).read_bytes()
        if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError('Frozen source resource changed')
        return raw.decode('utf-8')

    schema = json.loads(read('collaboration.contract'))
    batch_number = int(batch.removeprefix('v'))
    if batch_number < 19:
        raise ValueError('Formation resources require a new batch')
    contract_version = 'v' + str(batch_number - 12)
    release_version = 'v' + str(batch_number - 8)
    counting_version = 'v' + str(batch_number - 14)
    schema['$id'] = 'urn:walle:collaboration-contract:' + contract_version
    schema['$defs'] = definitions(schema['$defs'])
    files, refs = {}, {}

    def add(path, content, key, version):
        raw = content.encode('utf-8')
        reference = {'key': key, 'version': version, 'digest': hashlib.sha256(raw).hexdigest()}
        files[path] = raw
        refs[path] = reference
        return reference

    add(
        'schemas/collaboration-contract.' + contract_version + '.json',
        compact(schema),
        'collaboration.contract',
        contract_version,
    )
    named = {}
    for entry, stem in (
        ('Canonical', 'canonical'),
        ('Wire', 'wire'),
        ('ContextBasis', 'basis'),
        ('MessageStructures', 'messages'),
    ):
        named[entry] = add(
            'schemas/collaboration-' + stem + '.v3.json',
            named_schema(schema, entry).schema_json,
            'collaboration.' + stem,
            'v3',
        )
    outputs = []
    for operation, entry in (
        ('DISCUSS', 'OutputDiscuss'),
        ('GENERATE', 'OutputGenerate'),
        ('REVISE', 'OutputRevise'),
        ('PROPOSE_CHANGES', 'OutputPropose'),
        ('COMPARE', 'OutputCompare'),
        ('REVIEW', 'OutputReview'),
    ):
        reference = add(
            'schemas/output-' + operation.lower() + '.v5.json',
            named_schema(schema, entry).schema_json,
            'collaboration.output.' + operation.lower(),
            'v5',
        )
        outputs.append({'operation': operation, 'schema_ref': reference})
    guides = []
    for kind in ('brief', 'design', 'specification'):
        entry = entries['collaboration.' + kind]
        reference = add(
            entry['path'],
            read('collaboration.' + kind),
            entry['resource_ref']['key'],
            entry['resource_ref']['version'],
        )
        guides.append({'document_kind': kind, 'resource_ref': reference})
    structures = []
    for kind in ('brief', 'design', 'specification'):
        entry = entries['structure.' + kind]
        structures.append(
            add(
                entry['path'],
                read('structure.' + kind),
                entry['resource_ref']['key'],
                entry['resource_ref']['version'],
            )
        )
    design = ROOT / 'docs/iterations/pending/v2.1/WALL-E.后端设计文档_V_2.1.md'
    design_raw = design.read_bytes()
    start = design_raw.decode('utf-8').index('> 你在同份文档内协助形成成果。')
    instruction = design_raw.decode('utf-8')[start:].splitlines()[0][2:]
    prompt = (
        read('collaboration.common')
        + '\n\nV2.1文档形成协议（本段及本次严格输出Schema约束新增用途）\n'
        + instruction
    )
    prompt += '\nprogress_delta非空时严格包含原五字段及formation_delta；没有变化则整个progress_delta=null。保持原九根，不能增加第十根。新增source_refs使用实际携带的材料别名；公开SourceRef对象仅由程序解析生成。重大路线卡同轮formation_delta必须null。精确写入卡不授予正文执行权限。\n'
    prompt += '\n' + FORMATION_BEHAVIOR_RULES + '\n' + FORMATION_OUTPUT_RULES + '\n'
    prompt_ref = add('prompts/collaboration-common.v10.md', prompt, 'collaboration.common', 'v10')
    counting = json.loads(read('collaboration.counting'))
    counting['layout'] = 'formation_context_v21_1'
    counting['system_text'] = 'system_plus_output_schema_v1'
    counting['framing_reserve'] = 2048
    counting_ref = add(
        'counting/collaboration-counting.' + counting_version + '.json',
        compact(counting),
        'collaboration.counting',
        counting_version,
    )
    release = deepcopy(json.loads(read('collaboration.release')))
    release.update(
        version=release_version,
        canonical_schema=named['Canonical'],
        wire_schema=named['Wire'],
        message_schema=named['MessageStructures'],
        output_schemas=outputs,
        guides=guides,
        structure_profiles=structures,
        prompt=prompt_ref,
        counting=counting_ref,
        compiler_version='formation_compiler_v21_1',
        formation_protocol='formation_v21_1',
        model_transport={
            'mode': 'json_schema',
            'projection': 'ark_supported_keywords_v1',
            'strict': True,
            'operations': ['DISCUSS'],
            'bind_current_blocks': True,
        },
    )
    release['admission']['reserve'] = counting['framing_reserve']
    release = {key: release[key] for key in schema['$defs']['Release']['properties']}
    body = {key: value for key, value in release.items() if key != 'admission'}
    release_hash = hashlib.sha256(compact(body).encode('utf-8')).hexdigest()
    release['admission']['release_sha256'] = release_hash
    _validate(named_schema(schema, 'Release').schema_json, release)
    _validate(named_schema(schema, 'CountingDefinition').schema_json, counting)
    add(
        'release.' + release_version + '.json',
        compact(release),
        'collaboration.release',
        release_version,
    )
    result = {
        'schema_version': 1,
        'key': 'collaboration_v1',
        'version': batch,
        'design_sha256': hashlib.sha256(design_raw).hexdigest(),
        'release_sha256': release_hash,
        'files': [
            {
                'path': name,
                'bytes': len(raw),
                'sha256': refs[name]['digest'],
                'resource_ref': refs[name],
            }
            for name, raw in files.items()
        ],
    }
    raw_manifest = compact(result).encode('utf-8')
    target = ROOT / 'backend/resources' / batch
    if target.exists():
        raise ValueError('Immutable resource batch already exists')
    with tempfile.TemporaryDirectory(prefix='.formation-release-', dir=target.parent) as directory:
        staged = Path(directory) / batch
        for name, raw in {**files, 'manifest.json': raw_manifest}.items():
            path = staged / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        if target.exists():
            raise ValueError('Resource destination appeared while building')
        os.replace(staged, target)
    return {
        'batch': batch,
        'manifest_sha256': hashlib.sha256(raw_manifest).hexdigest(),
        'release_sha256': release_hash,
        'file_count': len(files),
    }


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    sys.stdout.reconfigure(encoding='utf-8')
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--first-batch', type=int, default=19)
    first = parser.parse_args().first_batch
    if first < 19 or first % 2 != 1:
        parser.error('First batch must be a new odd batch number')
    for source, target in (('v17', 'v' + str(first)), ('v18', 'v' + str(first + 1))):
        print(compact(build(source, target)))
