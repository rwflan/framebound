// Real reviewer/API regression with disposable credentials; no provider traffic.
// PYTHON=/path/to/python node e2e/training-journey.mjs (after npm run build)
import {spawn,spawnSync} from 'node:child_process';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import net from 'node:net';
import {fileURLToPath} from 'node:url';import assert from 'node:assert/strict';import {chromium} from 'playwright';
const ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..'),WORK=fs.mkdtempSync(path.join(os.tmpdir(),'framebound-training-browser-'));
const PROJECT=path.join(WORK,'project'),PRIVATE=path.join(WORK,'private');fs.mkdirSync(PROJECT);
const PY=process.env.PYTHON||'python',ENV={...process.env,FRAMEBOUND_TRAINING_HOME:PRIVATE,PYTHONPATH:[ROOT,path.join(ROOT,'tests'),process.env.PYTHONPATH||''].filter(Boolean).join(path.delimiter)};
const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));
const BASE=`http://127.0.0.1:${port}`,KEYS={meta_api_key:'browser-test-meta-secret',modal_token_id:'browser-test-modal-id',modal_token_secret:'browser-test-modal-secret'};
const fixture=spawnSync(PY,['-c',`from pathlib import Path
from test_agent_loop import setup
from framebound.v3.services import tasks,loop
import sys
project,spec,good=setup(Path(sys.argv[1]));loop.submit(project,'run','browser-result',good)
`,PROJECT],{cwd:ROOT,env:ENV,encoding:'utf8'});assert.equal(fixture.status,0,fixture.stderr);
// Test-only injection in this server: the real worker stops before any paid POST.
const server=spawn(PY,['-c',`import sys,uvicorn
from framebound.v3.services import training
from framebound.v2.api.app import create_app
def offline_account(_):raise RuntimeError('Offline browser account fixture')
training.account_evidence=offline_account
uvicorn.run(create_app(sys.argv[1]),host='127.0.0.1',port=int(sys.argv[2]))`,PROJECT,String(port)],{cwd:ROOT,env:ENV,stdio:['ignore','pipe','pipe']});
let log='';server.stderr.on('data',d=>log+=d);const wait=ms=>new Promise(r=>setTimeout(r,ms));let browser;
try{
 for(let i=0;i<100;i++){try{if((await fetch(BASE+'/api/health')).ok)break;}catch{}if(i===99)throw Error(log);await wait(100);}
 assert.equal((await fetch(BASE+'/v3/settings/providers',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(KEYS)})).status,403);
 browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],responseTexts=[];page.setDefaultTimeout(15000);page.on('pageerror',e=>errors.push(String(e)));
 page.on('response',r=>{if(/\/v3\/(settings\/providers|training)/.test(r.url()))r.text().then(text=>responseTexts.push(text)).catch(()=>{});});
 await page.goto(BASE+'/#/settings');await page.getByText('Connect your tools.',{exact:true}).waitFor();
 const meta=page.locator('.connection-card').filter({has:page.getByRole('heading',{name:'Meta Model API',exact:true})}),modal=page.locator('.connection-card').filter({has:page.getByRole('heading',{name:'Modal',exact:true})});
 await meta.getByLabel('API key',{exact:true}).fill(KEYS.meta_api_key);await meta.getByRole('button',{name:'Save key',exact:true}).click();await meta.getByText('Configured',{exact:true}).waitFor();assert.equal(await meta.getByLabel('API key',{exact:true}).inputValue(),'');
 await modal.getByLabel('Token ID',{exact:true}).fill(KEYS.modal_token_id);await modal.getByLabel('Token secret',{exact:true}).fill(KEYS.modal_token_secret);await modal.getByRole('button',{name:'Save token',exact:true}).click();await modal.getByText('Configured',{exact:true}).waitFor();assert.equal(await modal.getByLabel('Token secret',{exact:true}).inputValue(),'');
 await page.reload();await page.getByText('Connect your tools.',{exact:true}).waitFor();await page.getByText('Configured',{exact:true}).first().waitFor();assert.equal(await page.getByText('Configured',{exact:true}).count(),2);
 const storage=await page.evaluate(()=>JSON.stringify({local:{...localStorage},session:{...sessionStorage}}));for(const v of Object.values(KEYS))assert(!storage.includes(v));
 await page.getByRole('link',{name:'Continue to model training'}).click();await page.getByRole('button',{name:'Choose your model'}).click();await page.getByLabel('Model name',{exact:true}).fill('Browser motion model');await page.getByRole('radio',{name:/Motion/}).check();await page.getByLabel('Maximum Meta spend (USD)',{exact:true}).fill('5');await page.getByRole('button',{name:'Review setup'}).click();
 const start=page.getByRole('button',{name:'Start collecting',exact:true});assert.equal(await start.isEnabled(),false);await page.getByRole('checkbox').check();await start.dblclick();await page.getByText('Your model, taking shape.',{exact:true}).waitFor();await page.getByText('This run needs attention',{exact:true}).waitFor();
 const listing=await(await fetch(BASE+'/v3/training')).json();assert.equal(listing.runs.length,1,'Duplicate run created');const run=listing.runs[0];assert.equal(run.name,'Browser motion model');assert.equal(run.focus,'motion');assert.equal(run.budget_dollars,5);assert.equal(run.status,'blocked');assert.equal(run.spent_dollars,0);assert.equal(run.reserved_dollars,0);
 const replay=await page.evaluate(async config=>{const r=await fetch('/v3/training',{method:'POST',headers:{'Content-Type':'application/json','X-Framebound-Desk':'1'},body:JSON.stringify(config)});return{status:r.status,body:await r.json()};},{id:run.id,name:run.name,focus:run.focus,budget_dollars:5});assert.equal(replay.status,200);assert.equal(replay.body.id,run.id);
 const conflict=await page.evaluate(async config=>(await fetch('/v3/training',{method:'POST',headers:{'Content-Type':'application/json','X-Framebound-Desk':'1'},body:JSON.stringify(config)})).status,{id:run.id,name:run.name,focus:run.focus,budget_dollars:6});assert.equal(conflict,422);
 await page.reload();await page.getByText('Browser motion model',{exact:true}).waitFor();await page.setViewportSize({width:650,height:850});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await wait(100);assert(responseTexts.length>=4,'Expected settings and journey responses');for(const text of responseTexts)for(const v of Object.values(KEYS))assert(!text.includes(v),'Credential echoed in API response');assert.deepEqual(errors,[]);
 const directory=fs.readdirSync(PRIVATE).map(n=>path.join(PRIVATE,n)).find(p=>fs.statSync(p).isDirectory());assert(directory);assert.equal(fs.statSync(path.join(directory,'providers.json')).mode&0o777,0o600);assert.deepEqual(JSON.parse(fs.readFileSync(path.join(directory,'providers.json'),'utf8')),KEYS);assert.equal(fs.existsSync(path.join(directory,'data')),false,'Offline account failure admitted paid collection');
 console.log('PASS real training journey: reviewer authorization, credential persistence/redaction, spend consent, setup idempotency, blocked offline start, responsive layout; zero paid calls.');
}finally{await browser?.close();server.kill('SIGTERM');if(server.exitCode===null)await new Promise(r=>server.once('exit',r));fs.rmSync(WORK,{recursive:true,force:true});}
