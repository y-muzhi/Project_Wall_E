"""Bounded command capture for independent card root scenarios; no runtime diagnosis."""
import argparse,hashlib,json,os,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('group',choices=('success','negative'));args=parser.parse_args()
selected=['RETRY-normal','RETRY-unknown','RETRY-inflight','RETRY-latest'] if args.group=='success' else ['RETRY-scope-invalid','RETRY-work-conflict']
now=datetime.now(timezone.utc).isoformat();stamp=now.replace(':','-');directory=ROOT/'output/playwright'
paths=['tools/run-retry-root-check.py','tools/verify-retry-root-browser.mjs','tools/api-browser-service.py']
def hashes():return {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
before=hashes();command=['C:/Program Files/nodejs/node.exe','tools/verify-retry-root-browser.mjs','--cases',*selected]
env={k:v for k,v in os.environ.items() if not k.startswith('WALLE_')};out=directory/('retry-root-command-'+stamp+'.stdout.log');err=directory/('retry-root-command-'+stamp+'.stderr.log')
with out.open('w',encoding='utf-8') as output,err.open('w',encoding='utf-8') as errors:
 process=subprocess.Popen(command,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=errors,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
 for line in process.stdout:
  output.write(line);output.flush();print(line,end='',flush=True)
 code=process.wait()
after=hashes();record={'recorded_at':now,'scope':'Fixed finite selected cases, isolated native service and external command capture; not runtime/crash investigation','command':command,'selected_cases':selected,'exit_code':code,'stdout':out.read_text(encoding='utf-8'),'stderr':err.read_text(encoding='utf-8'),'inputs_before':before,'inputs_after':after,'model_environment_filtered':True,'passed':code==0 and before==after}
p=ROOT/'docs/verification'/('retry-root-command-'+stamp+'.json');p.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'command_passed':record['passed'],'command_evidence':str(p)},ensure_ascii=False))
if not record['passed']:raise SystemExit(1)
