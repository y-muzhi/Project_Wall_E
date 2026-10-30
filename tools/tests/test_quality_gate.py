"""Regression checks for the runner's failure and isolation boundaries."""
from datetime import datetime, timezone
from pathlib import Path
import os
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import quality_gate as gate


class QualityGateTests(unittest.TestCase):
    def test_nested_evaluation_admission_file_fits_temporary_root(self):
        with TemporaryDirectory(prefix='walle-v15-ev-runner-') as directory:
            path=Path(directory)/'data/unique/laboratory/analysis-required-over-budget/evaluation.sqlite.count-audit'/('collaboration-'+'a'*64+'.admission.json')
            path.parent.mkdir(parents=True)
            path.write_text('temporary probe',encoding='utf-8')
            self.assertEqual(path.read_text(encoding='utf-8'),'temporary probe')

    def test_environment_drops_credentials_and_product_configuration(self):
        env=gate.environment(Path('temporary'), {'PATH':'retained','WALLE_DATABASE_PATH':'private',
            'DEEPSEEK_API_KEY':'private','HTTPS_PROXY':'private','NODE_OPTIONS':'private'})
        self.assertEqual(env['PATH'],'retained')
        self.assertFalse(any(key in env for key in ('WALLE_DATABASE_PATH','DEEPSEEK_API_KEY','HTTPS_PROXY','NODE_OPTIONS')))

    def test_exit_status_and_timeout(self):
        with TemporaryDirectory() as directory:
            env=gate.environment(Path(directory))
            for script,expected in [('print("ok")','PASSED'),('raise SystemExit(7)','FAILED'),
                ('import time; time.sleep(30)','TIMEOUT')]:
                result=gate.run_stage('runner',[sys.executable,'-B','-c',script],directory,env,.3 if expected=='TIMEOUT' else 10)
                self.assertEqual(result['status'],expected)

    def test_zero_tests_is_failure(self):
        with TemporaryDirectory() as directory:
            result=gate.run_stage('frontend',[sys.executable,'-c','print("# tests 0")'],directory,gate.environment(Path(directory)),10)
            self.assertEqual(result['status'],'FAILED')

    def test_cancel_stops_owned_process(self):
        with patch.object(gate.subprocess,'Popen') as factory, patch.object(gate,'stop_owned') as stop:
            factory.return_value.communicate.side_effect=[KeyboardInterrupt(),('',None)]
            result=gate.run_stage('runner',['unused'],gate.ROOT,{},10)
            self.assertEqual(result['status'],'CANCELLED')
            stop.assert_called_once_with(factory.return_value)

    def test_report_never_passes_missing_steps_changed_sources_or_cleanup_failure(self):
        with TemporaryDirectory() as directory, patch.object(gate,'ROOT',Path(directory)):
            (Path(directory)/'docs/verification/v1.5').mkdir(parents=True)
            row=dict(stage='runner',status='PASSED',seconds=1,code=0,summary='ok',failures=[])
            for rows,before,after,cleanup,expected in [([row],'a','a',True,0),
                ([], 'a','a',True,1),([row],'a','b',True,1),([row],'a','a',False,1)]:
                path,code=gate.write_report(rows,('runner',),before,after,directory,cleanup,datetime.now(timezone.utc),'test')
                self.assertEqual(code,expected)
                self.assertIn('部分检查',path.read_text(encoding='utf-8'))

    def test_python_guards_reject_external_network_and_non_test_database(self):
        with TemporaryDirectory() as directory:
            script='''
from pathlib import Path
import socket, sqlite3, sys
sys.path.insert(0,sys.argv[1])
from quality_python import install_guards
root=Path(sys.argv[2]); temporary=Path(sys.argv[3])
install_guards(root,temporary)
for operation in [lambda: socket.create_connection(('203.0.113.1',443)),
                  lambda: sqlite3.connect(root/'forbidden-quality.db'),
                  lambda: open(root/'.env','r')]:
    try: operation()
    except PermissionError: pass
    else: raise AssertionError('guard did not deny operation')
with sqlite3.connect(temporary/'allowed.db') as connection:
    connection.execute('create table test(value integer)')
'''
            result=subprocess.run([sys.executable,'-B','-c',script,str(gate.ROOT/'tools'),str(gate.ROOT),directory],
                env=gate.environment(Path(directory)),capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_node_guard_blocks_connection(self):
        with TemporaryDirectory() as directory:
            result=subprocess.run([gate.shutil.which('node'),'--require',str(gate.ROOT/'tools/quality_node.cjs'),
                '-e',"try {require('net').connect(443,'203.0.113.1');process.exit(2)} catch(e) {if(!e.message.includes('Offline'))process.exit(3)}"],
                capture_output=True,timeout=10,env=gate.environment(Path(directory)))
            self.assertEqual(result.returncode,0)


if __name__=='__main__': unittest.main()
