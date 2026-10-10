const {chromium}=require('playwright');const fs=require('fs');const base=process.env.BASE_URL||'http://127.0.0.1:8080';fs.mkdirSync('.artifacts',{recursive:true});
(async()=>{const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'/usr/bin/google-chrome',headless:true,...(process.env.BROWSER_PROXY?{proxy:{server:process.env.BROWSER_PROXY}}:{}),args:['--no-sandbox']});const context=await browser.newContext({viewport:{width:1440,height:1000}});const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(String(e)));page.on('response',r=>{if(r.status()>=400)errors.push(r.status()+' '+r.url())});
await page.goto(base+'/',{waitUntil:'networkidle'});await page.screenshot({path:'.artifacts/gpt-policy-desktop.png'});
await page.locator('.auxiliary-archive > summary').click();
const dataset=await page.evaluate(async()=>await (await fetch('data/report.json')).json());const expected=dataset.episodes.length;const chunkCount=dataset.episodes.filter(r=>r.method==='pi05_chunk50').length;const fold=dataset.episodes.filter(r=>r.task==='fold_clothes');
const visible=()=>page.locator('.episode:visible').count();if(await visible()!==expected)throw Error('Case count differs from public data');
await page.selectOption('#task-filter','fold_clothes');if(await visible()!==fold.length)throw Error('Task filter');await page.selectOption('#status-filter','success');if(await visible()!==fold.filter(r=>r.status==='success').length)throw Error('Success filter');
await page.getByRole('button',{name:'重置',exact:true}).click();await page.waitForTimeout(100);if(await visible()!==expected)throw Error('Reset');
await page.locator('#case-search').fill('missing-case-xyz');if(await visible()!==0||!await page.locator('#empty-state').isVisible())throw Error('Empty filter');await page.locator('#case-search').fill('');
await page.locator('#show-chunk50').click();if(await visible()!==chunkCount)throw Error('Chunk filter');
const video=page.locator('.episode:visible video').first();await video.evaluate(async v=>{v.muted=true;await v.play()});await page.waitForTimeout(1800);const media=await video.evaluate(v=>({time:v.currentTime,duration:v.duration,width:v.videoWidth,height:v.videoHeight}));if(!(media.time>0&&media.width===1440))throw Error('Playback failed '+JSON.stringify(media));await video.evaluate(v=>v.pause());await page.screenshot({path:'.artifacts/gpt-policy-playback.png'});
await page.locator('.seed.success').first().click();if(await visible()!==expected)throw Error('Seed deep link reset');if(!page.url().includes('#pi05_prefix15'))throw Error('Deep link');
const beforeTheme=await page.locator('html').getAttribute('data-theme');const afterTheme=beforeTheme==='light'?'dark':'light';await page.locator('#theme-toggle').click();if(await page.locator('html').getAttribute('data-theme')!==afterTheme)throw Error('Theme');await page.reload({waitUntil:'networkidle'});if(await page.locator('html').getAttribute('data-theme')!==afterTheme)throw Error('Theme persistence');await page.locator('#theme-toggle').click();
await page.setViewportSize({width:390,height:844});await page.goto(base+'/scenes.html',{waitUntil:'networkidle'});const dimensions=await page.evaluate(()=>({viewport:innerWidth,scroll:document.documentElement.scrollWidth}));if(dimensions.scroll>dimensions.viewport)throw Error('Mobile overflow '+JSON.stringify(dimensions));await page.screenshot({path:'.artifacts/gpt-policy-mobile.png'});await page.locator('.auxiliary-archive > summary').click();await page.locator('#episodes').scrollIntoViewIfNeeded();await page.screenshot({path:'.artifacts/gpt-policy-mobile-cases.png'});
await page.goto(base+'/robolab.html',{waitUntil:'networkidle'});const rd=await page.evaluate(async()=>await (await fetch('data/robolab-report.json')).json());if(await page.locator('video').count()!==rd.episodes.length)throw Error('RoboLab case count');const rv=page.locator('video').first();await rv.evaluate(async v=>{v.muted=true;await v.play()});await page.waitForTimeout(1500);const rm=await rv.evaluate(v=>({time:v.currentTime,duration:v.duration,width:v.videoWidth,height:v.videoHeight}));if(!(rm.time>0&&rm.width===1440&&Math.abs(rm.duration-rd.episodes[0].duration_seconds)<.1))throw Error('RoboLab playback');await rv.evaluate(v=>v.pause());const rw=await page.evaluate(()=>({viewport:innerWidth,scroll:document.documentElement.scrollWidth}));if(rw.scroll>rw.viewport)throw Error('RoboLab mobile overflow');await page.screenshot({path:'.artifacts/robolab-mobile.png'});await page.setViewportSize({width:1440,height:1000});await page.screenshot({path:'.artifacts/robolab-desktop.png'});
await page.goto(base+'/gpt-methods.html',{waitUntil:'networkidle'});
const gd=await page.evaluate(async()=>await (await fetch('data/gpt-methods-progress.json')).json());
if(gd.schema!=='gpt_policy_progress.v2'||await page.locator('.gpt-episode').count()!==gd.episodes.length)throw Error('GPT audited episode count');
if(await page.locator('#gpt-case-matrix tbody tr').count()!==50)throw Error('GPT frozen matrix');
await page.locator('details:has(#gpt-case-matrix) > summary').click();
const gv=()=>page.locator('.gpt-episode:visible').count();
await page.selectOption('#gpt-method','pi05_plus_gpt');if(await gv()!==gd.episodes.filter(e=>e.method==='pi05_plus_gpt').length)throw Error('GPT method filter');
await page.selectOption('#gpt-method','all');await page.selectOption('#gpt-status','success');if(await gv()!==gd.episodes.filter(e=>e.success).length)throw Error('GPT native result filter');
await page.selectOption('#gpt-status','all');await page.selectOption('#gpt-task','arrange_largest_number');if(await gv()!==gd.episodes.filter(e=>e.identity.task==='arrange_largest_number').length)throw Error('GPT task filter');
await page.locator('#gpt-search').fill('missing-case-xyz');if(await gv()!==0||!await page.locator('#gpt-empty').isVisible())throw Error('GPT empty search');
await page.getByRole('button',{name:'重置',exact:true}).click();await page.waitForTimeout(100);if(await gv()!==gd.episodes.length)throw Error('GPT filter reset');
const gm=[];for(const method of ['gpt_only','pi05_plus_gpt']){
 const episode=gd.episodes.find(e=>e.method===method);const video=page.locator('#'+episode.id+' video');
 await video.evaluate(async v=>{v.muted=true;await v.play()});await page.waitForTimeout(1200);
 const state=await video.evaluate(v=>({time:v.currentTime,duration:v.duration,width:v.videoWidth,height:v.videoHeight}));
 if(!(state.time>0&&state.width===1440&&Math.abs(state.duration-episode.duration_seconds)<.1))throw Error('GPT complete playback '+method);
 await video.evaluate(v=>v.pause());gm.push({method,...state});
}
await page.screenshot({path:'.artifacts/gpt-methods-desktop.png'});
await page.selectOption('#gpt-method','pi05_plus_gpt');const direct=gd.episodes.find(e=>e.method==='gpt_only');
await page.locator('#gpt-case-matrix a[href="#'+direct.id+'"]').click();await page.waitForURL(url=>url.hash==='#'+direct.id);await page.waitForFunction(n=>[...document.querySelectorAll('.gpt-episode')].filter(e=>!e.hidden).length===n,gd.episodes.length);if(await gv()!==gd.episodes.length||!page.url().endsWith('#'+direct.id))throw Error('GPT paired matrix deep link');
await page.locator('#gpt-theme').click();const gt=await page.locator('html').getAttribute('data-theme');await page.reload({waitUntil:'networkidle'});if(await page.locator('html').getAttribute('data-theme')!==gt)throw Error('GPT persisted theme');
await page.setViewportSize({width:390,height:844});await page.goto(base+'/gpt-methods.html',{waitUntil:'networkidle'});
const gw=await page.evaluate(()=>({viewport:innerWidth,scroll:document.documentElement.scrollWidth}));if(gw.scroll>gw.viewport)throw Error('GPT mobile overflow '+JSON.stringify(gw));
await page.screenshot({path:'.artifacts/gpt-methods-mobile.png'});await page.locator('#gpt-rollouts').scrollIntoViewIfNeeded();await page.screenshot({path:'.artifacts/gpt-methods-mobile-rollouts.png'});
await page.goto(base+'/scenes.html',{waitUntil:'networkidle'});const primary=await page.locator('#main-methods').innerText();if(!primary.includes(gd.summary.complete_method_runs+'')||primary.includes('完整可计分主方法回合：0'))throw Error('Primary report counts');
const supplementalCounts=gd.supplementary.robolab.summary;const supplementalStatus=await page.locator('#robolab-infra-progress').innerText();
if(!supplementalStatus.includes(supplementalCounts.complete_method_runs+' / 100 条已完整审计，'+supplementalCounts.completed_pairs+' / 50 对已完成'))throw Error('Infrastructure supplemental counts');
const bounds=await page.evaluate(()=>({primary_precedes_baseline:Boolean(document.querySelector('#main-methods').compareDocumentPosition(document.querySelector('[aria-label="前缀基线关键指标"]'))&Node.DOCUMENT_POSITION_FOLLOWING)}));if(!bounds.primary_precedes_baseline)throw Error('Primary results must precede historical baseline');
await page.goto(base+'/robolab-methods.html',{waitUntil:'networkidle'});
const supplemental=await page.evaluate(async()=>await (await fetch('data/robolab-methods-progress.json')).json());
if(await page.locator('#robolab-methods-matrix tbody tr').count()!==50||await page.locator('video').count()!==supplemental.summary.complete_method_runs)throw Error('RoboLab two-method cohort');
const supplementalMedia=[];for(const method of ['gpt_only','pi05_plus_gpt']){
 const episode=supplemental.episodes.find(e=>e.method===method);if(!episode)continue;
 const proof=await page.evaluate(async path=>await (await fetch(path)).json(),episode.audit);
 if(!(proof.verified&&proof.complete_episode&&proof.scope==='complete_native_episode'&&proof.model==='gpt-6-astra'&&proof.method===method&&proof.native_actions===episode.control_steps&&proof.decisions===episode.decisions&&proof.terminal.success===episode.success&&(method!=='gpt_only'||proof.pi05_inference_calls===0)))throw Error('Supplemental complete evidence '+method);
 const video=page.locator('#'+episode.id+' video');await video.evaluate(async v=>{v.muted=true;await v.play()});await page.waitForTimeout(1200);
 const state=await video.evaluate(v=>({time:v.currentTime,duration:v.duration,width:v.videoWidth,height:v.videoHeight}));
 if(!(state.time>0&&state.width===1440&&Math.abs(state.duration-episode.duration_seconds)<.1))throw Error('Supplemental complete playback '+method);
 await video.evaluate(v=>v.pause());supplementalMedia.push({method,...state});
}
const sw=await page.evaluate(()=>({viewport:innerWidth,scroll:document.documentElement.scrollWidth}));if(sw.scroll>sw.viewport)throw Error('Supplemental mobile overflow');
await page.screenshot({path:'.artifacts/robolab-methods-mobile.png'});await page.setViewportSize({width:1440,height:1000});await page.screenshot({path:'.artifacts/robolab-methods-desktop.png'});
let selectedResult=null;
await page.goto(base+'/scenes.html',{waitUntil:'networkidle'});
if(await page.locator('a[href="gpt-methods-valid.html"]').count()){
 await page.goto(base+'/gpt-methods-valid.html',{waitUntil:'networkidle'});
 const selected=await page.evaluate(async()=>await (await fetch('data/gpt-methods-valid-progress.json')).json());
 if(await page.locator('#gpt-case-matrix tbody tr').count()!==50||await page.locator('.gpt-episode').count()!==selected.episodes.length)throw Error('Selected cohort matrix or videos');
 await page.locator('details:has(#gpt-case-matrix) > summary').click();
 if(JSON.stringify(selected.cohort.original_summary)!==JSON.stringify(gd.summary)||selected.cohort.diagnostic_episodes_in_denominator!==false)throw Error('Original and selected denominators');
 await page.selectOption('#gpt-method','gpt_only');await page.selectOption('#gpt-status','failure');
 if(await page.locator('.gpt-episode:visible').count()!==selected.episodes.filter(e=>e.method==='gpt_only'&&!e.success).length)throw Error('Selected native failure filter');
 const chosen=selected.episodes.find(e=>e.method==='pi05_plus_gpt');
 if(chosen){
  await page.locator('#gpt-case-matrix a[href="#'+chosen.id+'"]').click();
  await page.waitForFunction(n=>[...document.querySelectorAll('.gpt-episode')].filter(e=>!e.hidden).length===n,selected.episodes.length);
  const movie=page.locator('#'+chosen.id+' video');await movie.evaluate(async v=>{v.muted=true;await v.play()});await page.waitForTimeout(1000);
  const played=await movie.evaluate(v=>({time:v.currentTime,width:v.videoWidth,duration:v.duration}));
  if(!(played.time>0&&played.width===1440&&Math.abs(played.duration-chosen.duration_seconds)<.1))throw Error('Selected full playback');
  await movie.evaluate(v=>v.pause());
 }
 await page.screenshot({path:'.artifacts/gpt-methods-valid-desktop.png'});await page.setViewportSize({width:390,height:844});
 const width=await page.evaluate(()=>({viewport:innerWidth,scroll:document.documentElement.scrollWidth}));if(width.scroll>width.viewport)throw Error('Selected mobile overflow');
 await page.screenshot({path:'.artifacts/gpt-methods-valid-mobile.png'});
 if(!(await page.locator('a[href="gpt-methods.html"]').count()))throw Error('Original cohort comparison link');
 selectedResult={complete_method_runs:selected.episodes.length,completed_pairs:selected.summary.completed_pairs,matrix_cases:50,original_preserved:true,filters:true,deep_links:true,mobile:width};
}
if(errors.length)throw Error(errors.join('\n'));const result={passed:true,gpt_valid:selectedResult,cases:expected,filters:['task','result','protocol','search','empty','reset'],deep_links:true,theme_persistence:true,video:media,mobile:dimensions,robolab:{episodes:rd.episodes.length,video:rm,mobile:rw},robolab_methods:{complete_method_runs:supplemental.summary.complete_method_runs,completed_pairs:supplemental.summary.completed_pairs,matrix_cases:50,video:supplementalMedia,mobile:sw},gpt:{complete_method_runs:gd.episodes.length,completed_pairs:gd.summary.completed_pairs,matrix_cases:50,filters:true,deep_links:true,video:gm,mobile:gw},errors};fs.writeFileSync('.artifacts/gpt-policy-browser-results.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));await browser.close()})().catch(e=>{console.error(e);process.exit(1)});
