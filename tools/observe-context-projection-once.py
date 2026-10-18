"""One explicitly authorized historical-snapshot observation, offline by default.

At most one Tokenization batch and one Chat; no retries, adoption, service or
business writes. A durable Markdown slot prevents accidentally repeating it.
Actual private request/response evidence lives only in a cleaned temp folder.
"""
import argparse
import asyncio
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.guide.context_builder import BuiltContext, restore_transport_input, serialize_input
from backend.app.guide.context_projection import document_sections, make_basis, counting_parts
from backend.app.guide.counted_context import counting_release_for_function
from backend.app.infrastructure.audit_data import audit_json
from backend.app.infrastructure.local_credentials import read_local_credential
from backend.app.infrastructure.model_gateway import ModelGateway
from backend.app.infrastructure.model_profile import ModelProfile
from backend.app.infrastructure.production_ai import before_count
from backend.app.infrastructure.resources import ResourceCatalog, ConfigInvalid
from backend.app.infrastructure.schema_transport import compact, function_schema
from backend.app.infrastructure.tokenization import TokenizationGateway, restore_measurement

REPORT = ROOT / 'docs/verification/context-projection-live-once-2026-10-18.md'


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def prepare(database):
    with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute('SELECT * FROM llm_uses WHERE id=21').fetchone()
        if row is None or row['call_status'] != 'SUCCEEDED' or row['validation_status'] != 'SUCCEEDED':
            raise ValueError('The fixed successful baseline #21 is required')
        old = dict(row)
    saved = json.loads(old['request_snapshot_json'])
    catalog = ResourceCatalog()
    protocol = saved['protocol']
    old_function = catalog.restore(protocol['function_type'], protocol['prompt'].split('@')[1])
    canonical = restore_transport_input(json.loads(saved['request']['messages'][1]['content']), old_function)
    if canonical['scope'] != {'scope_type': 'DOCUMENT', 'scope_ref': None}:
        raise ValueError('Only the complete archived DOCUMENT snapshot is supported')
    function = catalog.freeze(canonical['action_type'], canonical['source_type'],
        template_key=canonical['template']['template_key'], template_version=canonical['template']['template_version'])
    if function.version != 'v9' or function.context_policy['transport_layout'] != 'context_projection_v1':
        raise ValueError('The fixed full-budget phase A protocol is required')
    blocks = canonical['current_document']['read_blocks']
    identities = [block['metadata']['block_id'] for block in blocks]
    if identities != canonical['read_manifest']['block_ids'] or not set(canonical['template']['locked_heading_block_ids']).issubset(identities):
        raise ValueError('Archived block/heading coverage is incomplete')
    # The archived DOCUMENT already contains the entire ordered block list.
    # Preserve its exact Markdown, metadata, IDs and plain text; do not read a
    # newer CURRENT or rebuild user prose from current business data.
    parsed = SimpleNamespace(blocks=[SimpleNamespace(heading_level=block['heading_level'], plain_text=block['plain_text']) for block in blocks])
    canonical['section_lookup'] = document_sections(parsed, [block['metadata'] for block in blocks], set(identities))
    canonical['read_manifest']['prompt'] = dict(zip(('key', 'version'), function.prompt_reference.split('@')))
    canonical['read_manifest']['context_template'] = dict(zip(('key', 'version'), function.context_template.split('@')))
    canonical = function.validate_input(canonical)
    encoded = serialize_input(canonical, function)
    system = function.prompt + '\n' + function_schema(function).schema_json
    basis = make_basis(canonical, function)
    context = BuiltContext(system, encoded, compact(canonical['read_manifest']), len(system.encode())+len(encoded.encode()), (), (), basis_json=compact(basis))
    profile = ModelProfile.from_snapshot(saved['profile'])
    plan = {'source_llm_use_id': 21, 'source_request_sha256': sha(compact(saved['request'])),
        'request_sha256': sha(compact(profile.request(context))), 'model': profile.model_name,
        'old_actual_input': old['input_tokens'], 'old_actual_output': old['output_tokens'],
        'old_cached': json.loads(old['cache_info_json'] or '{}').get('cached_tokens'),
        'blocks': len(blocks), 'history_messages': len(canonical['history']),
        'function': function.prompt_reference, 'template': canonical['template']['template_key']+'@'+canonical['template']['template_version'],
        'old_characters': sum(len(message['content']) for message in saved['request']['messages']),
        'new_characters': len(system)+len(encoded), 'maximum_count_batches': 1, 'maximum_chat_attempts': 1,
        'maximum_output_tokens': 8192, 'business_writes': False}
    return plan, function, canonical, context, saved['profile']


