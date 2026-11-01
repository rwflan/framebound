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
from test_source_correspondence import source_task
_,source_spec,source_candidate=source_task(Path(project))
tasks.create(project,source_spec);loop.start(project,'enhance','enhancement-run');loop.submit(project,'enhancement-run','enhanced',source_candidate)
`,[PROJECT]);
const server=spawn(PY,['-c',`import sys,uvicorn;from framebound.v2.api.app import create_app;uvicorn.run(create_app(sys.argv[1]),host='127.0.0.1',port=int(sys.argv[2]))`,PROJECT,PORT],{cwd:ROOT,env:ENV,stdio:['ignore','pipe','pipe']});
let serverLog='';server.stderr.on('data',d=>serverLog+=d);
const wait=ms=>new Promise(r=>setTimeout(r,ms));
let browser,page;
try{
  for(let i=0;i<100;i++){try{if((await fetch(BASE+'/api/health')).ok)break;}catch{}if(i===99)throw Error(serverLog);await wait(100);}
  browser=await chromium.launch({headless:true});
  const context=await browser.newContext({viewport:{width:1440,height:1000},permissions:['clipboard-read','clipboard-write']});
  page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.goto(BASE+'/#/run/run?revision=base');
  await page.locator('[data-revision="base"]').waitFor();
  assert.equal(await page.locator('.agent-inspector .inspector-heading strong').innerText(),'Frame 2');
  assert.equal(await page.getByRole('img',{name:/Reference/}).count(),0);
  assert.equal(await page.getByRole('button',{name:'Interventions 1'}).count(),1);
  assert.equal(await page.getByLabel('Intervention queue').getByText('clean').count(),0);
  await page.locator('.agent-inspector-tabs').getByRole('button',{name:'Feedback',exact:true}).click();
  await page.getByLabel('Desired correction').fill('Restore green costume. Preserve every other pixel.');
  await page.getByText('Edit scope and timing',{exact:true}).click();
  const canvas=page.getByLabel('Mark correction region');const rect=await canvas.boundingBox();assert(rect);
  await page.mouse.move(rect.x+rect.width*2.1/8,rect.y+rect.height*3.1/8);
  await page.mouse.down();await page.mouse.move(rect.x+rect.width*4.1/8,rect.y+rect.height*3.8/8);await page.mouse.up();
  await page.getByRole('checkbox',{name:'Authorize edits only within this range/region'}).check();
  // A late store update must not discard unsaved text/ROI or steal inspection.
  python(`from framebound.v3.services import interventions as I;from framebound.v2.services.authz import Actor;import sys;I.agent_satisfied(sys.argv[1],Actor(type='orchestrator',id='browser-test'),'run',revision_id='base',evaluation_id='evaluation:base',note='fixture judgment only')`,[PROJECT]);
  await wait(2300);
  assert.equal(await page.getByLabel('Desired correction').inputValue(),'Restore green costume. Preserve every other pixel.');
  assert.equal(await page.locator('.agent-inspector .inspector-heading strong').innerText(),'Frame 2');
  assert.equal(await page.locator('.region-box').count(),1);
  await page.getByText('Advanced: scoped agent correction',{exact:true}).click();
  await page.getByRole('button',{name:'Save correction for external agent',exact:true}).click();
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
  const portableDownload=await Promise.all([page.waitForEvent('download'),handoff.getByRole('link',{name:'Download portable handoff',exact:true}).click()]);
  const packagePath=await portableDownload[0].path(),external=path.join(WORK,'external-agent');
  python(`import json,sys,zipfile
