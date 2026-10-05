"""Measure approved frozen System budgets offline; never modify resources."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.infrastructure.resources import ResourceCatalog, FUNCTIONS


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def reachable_schema(value):
    """Analysis only: prune unreachable local defs, not a transport policy."""
    root = json.loads(compact(value))
    definitions = root.pop('$defs')
    reachable = set()
    def walk(node):
        if isinstance(node, dict):
            for key, child in node.items():
                if key == '$ref':
                    if not child.startswith('#/$defs/'): raise ValueError('Non-local ref')
                    name = child[8:]
                    if name not in reachable:
                        reachable.add(name); walk(definitions[name])
                else: walk(child)
        elif isinstance(node, list):
            for child in node: walk(child)
    walk(root)
    root['$defs'] = {key: value for key, value in definitions.items() if key in reachable}
    return root


catalog, rows = ResourceCatalog(), []
for action, source in FUNCTIONS:
    function = catalog.freeze(action, source)
    schema = json.loads(function.output_schema_json)
    full = function.prompt+'\n'+compact(schema)
    pruned = function.prompt+'\n'+compact(reachable_schema(schema))
    limit = function.context_policy['budget']['prompt_tokens']
    rows.append({'function_type':function.function_type,'manifest_sha256':function.manifest_sha256,
        'prompt_bytes':len(function.prompt.encode('utf-8')),'compact_full_schema_bytes':len(compact(schema).encode('utf-8')),
        'full_system_bytes':len(full.encode('utf-8')),'approved_system_limit':limit,
        'full_system_exceeds_limit':len(full.encode('utf-8')) > limit,
        'analysis_only_reachable_schema_system_bytes':len(pruned.encode('utf-8')),
        'analysis_only_reachable_schema_still_exceeds_limit':len(pruned.encode('utf-8')) > limit})
now = datetime.now(timezone.utc).isoformat()
record = {'scope':'Offline frozen-resource budget measurement only; no Provider tokenizer proof or paid call, no transport-policy adoption',
    'recorded_at':now,'counting':'approved conservative UTF-8 bytes; no token count inferred','resources_unchanged':True,
    'all_six_full_systems_exceed_approved_budget':all(row['full_system_exceeds_limit'] for row in rows),
    'all_six_analysis_pruned_systems_also_exceed':all(row['analysis_only_reachable_schema_still_exceeds_limit'] for row in rows),
    'inputs':{path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in ('backend/resources/v1/manifest.json','backend/app/guide/context_builder.py','tools/inspect-context-budget.py')}, 'functions':rows}
path = ROOT/'docs/verification'/('context-budget-'+now.replace(':','-').replace('.','-')+'.json')
path.write_bytes((json.dumps(record,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
print(json.dumps({'evidence':str(path),'all_six_over_budget':record['all_six_full_systems_exceed_approved_budget'], 'pruning_alone_insufficient':record['all_six_analysis_pruned_systems_also_exceed']},ensure_ascii=True))
