"""Offline plan by default; explicit exact-plan confirmation is paid execution.

Use --prepare to produce six synthetic model inputs on isolated actual SQLite.
This tool never enables production counting or writes the normal business DB.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.app.infrastructure.audit_data import MAX_AUDIT_BYTES
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.framing_probe import build_plan,validate_plan,digest,collect_observations,prune_raw
from backend.app.infrastructure.model_profile import ModelProfile
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.shared.validation import strict_json_object
from backend.app.shared.time import utc_milliseconds


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--plan',type=Path)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--authorized-plan-sha256')
    parser.add_argument('--output',type=Path,default=ROOT/'output/framing-probe')
    parser.add_argument('--prune-run',type=Path)
    args=parser.parse_args()
    if args.prune_run is not None:
        if args.prepare or args.plan is not None or args.execute or args.authorized_plan_sha256 is not None:parser.error('maintenance cannot execute or authorize')
        count=prune_raw(args.prune_run,utc_milliseconds(datetime.now(timezone.utc)))
        print(json.dumps({'mode':'local_raw_maintenance','records_changed':count,'paid_requests':0}));return
    if args.prepare and (args.plan is not None or args.execute or args.authorized_plan_sha256 is not None):parser.error('prepare cannot execute or authorize')
    if args.prepare:
        from backend.tests.infrastructure.framing_probe_cases import cases
        plan=build_plan(cases());args.output.mkdir(parents=True,exist_ok=True)
        path=args.output/('plan-'+digest(plan)+'.json')
        encoded=(json.dumps(plan,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
        if path.exists():
            if path.read_bytes()!=encoded:raise ConfigInvalid('Existing plan bytes differ')
        else:
            with path.open('xb') as handle:handle.write(encoded)
        print(json.dumps({'mode':'offline','plan':str(path),'plan_sha256':digest(plan),'limits':plan['limits'],'paid_requests':0,'production_compatibility_proved':False},ensure_ascii=False));return
    if args.plan is None:parser.error('use --prepare or --plan')
    with args.plan.open('rb') as handle:encoded=handle.read(MAX_AUDIT_BYTES+1)
    if len(encoded)>MAX_AUDIT_BYTES:raise ConfigInvalid('Plan exceeds capacity')
    plan=validate_plan(strict_json_object(encoded));plan_hash=digest(plan)
    if not args.execute:
        if args.authorized_plan_sha256 is not None:parser.error('authorization only applies to explicit execution')
        print(json.dumps({'mode':'offline','plan_sha256':plan_hash,'limits':plan['limits'],'paid_requests':0,'production_compatibility_proved':False},ensure_ascii=False));return
    if args.authorized_plan_sha256!=plan_hash:raise ConfigInvalid('Human paid confirmation must bind this exact plan')
    # Only this explicit CLI branch reads credentials or instantiates real I/O.
    profile=ModelProfile.from_environment()
    path=args.output/('run-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex)
    report=asyncio.run(collect_observations(plan,profile,path,authorized_plan_sha256=plan_hash))
    print(json.dumps({'report':str(path/'report.json'),'complete_observations':report['complete_observations'],'production_compatibility_proved':False},ensure_ascii=False))
    if not report['complete_observations']:raise SystemExit(1)


if __name__=='__main__':
    try:main()
    except (ConfigInvalid,StorageUnavailable,ValueError,OSError):
        print('Framing probe refused or stopped; inspect private evidence, no automatic resend.',file=sys.stderr);raise SystemExit(1)