from pathlib import Path
from PIL import Image
root=Path(sys.argv[2]);root.mkdir()
with zipfile.ZipFile(sys.argv[1]) as archive:archive.extractall(root)
manifest=json.loads((root/'manifest.json').read_text())
baseline=manifest['revisions']['base']['frame_asset_ids']
image=Image.open(root/manifest['assets'][baseline[1]]['file']).convert('RGBA')
image.putpixel((3,3),(0,255,0,255));image.save(root/'repair.png')
response=dict(revision_id='fixed',frames=[dict(asset_id=baseline[0]),dict(file='repair.png',rights='original',source_kind='procedural'),dict(asset_id=baseline[2])],generation_metadata=None)
(root/'response.json').write_text(json.dumps(response))
`,[packagePath,external]);
  python(`import subprocess,sys;subprocess.run([sys.executable,'-m','framebound','agent-handoff-import','--project',sys.argv[1],'--manifest',sys.argv[2],'--response',sys.argv[3]],check=True)`,[PROJECT,path.join(external,'manifest.json'),path.join(external,'response.json')]);
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
  await page.getByLabel('Timeline view').selectOption('all');
  const timeline=page.getByLabel('Project timeline');await timeline.getByRole('button',{name:'evaluated base',exact:true}).click();
  await page.locator('[data-revision="base"]').waitFor();
  assert.equal(await page.getByText('Historical revision',{exact:true}).count(),1);
  await page.getByRole('button',{name:'Open current'}).click();await page.locator('[data-revision="fixed"]').waitFor();
  await page.getByRole('button',{name:'Compare previous',exact:true}).click();
  await page.getByRole('button',{name:'Inspect previous revision playback frame 1',exact:true}).waitFor();
  // An explicit comparison choice is different from ordinary approval or newer-revision order.
  await page.getByRole('button',{name:'Resolve',exact:true}).click();
  await page.getByRole('button',{name:'Reopen',exact:true}).waitFor();
  await page.getByRole('button',{name:'decision',exact:true}).click();
  await page.getByRole('checkbox',{name:'Explicitly prefer this revision over base'}).check();
  await page.getByLabel('Decision note').fill('Explicitly prefer the restored costume over the previous flicker.');
  await page.getByRole('button',{name:'approve',exact:true}).click();
  await wait(1800);
  assert.equal((await (await fetch(BASE+'/v3/runs/run')).json()).creative_status,'human_approved');
  await page.getByRole('button',{name:'evidence',exact:true}).click();
  await page.getByRole('button',{name:'Compare previous',exact:true}).click();
  assert.equal(await page.getByRole('button',{name:'Inspect previous revision playback frame 1',exact:true}).count(),0);
  const inspected=await page.locator('.agent-inspector .inspector-heading strong').innerText();
  await page.getByRole('button',{name:'Play',exact:true}).click();await wait(500);
  assert.equal(await page.locator('.agent-inspector .inspector-heading strong').innerText(),inspected,'inspector chased playback');
  assert.equal(await page.locator('.projector-screen').count(),1);
  assert.equal(await page.locator('.projector-screen').getByRole('img').count(),1);
  await page.getByRole('button',{name:'Pause',exact:true}).click();
  // Force clipboard failure and ensure select/download fallback exposes the same durable text.
  await page.evaluate(()=>Object.defineProperty(navigator.clipboard,'writeText',{value:async()=>{throw Error('clipboard disabled');}}));
  const copy=handoff.getByRole('button',{name:'Copy instructions'});await copy.click();
  await handoff.getByLabel('Saved instructions').waitFor();
  assert((await handoff.getByLabel('Saved instructions').inputValue()).includes('fixed'));
  await page.setViewportSize({width:760,height:900});
  await page.getByRole('button',{name:'Zoom in',exact:true}).click();
  await page.getByRole('button',{name:'Zoom out',exact:true}).click();
  assert.equal(await page.getByRole('button',{name:'Play',exact:true}).count(),1);
  await page.setViewportSize({width:1440,height:1000});
  await page.goto(BASE+'/#/run/enhancement-run?revision=enhanced');
  await page.locator('[data-revision="enhanced"]').waitFor();
  assert.equal(await page.getByRole('button',{name:/Inspect candidate playback frame /}).count(),6);
  assert.equal(await page.getByRole('button',{name:/Inspect known-good source playback frame /}).count(),0);
  await page.getByRole('button',{name:'Compare known-good source',exact:true}).click();
  const mapped=page.getByRole('button',{name:'Inspect known-good source playback frame 4',exact:true});
  assert((await mapped.locator('img').getAttribute('src')).endsWith('/source-1'));
  const enhanced=await fetch(BASE+'/v3/desk/revisions/enhanced').then(r=>r.json());
  assert.equal(enhanced.source_comparison.frames[3].correspondence,'source_motion_interval');
  await page.getByRole('button',{name:'Inspect candidate playback frame 4',exact:true}).click();
  assert.equal(await page.getByText('source motion interval · source frame 2',{exact:false}).count(),1);
  await page.getByRole('button',{name:'Play',exact:true}).click();
  for(let sample=0;sample<5;sample++){
    const shown=await page.locator('.projector-screen').locator('img').evaluateAll(images=>images.map(im=>im.getAttribute('src')));
    assert.equal(shown.length,2);
    const index=Number(shown[1].split('candidate-')[1]);
    assert(shown[0].endsWith('/source-'+Math.floor(index/2)),'source playback used output array index instead of authored time');
    await wait(40);
  }
  await page.getByRole('button',{name:'Pause',exact:true}).click();
  await page.getByRole('button',{name:'Compare known-good source',exact:true}).click();
  assert.equal(await page.getByRole('button',{name:/Inspect known-good source playback frame /}).count(),0);
  await page.getByLabel('More workspaces').click();
  await page.getByRole('navigation',{name:'Workspace tools'}).getByRole('link',{name:/Export/}).click();
  await page.getByRole('heading',{name:'Export',exact:true}).waitFor();
  const selections=page.locator('.utility-run-list input[type=checkbox]');
  for(let i=0;i<await selections.count();i++)await selections.nth(i).check();
  await page.getByLabel('Snapshot name').fill('browser-training');
  const snapshot=path.join(WORK,'browser-snapshot');
  await page.getByLabel('Export destination').fill(snapshot);
  await page.getByText('Optional dataset views',{exact:true}).click();
  await page.getByRole('checkbox',{name:'Include automatically verified examples in a separate view'}).check();
  await page.getByRole('checkbox',{name:'Include labelled procedural fixtures'}).check();
  await page.getByRole('button',{name:'Preview export',exact:true}).click();
  await page.getByLabel('Export preview').waitFor();
  await page.getByRole('button',{name:'Export snapshot',exact:true}).click();
  await page.getByText('Snapshot validated',{exact:true}).waitFor();
  const manifest=JSON.parse(fs.readFileSync(path.join(snapshot,'manifest.json'),'utf8'));
  assert.equal(manifest.counts.positives,3);
  assert.equal(manifest.counts.automatically_verified,9);
  assert.equal(manifest.counts.preferences,1);
  const moved=path.join(WORK,'moved-snapshot');fs.renameSync(snapshot,moved);
  const validated=JSON.parse(python(`import json,sys;from framebound.v2.exports import validate_snapshot;result=validate_snapshot(sys.argv[1]);assert result['ok'],result['issues'];print(json.dumps(result))`,[moved]).split('\n').filter(l=>l.startsWith('{')).at(-1));
  assert(validated.ok);
  // Before pixels exist, a durable parent-reported failure still has a usable handoff.
  python(`import sys
