"""Export RoboLab Direct/Hybrid first audited terminals separately from RoboDojo."""
from html import escape as E
import json
from pathlib import Path
from build_gpt_site import read,write,digest,media,METHODS,PROOF_KEYS
from robolab_activity import activity


def eligible(run,entry):
    result=read(run/'rollout/result.json',{})
    identity=read(run/'rollout/run.json',{})
    proof=read(run/'complete_action_audit.json',{})
    assert result.get('complete') is True and (result.get('terminated') is True or result.get('truncated') is True)
    assert type(result['success']) is bool
    assert (identity['task'],identity['seed'])==(entry['task'],entry['seed'])
    assert (identity.get('evaluation_method')=='gpt_only')==(entry['method']=='gpt_only')
    assert proof['verified'] is True and proof['complete_episode'] is True and proof['scope']=='complete_native_episode'
    assert proof['method']==entry['method'] and (proof['model'],proof['reasoning_effort'])==('gpt-6-astra','xhigh')
    assert proof['native_actions']==result['step_id'] and proof['decisions']==result['decisions']
    assert proof['max_absolute_action_error']==0 and sum(proof['actions_by_mode'].values())==result['step_id']
    assert proof['terminal']=={k:result[k] for k in ('terminated','truncated','success')}
    assert proof['initial_state_hash']==identity['initial_state_hash']
    for name in ('rollout/result.json','rollout/run.json','rollout/codex_workspace/worker.json'):
        assert proof['files_sha256'][name]==digest(run/name)
    summaries=[name for name in proof['files_sha256'] if name.startswith('remote/sim/') and name.endswith('/summary.json')]
    assert len(summaries)==1
    summary=read(run/summaries[0]);assert digest(run/summaries[0])==proof['files_sha256'][summaries[0]]
    assert summary['complete'] is True and (summary['task'],summary['seed'])==(entry['task'],entry['seed'])
    assert summary['control_steps']==result['step_id'] and all(summary[k]==result[k] for k in ('terminated','truncated','success'))
    assert summary['native_max_episode_steps']==summary['max_episode_steps']==identity['max_episode_steps']
    if entry['method']=='gpt_only':assert proof['pi05_inference_calls']==result['pi05_inference_calls']==0
    return result,identity,proof


def select(attempts,entry):
    """An earlier native failure/audit gap blocks any later success selection."""
    for run,record in sorted(attempts,key=lambda pair:pair[1]['started_utc']):
        result=read(run/'rollout/result.json',{})
        if result.get('complete') is True and (result.get('terminated') is True or result.get('truncated') is True):
            try:return run,eligible(run,entry),'complete'
            except (AssertionError,KeyError,FileNotFoundError,TypeError,ValueError):return run,None,'audit_pending'
    return None,None,'pending'


def summarize(cases,episodes):
    paired={c['case_id'] for c in cases if c['paired_complete']}
    methods={}
    for method in METHODS:
        values={}
        for name,subset in (('all_completed',[e for e in episodes if e['method']==method]),
                            ('paired_completed',[e for e in episodes if e['method']==method and e['case_id'] in paired])):
            n=len(subset);wins=sum(e['success'] for e in subset)
            values[name]=dict(evaluated=n,successes=wins,failures=n-wins,success_rate=wins/n if n else None)
        methods[method]=values
    return dict(planned_pairs=50,planned_method_runs=100,completed_pairs=len(paired),complete_method_runs=len(episodes),methods=methods)


