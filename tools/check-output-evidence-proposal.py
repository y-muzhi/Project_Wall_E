"""Inspect candidate bytes/references only; no adoption or provider operation."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from jsonschema import Draft202012Validator
from backend.app.infrastructure.resources import ConfigInvalid, ResourceCatalog, _inspect_schema

base=ROOT/'backend/resources/v1';candidate=ROOT/'docs/proposals/resources-v2'
manifest=json.loads((candidate/'manifest.json').read_bytes())
if manifest['status']!='PROPOSED' or manifest['base_manifest_sha256']!=hashlib.sha256((base/'manifest.json').read_bytes()).hexdigest():
    raise AssertionError('Candidate must retain the exact approved base and proposed status')
checked=[]
for entry in manifest['files']:
    path=(candidate/entry['path']).resolve()
    if not path.is_relative_to(candidate) or path.stat().st_size!=entry['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:
        raise AssertionError('Candidate bytes or containment invalid')
    if entry['path'].startswith(('schemas/','templates/')):
        if path.read_bytes()!=(base/entry['path']).read_bytes():raise AssertionError('Approved Schema/template changed')
        checked.append(entry['path'])
    if entry['path'].startswith('schemas/'):
        schema=json.loads(path.read_bytes());Draft202012Validator.check_schema(schema);_inspect_schema(schema,schema)
entries=json.loads((candidate/'functions.v2.json').read_bytes())['functions']
old=json.loads((base/'functions.v1.json').read_bytes())['functions']
if len(entries)!=6:raise AssertionError('All six tasks required')
for new,prior in zip(entries,old):
    expected={**prior,'version':'v2','prompt':prior['prompt'].replace('@v1','@v2'),'context_template':prior['context_template'].replace('@v1','@v2')}
    if new!=expected:raise AssertionError('Function mapping changed unexpectedly')
    context=json.loads((candidate/('contexts/'+new['context_template'].replace('@','.')+'.json')).read_bytes())
    original=json.loads((base/('contexts/'+prior['context_template'].replace('@','.')+'.json')).read_bytes())
    if context!={**original,'prompt':new['prompt']}:raise AssertionError('Budget/input/transport changed')
    text=(candidate/('prompts/'+new['prompt'].replace('@','.')+'.md')).read_text(encoding='utf-8')
    prefix=(base/('prompts/'+prior['prompt'].replace('@','.')+'.md')).read_text(encoding='utf-8').replace('@v1\n','@v2\n',1).replace(prior['context_template'],new['context_template']).rstrip()+'\n'
    if not text.startswith(prefix) or '补充闭合协议' not in text:raise AssertionError('Prior Prompt behavior missing or no exact card rule')
    if new['action_type']=='INITIALIZE' and '完整确认声明证明' not in text:raise AssertionError('Fact rule missing')
try:ResourceCatalog(candidate)
except ConfigInvalid:activation_rejected=True
else:raise AssertionError('Unapproved candidate must not be executable')
report=json.loads((ROOT/'docs/verification/P2-2026-10-05T05-30-40-765Z.json').read_text(encoding='utf-8'))
changed=[name for name,digest in report['inputs']['after'].items() if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest]
if changed:raise AssertionError('Native verified inputs changed while drafting')
record={'recordedAt':datetime.now(timezone.utc).isoformat(),'scope':'Candidate structural/reference/byte checks only; no activation, model compatibility or completed AI business.',
    'passed':True,'files_checked':len(manifest['files']),'unchanged_schema_template_files':checked,
    'function_count':len(entries),'budget_transport_unchanged':True,'unapproved_catalog_activation_rejected':activation_rejected,
    'verified_native_inputs_checked':len(report['inputs']['after']),'changed_native_inputs':changed,
    'candidate_manifest_sha256':hashlib.sha256((candidate/'manifest.json').read_bytes()).hexdigest()}
path=ROOT/'docs/verification'/('output-evidence-proposal-'+record['recordedAt'].replace(':','-').replace('.','-')+'.json')
path.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'passed':True,'evidence':str(path),'files_checked':len(manifest['files'])},ensure_ascii=True))
