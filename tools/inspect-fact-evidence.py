"""Offline actual-storage counterexamples, not a model call or acceptance pass."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.tests.requirements.test_create_requirement import CreateRequirementTests
from backend.app.guide.queries import get_model_context
from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.documents.scopes import restore_authority
from backend.app.documents.patch_validation import validate_patch


def inspect(text, quote):
    fixture=CreateRequirementTests();fixture.setUp()
    try:
        created=fixture.create(initial_idea=text)['data']
        context=get_model_context(fixture.database,created['guide_run_id'],catalog=fixture.catalog)['data']
        function=fixture.catalog.freeze('INITIALIZE','USER_INSTRUCTION')
        current=context['current_document'];before=fixture.facts()
        with fixture.database.transaction() as connection:
            snapshot=validate_snapshot(current['markdown_content'],current['block_state_json'],DocumentSources(connection,context['requirement']['id'],fixture.catalog))
            authority=restore_authority(snapshot,'INITIALIZE',context['run']['scope_type'],None,context['run']['allowed_targets_json'])
            target=next(identity for identity,(block,metadata) in snapshot.by_id.items() if block.block_type=='paragraph' and
                any(item.block_id==identity and 'REPLACE_BLOCK' in item.operations for item in authority.allowed_targets))
            patch={'title':'diagnostic fabricated approval role','explanation':'adversarial constructed candidate, never adopted','impact':None,
                'target_ref':{'block_id':target},'original_content':snapshot.by_id[target][0].markdown,
                'patch_operation':'REPLACE_BLOCK','selector_json':None,'proposed_markdown':'审批人为部门经理。','proposed_data_json':None}
            output={'schema_version':1,'response_type':'INITIALIZE_TEXT','message':'adversarial diagnostic only',
                'confirmed_fact_patches':[{'patch':patch,'evidence':[{'message_id':context['user_input']['id'],'quoted_text':quote}]}]}
            function.parse_output(json.dumps(output,ensure_ascii=False));validate_patch(snapshot,patch,authority)
        unchanged=fixture.facts()==before
        if quote not in context['user_input']['content'] or not unchanged:raise AssertionError('Counterexample fixture did not retain actual facts')
        return {'actual_user_message':context['user_input']['content'],'actual_user_message_id':context['user_input']['id'],
            'candidate':output,'schema_passed':True,'actual_authority_patch_passed':True,'verbatim_user_quote_passed':True,
            'fact_consistency_proven':False,'reason':'The full actual USER statement denies or conditions the asserted department-manager role; its short quote does not confirm the candidate fact.',
            'database_unchanged':unchanged,'current_sha256':hashlib.sha256(current['markdown_content'].encode()).hexdigest()}
    finally:fixture.doCleanups()


cases=[inspect('审批人尚未确定，不能写成部门经理。','审批人'),inspect('如果审批人是部门经理，是否会更快？目前还未决定。','部门经理')]
record={'recordedAt':datetime.now(timezone.utc).isoformat(),'scope':'Actual SQLite/C03/frozen Schema/patch authority counterexamples; adversarial candidates only, no Provider, adoption, completed business or real-effect claim.',
    'cases':cases,'counterexample_reproduced':all(case['database_unchanged'] and not case['fact_consistency_proven'] for case in cases)}
path=ROOT/'docs'/'verification'/('fact-evidence-'+record['recordedAt'].replace(':','-').replace('.','-')+'.json')
path.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'counterexample_reproduced':record['counterexample_reproduced'],'evidence':str(path)},ensure_ascii=True))
