"""The actual fixed JS adapter permits only one unacknowledged original write."""

import os
import subprocess
from pathlib import Path
import pytest
from tools.quality_gate import environment
from tools.windows_backend_package import _replace_owned_build_file


@pytest.mark.skipif(
    not Path(
        'backend/distributions/windows/check-browser-20261114-1557-backpressure/vendor/playwright/driver/node.exe'
    ).is_file(),
    reason='Explicit fixed Node runtime required',
)
def test_fixed_js_adapter_waits_for_exact_original_write_ack(tmp_path):
    root = Path(__file__).resolve().parents[3]
    node = (
        root
        / 'backend/distributions/windows/check-browser-20261114-1557-backpressure/vendor/playwright/driver/node.exe'
    )
    folder = tmp_path / 'fixed-sdk-fixture'
    (folder / 'lib/server/utils').mkdir(parents=True)
    _replace_owned_build_file(folder / 'lib/server/utils/processLauncher.js', b'module.exports={};')
    source = "'use strict';\nconst assert=require('assert');\nconst path=require('path');\nconst [modulePath,folder]=process.argv.slice(1);\nconst frames=[];\nconst api=require(modulePath).install(folder,value=>frames.push(value),()=>7);\nconst launch=require(path.join(folder,'lib/server/utils/processLauncher.js')).launchProcess({\n command:'fixed-fixture',args:[],stdio:'pipe',log(){},onExit(){},tempDirectories:[],\n attemptToGracefullyClose:async()=>{}\n});\nassert.equal(frames.shift().event,'BROWSER_START');\napi.receive('BROWSER_STARTED',{browser:1,epoch:7,pid:123});\nlaunch.then(async original=>{\n const body=Buffer.alloc(100000,120);\n let complete=false;\n original.launchedProcess.stdio[3].write(body,()=>{complete=true;});\n assert.equal(frames.length,1);\n assert.equal(complete,false);\n assert.throws(()=>api.receive('BROWSER_WRITTEN',{browser:1,epoch:7,write:2}),/WRITE_ACK_REQUIRED/);\n assert.throws(()=>api.receive('BROWSER_WRITTEN',{browser:1,epoch:7,write:true}),/WRITE_ACK_REQUIRED/);\n const chunks=[];\n let sequence=1;\n while(frames.length){\n  const frame=frames.shift();\n  assert.equal(frame.event,'BROWSER_WRITE');\n  assert.equal(frame.write,sequence);\n  chunks.push(Buffer.from(frame.data,'base64'));\n  assert.equal(frames.length,0);\n  api.receive('BROWSER_WRITTEN',{browser:1,epoch:7,write:sequence});\n  sequence++;\n }\n await new Promise(resolve=>setImmediate(resolve));\n assert.equal(complete,true);\n assert.deepEqual(Buffer.concat(chunks),body);\n assert.throws(()=>api.receive('BROWSER_WRITTEN',{browser:1,epoch:7,write:sequence-1}),/WRITE_ACK_REQUIRED/);\n console.log('ORIGINAL_BROWSER_BACKPRESSURE_AND_ACK_CHECKED',chunks.length);\n}).catch(error=>{console.error(error);process.exitCode=1;});\n"
    result = subprocess.run(
        [
            str(node),
            '--preserve-symlinks',
            '--preserve-symlinks-main',
            '-e',
            source,
            str(root / 'backend/app/infrastructure/check_driver_browser_broker.cjs'),
            str(folder),
        ],
        env=environment(tmp_path),
        cwd=tmp_path,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr.decode('utf-8', 'replace')[:2000]
    assert b'ORIGINAL_BROWSER_BACKPRESSURE_AND_ACK_CHECKED 4' in result.stdout
