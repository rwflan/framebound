// Real reference-free browser journey with a separate API and parent-agent process.
import {spawn,spawnSync} from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {chromium} from 'playwright';
const ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const WORK=fs.mkdtempSync(path.join(os.tmpdir(),'framebound-agent-browser-'));
const PROJECT=path.join(WORK,'project');fs.mkdirSync(PROJECT);
const PORT=process.env.E2E_PORT||'8781',BASE=`http://127.0.0.1:${PORT}`;
const PY=process.env.PYTHON||'python',ENV={...process.env,PYTHONPATH:[ROOT,path.join(ROOT,'tests'),process.env.PYTHONPATH||''].filter(Boolean).join(path.delimiter)};
function python(code,args=[]){const r=spawnSync(PY,['-c',code,...args],{cwd:ROOT,env:ENV,encoding:'utf8'});assert.equal(r.status,0,r.stderr);return r.stdout;}
python(`from pathlib import Path
from test_agent_loop import setup,import_frames
from framebound.v3.services import loop,tasks
import sys
project,spec,good=setup(Path(sys.argv[1]))
bad=import_frames(Path(project),'bad',{'kind':'flicker'})
loop.submit(project,'run','base',bad)
spec['id']='clean-task';spec['animation_id']='clean'
tasks.create(project,spec);loop.start(project,'clean-task','clean-run');loop.submit(project,'clean-run','clean-result',good)
`,[PROJECT]);
const server=spawn(PY,['-c',`import sys,uvicorn;from framebound.v2.api.app import create_app;uvicorn.run(create_app(sys.argv[1]),host='127.0.0.1',port=int(sys.argv[2]))`,PROJECT,PORT],{cwd:ROOT,env:ENV,stdio:['ignore','pipe','pipe']});
let serverLog='';server.stderr.on('data',d=>serverLog+=d);
const wait=ms=>new Promise(r=>setTimeout(r,ms));
let browser;
try{
  for(let i=0;i<100;i++){try{if((await fetch(BASE+'/api/health')).ok)break;}catch{}if(i===99)throw Error(serverLog);await wait(100);}
  browser=await chromium.launch({headless:true});
  const context=await browser.newContext({viewport:{width:1440,height:1000},permissions:['clipboard-read','clipboard-write']});
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.goto(BASE+'/#/run/run?revision=base');
  await page.locator('[data-revision="base"]').waitFor();
  assert.equal(await page.getByRole('status',{name:'Inspected frame'}).innerText(),'Frame 2 / 3');
  assert.equal(await page.getByRole('img',{name:/Reference/}).count(),0);
  assert.equal(await page.getByRole('button',{name:'Interventions 0'}).count(),1);
  assert.equal(await page.getByLabel('Intervention queue').getByText('clean').count(),0);
  await page.getByRole('button',{name:'correction',exact:true}).click();
  await page.getByLabel('Desired correction').fill('Restore green costume. Preserve every other pixel.');
  const canvas=page.getByLabel('Mark correction region');const rect=await canvas.boundingBox();assert(rect);
  await page.mouse.move(rect.x+rect.width*2.1/8,rect.y+rect.height*3.1/8);
  await page.mouse.down();await page.mouse.move(rect.x+rect.width*4.1/8,rect.y+rect.height*3.8/8);await page.mouse.up();
  await page.getByRole('checkbox',{name:'Authorize edits only within this range/region'}).check();
  // A late store update must not discard unsaved text/ROI or steal inspection.
  python(`from framebound.v3.services import interventions as I;from framebound.v2.services.authz import Actor;import sys;I.agent_satisfied(sys.argv[1],Actor(type='orchestrator',id='browser-test'),'run',revision_id='base',evaluation_id='evaluation:base',note='fixture judgment only')`,[PROJECT]);
  await wait(2300);
  assert.equal(await page.getByLabel('Desired correction').inputValue(),'Restore green costume. Preserve every other pixel.');
  assert.equal(await page.getByRole('status',{name:'Inspected frame'}).innerText(),'Frame 2 / 3');
  assert.equal(await page.locator('.region-box').count(),1);
  await page.getByRole('button',{name:'Save correction',exact:true}).click();
  const handoff=page.locator('[aria-label="Saved action instructions"]');
  await handoff.getByRole('button',{name:'Copy instructions'}).waitFor();
  await handoff.getByRole('button',{name:'Copy instructions'}).click();
  await handoff.getByText('Copied',{exact:true}).waitFor();
  const clipboard=await page.evaluate(()=>navigator.clipboard.readText());
  assert.match(clipboard,/Restore green costume/);assert.match(clipboard,/ticks \[2, 5\)/);assert.match(clipboard,/sha256/);
  const run=await (await fetch(BASE+'/v3/runs/run')).json();
  const feedback=run.feedback;
  assert(feedback.id.startsWith('handoff:'));
  const mark=(await (await fetch(BASE+'/v3/desk')).json()).runs.find(r=>r.id==='run').interventions[0];
  assert.deepEqual(mark.roi,{left:2,top:3,right:5,bottom:4});assert.deepEqual(mark.tick_range,[2,5]);
  assert.equal(mark.authorize_edit_scope,true);
  const download=await Promise.all([page.waitForEvent('download'),handoff.getByRole('link',{name:'Download text'}).click()]);
  const file=await download[0].path();assert.equal(fs.readFileSync(file,'utf8'),clipboard);
  const submission=path.join(WORK,'submit.json');fs.writeFileSync(submission,JSON.stringify({run_id:'run',revision_id:'fixed',parent_revision_id:'base',feedback_id:feedback.id,frame_asset_ids:['good-0','good-1','good-2']}));
  python(`import subprocess,sys;subprocess.run([sys.executable,'-m','framebound','agent-run-submit','--project',sys.argv[1],'--submission',sys.argv[2]],check=True)`,[PROJECT,submission]);
  await wait(2300);
  assert.equal(await page.locator('[data-revision="base"]').count(),1,'live update stole selected revision');
  await page.getByRole('button',{name:'Open current'}).click();
  await page.locator('[data-revision="fixed"]').waitFor();
  await page.getByRole('button',{name:'Resolve',exact:true}).click();
  await page.getByRole('button',{name:'Reopen',exact:true}).waitFor();
  assert.equal((await (await fetch(BASE+'/v3/runs/run')).json()).lifecycle,'completed');
  await page.getByRole('button',{name:'Reopen',exact:true}).click();
  await wait(1800);
  assert.equal((await (await fetch(BASE+'/v3/runs/run')).json()).lifecycle,'awaiting_decision');
  await page.getByRole('button',{name:'Timeline',exact:true}).click();
  const timeline=page.getByLabel('Project timeline');await timeline.getByRole('button',{name:'evaluated base',exact:true}).click();
  await page.locator('[data-revision="base"]').waitFor();
  assert.equal(await page.getByText('Historical revision',{exact:true}).count(),1);
  await page.getByRole('button',{name:'Open current'}).click();await page.locator('[data-revision="fixed"]').waitFor();
  await page.getByRole('button',{name:'Compare previous',exact:true}).click();
  await page.getByRole('button',{name:'Previous revision, frame 1',exact:true}).waitFor();
  await page.getByRole('button',{name:'Compare previous',exact:true}).click();
  assert.equal(await page.getByRole('button',{name:'Previous revision, frame 1',exact:true}).count(),0);
  const inspected=await page.getByRole('status',{name:'Inspected frame'}).innerText();
  await page.getByRole('button',{name:'Play',exact:true}).click();await wait(500);
  assert.equal(await page.getByRole('status',{name:'Inspected frame'}).innerText(),inspected,'inspector chased playback');
  assert.equal(await page.getByLabel('Main playback').count(),1);
  assert.equal(await page.getByLabel('Main playback').getByRole('img').count(),1);
  await page.getByRole('button',{name:'Pause',exact:true}).click();await page.getByRole('button',{name:'Film',exact:true}).click();
  // Force clipboard failure and ensure select/download fallback exposes the same durable text.
  await page.evaluate(()=>Object.defineProperty(navigator.clipboard,'writeText',{value:async()=>{throw Error('clipboard disabled');}}));
  const copy=page.getByRole('button',{name:'Copy instructions'}).first();await copy.click();
  await page.getByLabel('Saved instructions').first().waitFor();
  assert((await page.getByLabel('Saved instructions').first().inputValue()).includes('fixed'));
  await page.setViewportSize({width:760,height:900});
  await page.getByRole('button',{name:'Zoom in',exact:true}).click();
  await page.getByRole('button',{name:'Zoom out',exact:true}).click();
  assert.equal(await page.getByRole('button',{name:'Play',exact:true}).count(),1);
  await page.setViewportSize({width:1440,height:1000});
  await page.getByRole('link',{name:'Export training data',exact:true}).click();
  await page.getByRole('heading',{name:'Export training data',exact:true}).waitFor();
  const selections=page.locator('.agent-export-selection input[type=checkbox]');
  for(let i=0;i<await selections.count();i++)await selections.nth(i).check();
  await page.getByLabel('Snapshot name').fill('browser-training');
  const snapshot=path.join(WORK,'browser-snapshot');
  await page.getByLabel('Export destination').fill(snapshot);
  await page.getByRole('checkbox',{name:'Include automatically verified examples in their separate view'}).check();
  await page.getByRole('checkbox',{name:'Include procedural fixtures as labeled training examples'}).check();
  await page.getByRole('button',{name:'Preview export',exact:true}).click();
  await page.getByLabel('Export preview').waitFor();
  await page.getByRole('button',{name:'Export snapshot',exact:true}).click();
  await page.getByText('Snapshot validated',{exact:true}).waitFor();
  const manifest=JSON.parse(fs.readFileSync(path.join(snapshot,'manifest.json'),'utf8'));
  assert.equal(manifest.counts.positives,0);
  assert.equal(manifest.counts.automatically_verified,3);
  assert.equal(manifest.counts.preferences,0);
  const moved=path.join(WORK,'moved-snapshot');fs.renameSync(snapshot,moved);
  const validated=JSON.parse(python(`import json,sys;from framebound.v2.exports import validate_snapshot;result=validate_snapshot(sys.argv[1]);assert result['ok'],result['issues'];print(json.dumps(result))`,[moved]).split('\n').filter(l=>l.startsWith('{')).at(-1));
  assert(validated.ok);
  fs.mkdirSync(path.join(ROOT,'output/playwright'),{recursive:true});
  await page.screenshot({path:path.join(ROOT,'output/playwright/agent-workflow.png')});
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({ok:true,work:WORK,checks:['native-markup','saved-copy-download','live-stability','fresh-process-repair','owner-resolve-reopen','timeline-exact-revision','conditional-comparison','stable-playback','clipboard-fallback','manual-export-preview','moved-snapshot-validation']}));
}finally{if(browser)await browser.close();server.kill('SIGTERM');}