async def execute(plan, function, canonical, context, stored_profile):
    at = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
    # An interrupted/failed slot is not permission to resend. No overwrite.
    with REPORT.open('x', encoding='utf-8', newline='\n') as report:
        report.write('# 上下文 Token 一期：单次真实请求对照\n\n')
        report.write(f'时间：{at}（Asia/Hong_Kong）。用户授权：发送一次真实请求测试Token节省。\n\n')
        report.write('独立历史快照观测；最多1次Tokenization批次＋1次Chat，无重试，不运行产品任务或采用返回。\n\n')
        report.write('```json\n'+json.dumps(plan,ensure_ascii=False,indent=2)+'\n```\n\n')
        report.flush(); os.fsync(report.fileno())
    def note(text):
        with REPORT.open('a', encoding='utf-8', newline='\n') as report:
            report.write(text+'\n'); report.flush(); os.fsync(report.fileno())
    stage = 'CREDENTIAL'
    count_calls = chat_calls = 0
    try:
        key = os.environ.get('WALLE_MODEL_API_KEY') or read_local_credential(ROOT / '.env.local')
        profile = ModelProfile.from_snapshot(stored_profile, api_key=key)
        release = counting_release_for_function(profile, function)
        if not before_count(profile, function, release): raise ConfigInvalid('Frozen admission unavailable')
        texts = (context.system, context.input_json, *counting_parts(canonical, function))
        with tempfile.TemporaryDirectory(prefix='walle-projection-live-once-') as directory:
            private = Path(directory)
            def journal(name, value):
                with (private/(name+'.json')).open('x',encoding='utf-8',newline='\n') as handle:
                    handle.write(audit_json(value,credentials=(key,)));handle.flush();os.fsync(handle.fileno())
            stage = 'COUNT'
            journal('count-prepared',{'profile':profile.snapshot,'texts':list(texts)})
            note('计数批次1已准备；开始一次精确分词。')
            count_calls += 1
            receipt = await TokenizationGateway().count(profile, texts)
            restore_measurement(receipt.evidence,texts,expected_model=profile.model_name)
            budget=release['budget'];counts=receipt.counts
            estimate=counts[0]+counts[1]+1024
            if any(count>budget[limit] for count,limit in zip((counts[0],counts[2],counts[3],counts[4],counts[5]),
                    ('prompt_tokens','current_user_tokens','source_tokens','template_tokens','history_tokens'))) or estimate>budget['input_tokens'] or estimate+8192>budget['total_tokens']:
                raise ConfigInvalid('The single candidate exceeds the existing budget; no trim or retry')
            note(f'精确预检通过：六项{list(counts)}；输入含1024余量={estimate}；计数请求ID={receipt.request_id}。\n')
            stage='CHAT'
            journal('chat-prepared',{'request':profile.request(context),'context_basis':json.loads(context.basis_json),'source_request_sha256':plan['source_request_sha256']})
            note('Chat尝试1已准备；发送一次请求。该记录不是成功或收费证明。')
            chat_calls += 1
            result=await ModelGateway().send(profile,context)
            journal('chat-observed',{'succeeded':result.succeeded,'http_status':result.http_status,'category':result.category,'raw_response':result.raw_response})
            if not result.succeeded: raise ConfigInvalid('The one Chat attempt failed; no retry')
            raw=result.raw_response
            if raw.get('model')!=profile.model_name:raise ConfigInvalid('Returned model differs')
            usage=raw.get('usage',{})
            incoming,outgoing,total=(usage.get(name) for name in ('prompt_tokens','completion_tokens','total_tokens'))
            if any(type(value) is not int or value<0 for value in (incoming,outgoing,total)) or total!=incoming+outgoing:
                raise ConfigInvalid('Actual usage is missing or inconsistent')
            cached=usage.get('prompt_tokens_details',{}).get('cached_tokens')
            old_in,old_out=plan['old_actual_input'],plan['old_actual_output']
            saving=old_in-incoming
            message=raw.get('choices',[{}])[0].get('message',{}).get('content','')
            try: response_type=json.loads(message).get('response_type')
            except (ValueError,AttributeError):response_type=None
            summary={'actual_input_tokens':incoming,'actual_output_tokens':outgoing,'actual_total_tokens':total,
                'cached_input_tokens':cached,'input_tokens_saved':saving,'input_reduction_percent':round(saving*100/old_in,2),
                'old_total_tokens':old_in+old_out,'total_tokens_difference':old_in+old_out-total,
                'duration_ms':result.duration_ms,'finish_reason':result.finish_reason,'response_type':response_type,
                'chat_request_id':result.provider_request_id,'observed_framing_delta':incoming-counts[0]-counts[1],
                'count_batches_invoked':count_calls,'chat_attempts_invoked':chat_calls}
            note('\n## 实际结果\n\n```json\n'+json.dumps(summary,ensure_ascii=False,indent=2)+'\n```\n')
            note('对照使用调用21的同一归档正文、完整模板、历史和本轮输入；仅替换一期封装、定位索引与冻结Prompt。旧请求不重发。缓存计入输入，不重复加到合计；不同轮输出量和缓存状态不同，总量差及费用不可视为固定节省率。只有一次样本，不证明通用效果或供应方封装上界。\n')
            print(json.dumps(summary,ensure_ascii=False),flush=True)
    except BaseException as error:
        note(f'\n停止阶段：{stage}；错误类型：{type(error).__name__}。计数调用={count_calls}，Chat调用={chat_calls}；不重试、不据此推断收费。\n')
        raise SystemExit('Single observation stopped; see Markdown stage record. No retry.') from None
    finally:
        note('\n临时请求／响应JSON由TemporaryDirectory清理，仅留本Markdown摘要；未启动服务、未修改业务库或用户正文。\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--expected-request-sha256')
    args=parser.parse_args()
    plan,function,canonical,context,profile=prepare(ROOT/'data/wall-e.sqlite')
    if not args.execute:
        print(json.dumps(plan,ensure_ascii=False,indent=2));return
    if args.expected_request_sha256!=plan['request_sha256']:
        raise SystemExit('Exact inspected request digest required')
    asyncio.run(execute(plan,function,canonical,context,profile))


if __name__=='__main__':main()
