"""Build a portable public report from explicitly selected local experiment fields."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import html
import json
import re
from pathlib import Path
import shutil
import subprocess

TASKS = {'arrange_largest_number':'排列最大数字','build_tower':'搭建积木塔',
'classify_objects':'物体分类','classify_objects_by_language':'按语言分类',
'fold_clothes':'折叠衣物','imitate_sorting_sequence':'模仿排序序列',
'make_kong':'制作 Kong 玩具','organize_table':'整理桌面',
'pack_objects_into_box':'物品装箱','put_bottles_into_dustbin':'瓶子放入垃圾桶'}
METHODS={'pi05_prefix15':'π0.5 · 前 15 步','pi05_chunk50':'π0.5 · 完整 50 步'}
STATES={'success':'成功','failure':'原生失败','excluded':'无效布局 · 排除','incomplete':'未完成'}
E=html.escape

def read(path):return json.loads(path.read_text())
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();root=a.source.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    (out/'assets').mkdir(exist_ok=True)
    for asset in (Path(__file__).resolve().parents[1]/'web/assets').iterdir():shutil.copyfile(asset,out/'assets'/asset.name)
    report=read(root/'independent_report.json');audit=read(root/'prefix15_cohort_audit.json')
    assert not report['artifact_errors']
    source_rows={r['directory']:r for r in report['episodes']}
    entries=[]
    for row in audit['cases']:
        folder=(root/row['evidence']).parent
        folder.resolve().relative_to(root)
        match=source_rows.get(str((folder/'rollout').relative_to(root)))
        entries.append((folder,read(root/'fixtures/cases'/f"{row['case']}.json")['case'],match,'pi05_prefix15'))
    for row in report['episodes']:
        if row['method']=='pi05_chunk50':
            entries.append(((root/row['directory']).parent,row['case'],row,'pi05_chunk50'))
    records=[];jobs=[]
    for folder,case,row,method in entries:
        cid=case['case_id']
        if not re.fullmatch(r'[a-z0-9_]+',cid):raise ValueError('Unexpected case ID')
        uid=method+'__'+cid
        outcome_path=folder/'sim/evaluation_outcome.json'
        native=read(outcome_path) if outcome_path.exists() else {}
        status=('excluded' if native.get('status')=='invalid_native_layout' else
                'success' if row and row['eligible'] and row['success'] else
                'failure' if row and row['eligible'] else 'incomplete')
        steps=row['steps'] if row else native.get('native_control_steps',0)
        ident=folder/'policy_identity.json';identity=read(ident) if ident.exists() else {}
        record=dict(id=uid,case_id=cid,task=case['task'],task_label=TASKS[case['task']],
                    runtime_task=case['runtime_task'],variant=case['variant'],seed=case['reset_seed'],
                    method=method,method_label=METHODS[method],status=status,status_label=STATES[status],
                    complete=bool(row and row['complete']),eligible=bool(row and row['eligible']),
                    success=native.get('native_success'),score=native.get('native_score'),steps=steps,
                    native_horizon=native.get('native_step_limit'),run_id=folder.name,
                    layout_sha256=case.get('layout_sha256',case.get('layout',{}).get('sha256')),
                    checkpoint_sha256=identity.get('checkpoint_sha256'),
                    native_status=native.get('status'),teacher_invoked=False,
                    evidence='data/episodes/'+uid+'.json',video=None,poster=None)
        history_path=folder/'rollout/history.json'
        history=read(history_path) if history_path.exists() else []
        trace=[]
        for i,h in enumerate(history):
            trace.append({k:h[k] for k in ('decision','start_tick','end_tick','executed_steps','native_success','terminal','inference_index') if k in h})
        video=folder/'sim/sensors.mp4'
        if video.exists() and video.stat().st_size>1000:
            record['video']='media/'+uid+'.mp4';record['poster']='media/'+uid+'.jpg'
            jobs.append((video,out/record['video'],out/record['poster']))
        record['decisions']=len(history)
        write(out/record['evidence'],dict(**record,execution_trace=trace,
             interpretation='原生失败计入分母；无效布局、基础设施错误和未完成轨迹不计入分母。'))
        records.append(record)
    records.sort(key=lambda r:(list(TASKS).index(r['task']),r['method'],r['seed']))
    def media(job):
        source,destination,poster=job;destination.parent.mkdir(parents=True,exist_ok=True)
        if not destination.exists():
            temp=destination.with_suffix('.tmp.mp4')
            subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(source),'-an','-vf','scale=1440:-2,fps=15',
                '-c:v','libx264','-preset','fast','-crf','26','-threads','2','-movflags','+faststart','-y',str(temp)],check=True)
            temp.replace(destination)
        if not poster.exists():
            subprocess.run(['ffmpeg','-nostdin','-v','error','-ss','0','-i',str(destination),'-frames:v','1','-q:v','3','-threads','1','-y',str(poster)],check=True)
        return dict(path=str(destination.relative_to(out)),source_sha256=digest(source),sha256=digest(destination),bytes=destination.stat().st_size)
    with ThreadPoolExecutor(max_workers=3) as pool:media_manifest=list(pool.map(media,jobs))
    groups=[]
    for task,label in TASKS.items():
        rs=[r for r in records if r['task']==task and r['method']=='pi05_prefix15'];valid=[r for r in rs if r['eligible']]
        groups.append(dict(task=task,label=label,cases=len(rs),eligible=len(valid),successes=sum(r['success'] is True for r in valid),
            mean_score=sum(r['score'] for r in valid)/len(valid) if valid else None,episodes=[r['id'] for r in rs]))
    summary=report['summary']['pi05_prefix15']
    assert sum(g['eligible'] for g in groups)==summary['evaluated']==audit['eligible_cases']
    assert sum(g['successes'] for g in groups)==summary['successes']==audit['successes']
    now=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    public=dict(generated_at=now,planned_prefix15_cases=audit['planned_cases'],resolved_prefix15_cases=audit['resolved_cases'],
                summary={k:v for k,v in report['summary'].items() if k in METHODS},tasks=groups,episodes=records,
                source_report_sha256=digest(root/'independent_report.json'))
    write(out/'data/report.json',public);write(out/'data/media-manifest.json',media_manifest)
    write(out/'data/public-report-recomputed.json',read(root/'public_metrics_recomputed.json'))
    baselines=read(root/'additional_baseline_sources.json')
    public_baselines=[{key:row[key] for key in ('method','source_commit','checkpoint_repository','checkpoint_revision','status','verified_files','verified_bytes','manifest_sha256','inference_completed','excluded_prefixes') if key in row} for row in baselines]
    write(out/'data/model-readiness.json',dict(generated_at=now,models=public_baselines))
    action_audit=read(root/'chunk50_first_episode_audit.json')
    write(out/'data/chunk50-action-audit.json',{key:action_audit[key] for key in ('verified','native_actions','predictions','max_absolute_action_error','checks')})

    shutil.copyfile(root/'independent_task_results.png',out/'assets/task-results.png')
    smoke=root/'mainskill_robolab_smoke/20260915T083211Z/rollout/observations/000'
    for name in ('main_rgb','wrist_rgb'):shutil.copyfile(smoke/(name+'.png'),out/'assets'/('robolab-'+name+'.png'))
    write(out/'data/robolab-render-validation.json',read(smoke/'render_validation.json'))
    write(out/'data/robolab-strict-reset-validation.json',read(root/'mainskill_strict_reset_validation.json'))
    write(out/'data/robolab-fresh-reset-pairing.json',read(root/'mainskill_fresh_reset_pairing.json'))
    write(out/'data/robolab-first-action-audit.json',read(root/'mainskill_robolab_first_action_audit.json'))
    write(out/'data/robolab-openpi-environment.json',read(root/'mainskill/openpi_environment.json'))
    from markdown import markdown
    interpretation=(root/'report_interpretation_zh.md').read_text().replace('`independent_report.md`','本页「独立结果」').replace('`recompute_public_metrics.py`','公开结果复算脚本')
    article=markdown(interpretation,extensions=['tables','fenced_code'])
    (out/'data/report-interpretation.md').write_text(interpretation)
    matrix=[]
    for g in groups:
        cells=''.join(f'<button class="seed {r["status"]}" data-focus="{r["id"]}" title="{E(r["case_id"])} · {r["status_label"]}" aria-label="{E(g["label"])} seed {r["seed"]} {r["status_label"]}">{r["seed"]}</button>' for r in records if r['id'] in g['episodes'])
        n=g['eligible'];wins=g['successes'];rate=wins/n if n else 0
        matrix.append(f'<tr><td><button class="task-link" data-task="{g["task"]}">{g["label"]}</button><small>{g["task"]}</small></td><td><div class="seeds">{cells}</div></td><td class="mono">{wins} / {n}</td><td><div class="bar"><i style="width:{rate*100}%"></i></div><span class="mono">{rate:.0%}</span></td><td class="mono">{g["mean_score"]:.2f}</td></tr>')
    cards=[]
    for r in records:
        if r['video']:
            player=f'<video controls playsinline preload="none" poster="{r["poster"]}" aria-label="{E(r["task_label"])} seed {r["seed"]} 回放"><source src="{r["video"]}" type="video/mp4"></video>'
        else:player='<div class="no-video"><span>∅</span><p>原生场景初始化失败</p><small>无可用执行回放 · 已保留排除记录</small></div>'
        score='—' if r['score'] is None else f'{r["score"]:.2f}'
        cards.append(f'''<article class="episode" id="{r['id']}" data-task="{r['task']}" data-method="{r['method']}" data-status="{r['status']}" data-search="{E(r['case_id']+' '+r['task_label'])}">
<div class="episode-head"><div><span class="eyebrow">{r['method_label']} · SEED {r['seed']}</span><h3>{r['task_label']}</h3></div><span class="badge {r['status']}">{r['status_label']}</span></div>{player}
<div class="episode-meta"><span>控制步 <b class="mono">{r['steps']:,}</b></span><span>得分 <b class="mono">{score}</b></span><span>{'随机变体' if 'random' in r['runtime_task'] else '标准场景'}</span></div>
<details><summary>案例与执行记录 <span>↗</span></summary><div class="evidence-detail"><code>{E(r['case_id'])}</code><p>运行：{r['run_id']}<br>模型决策：{r['decisions']} 次<br>计入成功率：{'是' if r['eligible'] else '否'}</p><a href="{r['evidence']}" download>下载案例 JSON ↓</a></div></details></article>''')
    options=''.join(f'<option value="{t}">{label}</option>' for t,label in TASKS.items())
    featured=next(r for r in records if r['task']=='put_bottles_into_dustbin' and r['status']=='success')
    from PIL import Image
    with Image.open(out/featured['poster']) as im:
        im.crop((0,0,im.width//3,im.height)).save(out/'assets/hero.jpg',quality=93)
    chunk=report['summary'].get('pi05_chunk50',{})
    html_template=(Path(__file__).parent/'template.html').read_text()
    values={'UPDATED':now,'ATTEMPTED':str(audit['resolved_cases']),'ELIGIBLE':str(summary['evaluated']),'SUCCESSES':str(summary['successes']),
            'RATE':f"{summary['success_rate']:.2%}",'STEPS':f"{summary['observed_steps']:,}",'MEAN_SCORE':f"{summary['mean_score']:.4f}",
            'MATRIX':''.join(matrix),'CARDS':''.join(cards),'TASK_OPTIONS':options,'EPISODE_COUNT':str(len(records)),
            'FEATURED_POSTER':featured['poster'],'FEATURED_ID':featured['id'],'ARTICLE':article,
            'CHUNK_COUNT':str(chunk.get('evaluated',0)),'CHUNK_WINS':str(chunk.get('successes',0))}
    for key,value in values.items():html_template=html_template.replace('{{'+key+'}}',value)
    assert '{{' not in html_template
    (out/'index.html').write_text(html_template)
    (out/'scenes.html').write_text(html_template)
    (out/'.nojekyll').touch()
    print(json.dumps(dict(site=str(out),episodes=len(records),videos=len(media_manifest),media_mib=sum(x['bytes'] for x in media_manifest)/2**20,summary=summary),ensure_ascii=False),flush=True)

if __name__=='__main__':main()