from framebound.v3.services import tasks,loop,failures
project=sys.argv[1];spec=tasks.get(project,'task')['spec'];spec.update(id='pending-task',animation_id='pending')
tasks.create(project,spec);loop.start(project,'pending-task','pending-run')
failures.record(project,'pending-run',dict(id='attempt-1',kind='tool_error',reason='External tool unavailable before generating frames.',outcome_known=True))
`,[PROJECT]);
  await page.goto(BASE+'/#/run/pending-run');
  await page.getByRole('main').getByText('External tool unavailable before generating frames.',{exact:true}).waitFor();
  await page.getByRole('button',{name:'View instructions',exact:true}).click();
  assert.match(await page.getByLabel('Saved instructions').inputValue(),/No candidate has been registered/);
  assert.equal(await page.getByRole('link',{name:'Download portable handoff',exact:true}).count(),0);
  const initialText=await fetch(BASE+'/v3/runs/pending-run').then(r=>r.json());
  const initialDownload=await fetch(BASE+'/v3/feedback/'+encodeURIComponent(initialText.feedback_id)+'/text').then(r=>r.text());
  assert.equal(await page.getByLabel('Saved instructions').inputValue(),initialDownload);
  python(`import sys
from framebound.v3.services import failures
failures.record(sys.argv[1],'pending-run',dict(id='attempt-2',kind='provider_failure',reason='External provider outcome is unknown.',outcome_known=False))
`,[PROJECT]);
  await page.getByText(/Unknown parent-reported provider outcome/).first().waitFor();
  await page.getByRole('button',{name:'View instructions',exact:true}).click();
  assert.match(await page.getByLabel('Saved instructions').inputValue(),/This run is stopped/);
  fs.mkdirSync(path.join(ROOT,'output/playwright'),{recursive:true});
  await page.screenshot({path:path.join(ROOT,'output/playwright/agent-workflow.png')});
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({ok:true,work:WORK,checks:['native-markup','portable-offline-handoff','explicit-human-preference','saved-copy-download','live-stability','fresh-process-repair','owner-resolve-reopen','timeline-exact-revision','conditional-comparison','stable-playback','clipboard-fallback','manual-export-preview','moved-snapshot-validation','known-good-authored-time-comparison','pre-submission-failure-handoff','unknown-provider-stop']}));
}catch(error){
  if(page){await page.screenshot({path:path.join(WORK,'failure.png')}).catch(()=>{});fs.writeFileSync(path.join(WORK,'failure.html'),await page.content().catch(()=>''));}
  console.error('Agent browser failure artifacts:',WORK);throw error;
}finally{if(browser)await browser.close();server.kill('SIGTERM');}
