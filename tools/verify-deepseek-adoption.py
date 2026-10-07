"""Capture D-014 offline regression command and source hashes, without keys."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def hashes():
    paths=[path for path in (ROOT/'backend').rglob('*')
           if path.is_file() and path.suffix in ('.py','.json','.sql','.md','.lock')]
    paths.append(Path(__file__))
    return {path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--full',action='store_true');args=parser.parse_args()
    modules=['backend.tests.infrastructure.test_deepseek_adoption',
             'backend.tests.infrastructure.test_model_profile_audit_data',
             'backend.tests.infrastructure.test_audit_repository',
             'backend.tests.infrastructure.test_tokenization',
             'backend.tests.infrastructure.test_framing_probe',
             'backend.tests.guide.test_counted_context',
             'backend.tests.guide.test_counted_orchestrator',
             'backend.tests.guide.test_trusted_output',
             'backend.tests.guide.test_orchestrator']
    arguments=['discover','-s','backend/tests','-t','.','-v'] if args.full else [*modules,'-v']
    command=[sys.executable,'-X','utf8','-m','unittest',*arguments]
    environment={key:value for key,value in os.environ.items() if not key.startswith('WALLE_')}
    environment['PYTHONIOENCODING']='utf-8'
    before=hashes();at=datetime.now(timezone.utc).isoformat()
    completed=subprocess.run(command,cwd=ROOT,env=environment,capture_output=True,encoding='utf-8')
    after=hashes();changes=[path for path in sorted(before.keys()|after.keys()) if before.get(path)!=after.get(path)]
    match=re.search(r'Ran (\d+) tests? in',completed.stderr)
    record={'scope':'D-014 offline SQLite/loopback regression; no paid request, framing/effect proof, live preview write or restart.',
            'recorded_at':at,'full_backend':args.full,'command':command,'exit_code':completed.returncode,
            'stdout':completed.stdout,'stderr':completed.stderr,'tests':int(match[1]) if match else None,
            'inputs_before':before,'inputs_after':after,'changed_inputs':changes,
            'passed':completed.returncode==0 and not changes}
    path=ROOT/'docs/verification'/('deepseek-adoption-'+at.replace(':','-').replace('.','-')+'.json')
    path.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'passed':record['passed'],'tests':record['tests'],'evidence':str(path)},ensure_ascii=False))
    if not record['passed']:
        print(completed.stderr[-12000:])
        return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