def build(source,out):
    frozen=read(source/'fixtures/robolab_two_methods_frozen.json')
    if not frozen:return None
    entries=frozen['entries'];assert len(entries)==100
    grouped={(e['task'],e['seed'],e['method']):[] for e in entries}
    assert len(grouped)==100
    campaign=source/'robolab_gpt_campaign';attempts=[]
    if campaign.exists():
        for run in sorted(campaign.iterdir()):
            record=read(run/'attempt.json')
            if not record:continue
            key=(record['task'],record['seed'],record['method'])
            if key in grouped:
                grouped[key].append((run,record))
                attempts.append(dict(run_id=run.name,task=key[0],seed=key[1],method=key[2],
                    status=record['status'],started_utc=record['started_utc'],eligible=False))
    previous=read(out/'data/robolab-methods-progress.json',{})
    old={e['id']:e for e in previous.get('episodes',[])}
    active=activity(source)
    active_keys={(r['task'],r['seed'],r['method']):r for r in active}
    episodes=[];cases=[]
    pairs=sorted({(e['task'],e['seed']) for e in entries});assert len(pairs)==50
    for task,seed in pairs:
        cid=task+'__seed'+str(seed);case=dict(case_id=cid,task=task,seed=seed,methods={})
        for method in METHODS:
            entry=dict(task=task,seed=seed,method=method);run,values,status=select(grouped[(task,seed,method)],entry)
            item=dict(status=status,episode_id=None)
            if status=='pending' and (task,seed,method) in active_keys:
                item.update(status='running',observed_control_steps=active_keys[(task,seed,method)]['observed_control_steps'])
            if values:
                result,identity,proof=values;uid='robolab_'+cid+'__'+method
                public_proof={k:proof[k] for k in PROOF_KEYS if k in proof}
                public_proof.update(method=method,terminal=proof['terminal'],student_identity_sha256=proof['student_identity_sha256'])
                audit_path='data/robolab-method-episodes/'+uid+'-audit.json';write(out/audit_path,public_proof)
                movie=media(run,uid,out,old,source_file=run/'remote/sim/sensors.mp4',prefix='media/robolab-methods')
                episode=dict(id=uid,run_id=run.name,case_id=cid,task=task,seed=seed,method=method,
                    success=result['success'],complete=True,eligible=True,control_steps=result['step_id'],decisions=result['decisions'],
                    terminated=result['terminated'],truncated=result['truncated'],actions_by_mode=proof['actions_by_mode'],
                    pi05_inference_calls=proof['pi05_inference_calls'],initial_state_hash=identity['initial_state_hash'],
                    native_horizon=identity['max_episode_steps'],audit=audit_path,audit_sha256=digest(out/audit_path),**movie)
                episode['evidence']='data/robolab-method-episodes/'+uid+'.json';write(out/episode['evidence'],episode)
                episodes.append(episode);item.update(episode_id=uid)
            case['methods'][method]=item
        case['paired_complete']=all(v['episode_id'] for v in case['methods'].values());cases.append(case)
    selected={e['run_id'] for e in episodes}
    for attempt in attempts:
        if attempt['run_id'] in selected:attempt.update(eligible=True,status='complete')
    data=dict(schema='gpt_policy_robolab_methods.v1',frozen_sha256=digest(source/'fixtures/robolab_two_methods_frozen.json'),
        cohort='new fixed-seed cohort; historical raw initial states unavailable',
        direct_implementation='owned EEF adapter; historical Direct source and prompt unavailable',
        cases=cases,episodes=episodes,attempts=attempts,active_runs=active,summary=summarize(cases,episodes))
    write(out/'data/robolab-methods-progress.json',data);render(out,data)
    return data


def render(out,data):
    summary=data['summary'];episodes={e['id']:e for e in data['episodes']}
    stats=[]
    for method,label in METHODS.items():
        value=summary['methods'][method]['all_completed']
        stats.append(f'<article><span>{label}</span><strong>{value["successes"]}<small> / {value["evaluated"]}</small></strong><p>成功 / 完整原生回合</p></article>')
    rows=[]
    for c in data['cases']:
        cells=[]
        for method in METHODS:
            value=c['methods'][method];episode=episodes.get(value['episode_id'])
            cells.append('<td>'+ (f'<a href="#{episode["id"]}">{"成功" if episode["success"] else "原生失败"} · {episode["control_steps"]} 步</a>' if episode else ('完整终止，待审计' if value['status']=='audit_pending' else f'运行中 · {value["observed_control_steps"]} 步' if value['status']=='running' else '待完成'))+'</td>')
        rows.append(f'<tr><td>{E(c["task"])} / seed {c["seed"]}</td>'+''.join(cells)+'</tr>')
    cards=[]
    for episode in episodes.values():
        cards.append(f'<article class="episode" id="{episode["id"]}"><h3>{E(episode["task"])} / seed {episode["seed"]} · {METHODS[episode["method"]]}</h3><p>{"原生成功" if episode["success"] else "原生失败"} · {episode["control_steps"]} 步 / {episode["decisions"]} 决策</p><video controls playsinline preload="none" poster="{episode["poster"]}"><source src="{episode["video"]}" type="video/mp4"></video><p><a href="{episode["evidence"]}">案例 JSON ↓</a> · <a href="{episode["audit"]}">完整动作审计 ↓</a></p></article>')
    document=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RoboLab 两方法补充 · GPT-as-Policy 复现</title><link rel="stylesheet" href="assets/site.css"><link rel="stylesheet" href="assets/gpt.css"></head><body><header class="topbar"><div class="wrap top-inner"><a class="brand" href="scenes.html">GPT-AS-POLICY / 复现主页</a></div></header><main class="wrap"><section class="report-section"><h1>RoboLab · GPT Direct 与 Hybrid</h1><p class="hero-lead">50 个固定种子案例 × 两方法；已审计 {summary["complete_method_runs"]} / 100 个完整回合，已配齐 {summary["completed_pairs"]} / 50 个案例。</p><p>这是新的补充评测，和 RoboDojo 主实验分别计分。Direct 为本项目 EEF 适配器，历史实现未公开；历史原始初态未恢复。完整失败计入分母，前缀审计、连接中断和独立 π0.5 辅助轨迹均不计分。</p><div class="stats gpt-stats">{''.join(stats)}</div><p><a href="data/robolab-methods-progress.json">完整补充结果与配对 JSON ↓</a> · <a href="robolab.html">历史独立 π0.5 辅助回放 ↗</a></p></section><section class="report-section"><h2>50 案例矩阵</h2><div class="panel table-wrap"><table id="robolab-methods-matrix"><thead><tr><th>案例</th><th>GPT Direct</th><th>Hybrid</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></section><section class="report-section"><h2>已审计完整回放</h2><div class="episode-grid">{''.join(cards)}</div><p>未计分尝试 {sum(not a["eligible"] for a in data["attempts"])} 次，记录在结果 JSON 中；中断不能代替完整回合。</p></section></main></body></html>'''
    (out/'robolab-methods.html').write_text(document)
