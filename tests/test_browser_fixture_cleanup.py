"""Browser setup failures must release the owned localhost fixture listener."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize('failure', ['launch', 'context', 'close'])
def test_failed_browser_setup_closes_listener_and_preserves_error(tmp_path, failure):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is unavailable; the isolated CI image includes it')
    stub = tmp_path / 'browser.cjs'
    stub.write_text("module.exports={chromium:{async launch(){" +
        ("throw Error('launch failure');" if failure == 'launch' else
         "return {async newContext(){throw Error('context failure');},async close(){" +
         ("throw Error('close failure');" if failure == 'close' else "") + "}};") + "}}};")
    fixture = Path(__file__).parent / 'frontend/performance-fixture.cjs'
    code = """
const assert=require('node:assert/strict');
const http=require('node:http');
const original=http.createServer, servers=[];
http.createServer=(...args)=>{const s=original(...args);servers.push(s);return s;};
const {fixture}=require(process.argv[1]);
(async()=>{
  await assert.rejects(fixture(), /launch failure|context failure/);
  assert.equal(servers.length,1);
  assert.equal(servers[0].listening,false);
  assert.equal(servers[0].address(),null);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run([node, '-e', code, str(fixture.resolve())],
        env=dict(os.environ, ROYAL_PLAYWRIGHT=str(stub)),
        capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
