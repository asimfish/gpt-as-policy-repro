"""Compare the sealed independent cohort to immutable public author snapshots."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import statistics

METHODS={'gpt_only':'GPT Direct','pi05_plus_gpt':'π0.5 + GPT Hybrid'}
ORIGINAL={'gpt':'gpt_only','mix':'pi05_plus_gpt'}
SEEDS=('eval_seed','layout_id','reset_seed','simulator_initial_seed','policy_rng_seed')
TOKEN_KEYS=('totalTokens','inputTokens','cachedInputTokens','cacheWriteInputTokens','outputTokens','reasoningOutputTokens')


def read(path):return json.loads(path.read_text())
def sha(data):return hashlib.sha256(data).hexdigest()
def integer(value):
    assert type(value) is int and value>=0
    return value

def mean_score(rows):
    values=[r['score'] for r in rows if r.get('score') is not None]
    assert all(type(v) in (int,float) and 0<=v<=1 for v in values)
    return dict(score_samples=len(values),mean_score=statistics.mean(values) if values else None)

def metrics(rows):
    assert rows and all(type(r['success']) is bool for r in rows)
    steps=sum(integer(r['steps']) for r in rows)
    assert all(integer(r['corrected_steps'])<=r['steps'] for r in rows)
    tokens=[r.get('tokens') for r in rows]
    present=[r for r in tokens if r is not None]
    fields={k:sum(integer(r[k]) for r in present) for k in TOKEN_KEYS}
    return dict(episodes=len(rows),successes=sum(r['success'] for r in rows),
        success_rate=sum(r['success'] for r in rows)/len(rows),**mean_score(rows),
        control_steps=steps,executed_chunks=sum(integer(r['chunks']) for r in rows),
        corrected_steps=sum(integer(r['corrected_steps']) for r in rows),
        correction_fraction=sum(r['corrected_steps'] for r in rows)/steps if steps else None,
        token_samples=len(present),tokens=fields if present else None,
        token_scope='last recorded cumulative controller usage; cached input included; not billing')

def indexed(rows):
    keys=[(r['case_id'],r['method']) for r in rows]
    assert len(keys)==len(set(keys)), 'Duplicate case/method would distort denominators'
    return dict(zip(keys,rows))

def budget_observation(rows,budget):
    assert integer(budget)>0
    assert all(type(r['success']) is bool for r in rows)
    finished=[r for r in rows if integer(r['decision_events'])<=budget]
    return dict(budget=budget,episodes=len(rows),success_already_observed=sum(r['success'] for r in finished),
        native_failure_already_observed=sum(not r['success'] for r in finished),
        still_unfinished_in_recorded_prefix=len(rows)-len(finished),
        scope='Recorded-prefix observation only; not a new capped-policy evaluation or causal estimate.')

def compare_cases(original,current):
    old,new=indexed(original),indexed(current)
    common=sorted(set(old)&set(new));details=[]
    for key in common:
        a,b=old[key],new[key]
        assert a['seeds']==b['seeds'], 'Same case ID with different seed fields is not aligned'
        details.append(dict(case_id=key[0],method=key[1],original_success=a['success'],
            reproduction_success=b['success'],original_score=a.get('score'),reproduction_score=b.get('score'),
            success_changed=a['success']!=b['success'],evidence=b['evidence']))
    return dict(alignment='case identifiers and five seed fields; historical full physics states unverified',
        common_case_pairs=len({r['case_id'] for r in details}),common_method_runs=len(details),
        original_only=[dict(case_id=k[0],method=k[1]) for k in sorted(set(old)-set(new))],
        reproduction_only=[dict(case_id=k[0],method=k[1]) for k in sorted(set(new)-set(old))],
        methods={m:dict(episodes=sum(r['method']==m for r in details),
            original_successes=sum(r['method']==m and r['original_success'] for r in details),
            reproduction_successes=sum(r['method']==m and r['reproduction_success'] for r in details),
            changed_success_outcomes=sum(r['method']==m and r['success_changed'] for r in details)) for m in METHODS},cases=details)

def task_comparison(original,current):
    rows=[]
    for task in sorted({r['task'] for r in original}|{r['task'] for r in current}):
        for method in METHODS:
            a=[r for r in original if r['task']==task and r['method']==method]
            b=[r for r in current if r['task']==task and r['method']==method]
            assert a and b and len(a)==len(b), 'Task denominators differ'
            rows.append(dict(task=task,method=method,original=metrics(a),reproduction=metrics(b)))
    return rows

def collect(source,docs,gate):
    bindings={(r['cohort'],r['case_id'],r['method']):r for r in gate['original_episodes']}
    records=[];inputs={};extra_inputs=[]
    for cohort,filename in [('robodojo','gpt-methods-valid-progress.json'),('robolab','robolab-methods-progress.json')]:
        document=read(docs/'data'/filename)
        assert document['summary']['complete_method_runs']==100 and document['summary']['completed_pairs']==50
        for e in document['episodes']:
            assert re.fullmatch(r'[A-Za-z0-9_]+',e['run_id']) and e['method'] in METHODS
            root=source/('gpt_pair_campaign' if cohort=='robodojo' else 'robolab_gpt_campaign')/e['run_id']
            if cohort=='robodojo':root=root/e['method']
            def bound(rel,expected=None):
                f=root/rel;data=f.read_bytes();digest=sha(data)
                if expected is not None:assert digest==expected,rel
                inputs[str(f.relative_to(source))]=digest
                return json.loads(data)
            proof=bound('complete_action_audit.json',bindings[cohort,e['case_id'],e['method']]['audit_sha256'])
            result=bound('rollout/result.json',proof['files_sha256']['rollout/result.json'])
            run_config=bound('rollout/run.json',proof['files_sha256']['rollout/run.json'])
            history=bound('rollout/history.json',proof['files_sha256'].get('rollout/history.json'))
            if 'rollout/history.json' not in proof['files_sha256']:
                extra_inputs.append(str((root/'rollout/history.json').relative_to(source)))
            assert result['complete'] is True and result['success']==e['success']
            executed=[h for h in history if integer(h['executed_steps'])>0]
            assert sum(h['executed_steps'] for h in executed)==e['control_steps']==proof['native_actions']
            corrected=sum(h['executed_steps'] for h in executed if h['response'].get('mode') in ('edit','eef')) if e['method']=='pi05_plus_gpt' else 0
            if e['method']=='pi05_plus_gpt':
                assert corrected==proof['actions_by_mode']['edit']+proof['actions_by_mode']['eef']
            tokens=None;usage_path=root/'rollout/token_usage.json'
            if usage_path.exists():
                usage=bound('rollout/token_usage.json')
                if 'rollout/token_usage.json' not in proof['files_sha256']:
                    extra_inputs.append(str(usage_path.relative_to(source)))
                assert usage['model']=='gpt-6-astra' and usage['effort']=='xhigh'
                assert usage['total_tokens_include_cached_input'] is True
                tokens={k:integer(usage['usage']['total'][k]) for k in TOKEN_KEYS}
                assert tokens['totalTokens']==tokens['inputTokens']+tokens['outputTokens']
                assert tokens['cachedInputTokens']<=tokens['inputTokens'] and tokens['reasoningOutputTokens']<=tokens['outputTokens']
            row=dict(cohort=cohort,case_id=e['case_id'],method=e['method'],run_id=e['run_id'],
                task=e.get('task',e.get('identity',{}).get('task')),success=e['success'],score=e.get('score'),
                steps=e['control_steps'],chunks=len(executed),decision_events=e['decisions'],corrected_steps=corrected,
                tokens=tokens,evidence=e['evidence'],max_decisions=integer(run_config['max_decisions']))
            if cohort=='robodojo':row['seeds']={k:e['identity'][k] for k in SEEDS}
            records.append(row)
    assert len(records)==200
    return records,inputs,extra_inputs

def prepare(source,docs):
    q=source/'publication_checks/blog_alignment_20261008'
    if not (q/'original_sources.json').exists():return None
    sources=read(q/'original_sources.json')
    for name in ('original_robodojo_cases.json','original_robolab.json','original_robolab_leaderboard.csv'):
        assert sha((q/name).read_bytes())==sources[name]['sha256']
    gate_data=(source/'full_reproduction_verification.json').read_bytes();gate=json.loads(gate_data)
    certificate=source/'final_verification'/gate['published_commit']/'certificate.json'
    assert gate_data==certificate.read_bytes()
    from export_infra_bundle import validate_completion_certificate
    validate_completion_certificate(gate_data,dict(sha256=sha(gate_data),published_commit=gate['published_commit']))
    current,inputs,extra_inputs=collect(source,docs,gate)
    raw=read(q/'original_robodojo_cases.json')['cases']
    original=[dict(case_id=r['case_id'],method=ORIGINAL[r['method']],task=r['task'],success=r['success'],
        score=r['score'],steps=r['steps'],chunks=r['chunks'],corrected_steps=r['corrected_steps'],
        tokens={k:r['tokens'][k] for k in TOKEN_KEYS},seeds={k:r['seeds'][k] for k in SEEDS}) for r in raw]
    assert len(original)==100 and len(indexed(original))==100
    own_dojo=[r for r in current if r['cohort']=='robodojo'];lab=read(q/'original_robolab.json')
    own_lab=[r for r in current if r['cohort']=='robolab'];lab_tasks=[]
    for task in lab['tasks']:
        for method,alias in [('gpt_only','pure_astra'),('pi05_plus_gpt','astra_pi05')]:
            actual=[r for r in own_lab if r['task']==task['task'] and r['method']==method]
            assert len(actual)==5
            lab_tasks.append(dict(task=task['task'],method=method,original_successes=integer(task['successes'][alias]),
                reproduction_successes=sum(r['success'] for r in actual),episodes=5))
    assert len(lab_tasks)==20
    for method,alias in [('gpt_only','pure_astra'),('pi05_plus_gpt','astra_pi05')]:
        published=next(r for r in lab['methods'] if r['id']==alias)
        assert published['episodes']==50 and published['successes']==sum(r['original_successes'] for r in lab_tasks if r['method']==method)
    comparison=dict(schema='gpt_policy_blog_comparison.v1',independent_evaluation_complete=True,
        historical_equivalence_verified=False,native_completion_commit=gate['published_commit'],
        native_completion_sha256=sha(gate_data),original_sources={k:sources[k] for k in ('GPT-as-Policy','public-website','original_robodojo_cases.json','original_robolab.json','original_robolab_leaderboard.csv')},
        original_robodojo_episodes=original,reproduction_episodes=current,
        robodojo=dict(methods={m:dict(original=metrics([r for r in original if r['method']==m]),reproduction=metrics([r for r in own_dojo if r['method']==m])) for m in METHODS},
            tasks=task_comparison(original,own_dojo),case_alignment=compare_cases(original,own_dojo)),
        robolab=dict(case_alignment_verified=False,original_uniform_fresh_budget=False,
            reproduction_selection='First valid native terminal attempt, audited original failures retained; infrastructure retries bounded separately.',
            max_decisions_by_method={m:sorted({r['max_decisions'] for r in own_lab if r['method']==m}) for m in METHODS},
            recorded_budget_observations={m:[budget_observation([r for r in own_lab if r['method']==m],b) for b in (180,500)] for m in METHODS},
            methods={m:dict(original_successes=sum(t['original_successes'] for t in lab_tasks if t['method']==m),
                reproduction=metrics([r for r in own_lab if r['method']==m]),episodes=50) for m in METHODS},tasks=lab_tasks),
        limitations=['一对 RoboDojo layout4 改为预冻结 layout5；原面板另存，两个面板共享49对。',
            '匹配案例ID与种子不能证明历史完整物理初态相同；RoboLab仅按任务汇总比较。',
            'RoboLab Direct 使用自有 EEF 适配器，历史完整源码与prompt未恢复。',
            '原 RoboLab 含历史结果及授权重试，两个 BlocksInBin Direct 重试使用500而非180决策；本次不采用该混合预算协议。',
            '本次RoboLab日志的决策上限为100000，主要受原生控制时域约束；180/500决策表仅截看已有轨迹，不是新预算评测或因果解释。',
            'Token 为控制器最后记录的累计计数，包含缓存输入；RoboLab缺少独立用量汇总，保持未知，不能作为零消耗或账单金额。',
            'π0.5、Cosmos和DreamZero全量基线尚未纳入此前两方法范围。'])
    receipt=dict(schema='gpt_policy_blog_statistics_audit.v1',verified=True,complete_native_episodes=200,
        native_completion_sha256=sha(gate_data),files_sha256=inputs,additional_statistics_inputs=extra_inputs,
        method='Original audit/result/config SHA bindings; history coverage and correction counts checked against sealed native audit. History absent from older audit manifests and cumulative usage files are separately captured with current SHA, not retroactively claimed as original gate inputs. No model or simulator calls.',
        original_source_files={name:sources[name]['sha256'] for name in ('original_robodojo_cases.json','original_robolab.json','original_robolab_leaderboard.csv')},
        comparison_sha256=sha((json.dumps(comparison,ensure_ascii=False,indent=2)+'\n').encode()))
    (q/'statistics_audit.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return comparison

def verify_public(docs):
    path=docs/'data/blog-comparison.json'
    if not path.exists():return
    value=read(path)
    assert value['schema']=='gpt_policy_blog_comparison.v1'
    assert value['independent_evaluation_complete'] is True and value['historical_equivalence_verified'] is False
    assert value['native_completion_sha256']==sha((docs/'data/reproduction-completion.json').read_bytes())
    old=value['original_robodojo_episodes'];current=value['reproduction_episodes']
    assert len(old)==100 and len(current)==200
    for cohort,name in [('robodojo','gpt-methods-valid-progress.json'),('robolab','robolab-methods-progress.json')]:
        own=[r for r in current if r['cohort']==cohort];lookup=indexed(own);document=read(docs/'data'/name)
        assert set(lookup)=={(e['case_id'],e['method']) for e in document['episodes']}
        for e in document['episodes']:
            row=lookup[e['case_id'],e['method']]
            assert row['run_id']==e['run_id'] and row['success']==e['success'] and row['score']==e.get('score')
            assert row['steps']==e['control_steps'] and row['decision_events']==e['decisions'] and row['evidence']==e['evidence']
            if e['method']=='pi05_plus_gpt':assert row['corrected_steps']==e['actions_by_mode']['edit']+e['actions_by_mode']['eef']
            else:assert row['corrected_steps']==0
            if cohort=='robodojo':assert row['seeds']=={k:e['identity'][k] for k in SEEDS}
        for method in METHODS:
            actual=metrics([r for r in own if r['method']==method])
            assert actual==value[cohort]['methods'][method]['reproduction']
            if cohort=='robolab':
                assert value['robolab']['recorded_budget_observations'][method]==[budget_observation([r for r in own if r['method']==method],b) for b in (180,500)]
                assert value['robolab']['max_decisions_by_method'][method]==sorted({integer(r['max_decisions']) for r in own if r['method']==method})
                tasks=[t for t in value['robolab']['tasks'] if t['method']==method]
                assert len(tasks)==10 and {t['task'] for t in tasks}=={r['task'] for r in own}
                for task in tasks:
                    matched=[r for r in own if r['method']==method and r['task']==task['task']]
                    assert task['episodes']==len(matched)==5
                    assert integer(task['original_successes'])<=5
                    assert task['reproduction_successes']==sum(r['success'] for r in matched)
                assert value['robolab']['methods'][method]['original_successes']==sum(t['original_successes'] for t in tasks)
    own=[r for r in current if r['cohort']=='robodojo']
    assert value['robodojo']['case_alignment']==compare_cases(old,own)
    assert value['robodojo']['tasks']==task_comparison(old,own)
    for method in METHODS:assert metrics([r for r in old if r['method']==method])==value['robodojo']['methods'][method]['original']
    assert (docs/'blog-comparison.html').read_text()==render(value)
    assert 'blog-comparison.html' in (docs/'scenes.html').read_text()

def render(value):
    E=html.escape
    def cell(value):
        if isinstance(value,dict):
            assert re.fullmatch(r'data/gpt-episodes/[A-Za-z0-9_.-]+\.json',value['href'])
            return '<a href="'+E(value['href'],quote=True)+'">'+E(value['text'])+'</a>'
        return E(str(value))
    def table(headers,rows):return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+E(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+cell(c)+'</td>' for c in row)+'</tr>' for row in rows)+'</tbody></table></div>'
    def score(m):return '未知' if m['mean_score'] is None else f'{m["mean_score"]*100:.2f}（n={m["score_samples"]}）'
    def usage(m):return '未知' if m['tokens'] is None else f'{m["tokens"]["totalTokens"]:,}（n={m["token_samples"]}）'
    rows=[]
    for method,values in value['robodojo']['methods'].items():
        a,b=values['original'],values['reproduction']
        rows.append([METHODS[method],f'{a["successes"]}/{a["episodes"]}',f'{b["successes"]}/{b["episodes"]}',score(a),score(b),f'{a["control_steps"]:,} / {b["control_steps"]:,}',f'{a["executed_chunks"]:,} / {b["executed_chunks"]:,}',usage(a)+' / '+usage(b)])
    main=table(['方法','原成功数','本次成功数','原Score×100','本次Score×100','控制步 原/本次','执行段 原/本次','累计Token 原/本次'],rows)
    a=value['robodojo']['methods']['pi05_plus_gpt']['original'];b=value['robodojo']['methods']['pi05_plus_gpt']['reproduction']
    correction=f'Hybrid 原纠错 {a["corrected_steps"]:,}/{a["control_steps"]:,} 步（{a["correction_fraction"]:.2%}）；本次 {b["corrected_steps"]:,}/{b["control_steps"]:,} 步（{b["correction_fraction"]:.2%}）。纠错按实际执行的 edit/EEF 控制步计数。累计Token包含缓存输入，不能直接换算费用；执行段只计 executed_steps&gt;0，与作者提取口径一致。'
    tasks=table(['RoboDojo任务','方法','原成功数/5','本次成功数/5'],[[t['task'],METHODS[t['method']],t['original']['successes'],t['reproduction']['successes']] for t in value['robodojo']['tasks']])
    lab=table(['RoboLab任务','方法','原成功数/5','本次成功数/5'],[[t['task'],METHODS[t['method']],t['original_successes'],t['reproduction_successes']] for t in value['robolab']['tasks']])
    budgets=table(['方法','观察到的决策数','已成功终止','已原生失败','在已录轨迹中尚未终止'],[[METHODS[m],r['budget'],r['success_already_observed'],r['native_failure_already_observed'],r['still_unfinished_in_recorded_prefix']] for m,rows in value['robolab']['recorded_budget_observations'].items() for r in rows])
    alignment=value['robodojo']['case_alignment'];paired=table(['共同案例','方法','原成功','本次成功','原Score','本次Score','本次证据'],[[r['case_id'],METHODS[r['method']],'是' if r['original_success'] else '否','是' if r['reproduction_success'] else '否',r['original_score'] if r['original_score'] is not None else '缺失',r['reproduction_score'],dict(href=r['evidence'],text='案例JSON')] for r in alignment['cases']])
    changed='；'.join(METHODS[m]+f'：{r["changed_success_outcomes"]}/{r["episodes"]}条成功判定不同' for m,r in alignment['methods'].items())
    document='<h2>RoboLab决策预算观察</h2><p>本次决策上限100000，主要受原生控制时域约束。原报告部分Direct回合采用180/500决策。下表只观察已有轨迹在相应决策数内是否已终止，不能当作新预算的实际成功率；尚未终止不计为失败。</p>'+budgets
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>与原 blog 的逐项对照</title><style>body{font:16px/1.65 system-ui,sans-serif;max-width:1200px;margin:auto;padding:24px;color:#182238;background:#f6f8fb}h1,h2{line-height:1.3}a{color:#1555b0}.panel{background:white;border:1px solid #dce2ec;border-radius:12px;padding:18px;margin:20px 0}.scroll{overflow-x:auto}table{border-collapse:collapse;min-width:620px;width:100%}th,td{text-align:left;border-bottom:1px solid #e1e6ef;padding:9px;font-size:14px}th{background:#eef2f9}li{margin:8px 0}details{margin:20px 0}code{overflow-wrap:anywhere}@media(max-width:600px){body{padding:14px}}</style><main><a href="scenes.html">← 复现报告</a><h1>与原 blog 的逐项对照</h1><div class="panel"><strong>两方法200回合执行和审计已完成；历史等价性尚未证明。</strong><p>本页比较独立运行与作者公开快照。相同总成功数不能证明案例结果或控制实现一致，数值差异也不能单独定位原因。</p><p><a href="data/blog-comparison.json">下载完整对照 JSON</a> · <a href="data/reproduction-completion.json">查看原始执行验收证明</a> · <a href="https://github.com/anonymous-report-421/GPT-as-Policy">作者公开源码</a></p></div><h2>RoboDojo 主结果与执行统计</h2>'+main+'<p>'+correction+'</p><h2>逐任务比较</h2>'+tasks+lab+document+'<h2>共同案例对照</h2><p>共同49对、98条方法回合的案例ID与五个种子字段相同；完整历史物理初态未核验。'+E(changed)+'。layout4与layout5保持分列，未合并为相同案例。</p><details><summary>展开98条共同案例</summary>'+paired+'</details><h2>协议与来源限制</h2><ul>'+''.join('<li>'+E(t)+'</li>' for t in value['limitations'])+'</ul><p>原RoboLab总数为 Direct49/50、Hybrid46/50；本次同为49/50、46/50，逐任务表展示了失败分布差异。两批历史初态未配对，不能计算逐seed一致率。</p><p>原数据固定提交：<code>'+E(value['original_sources']['GPT-as-Policy']['commit'])+'</code>；网站数据提交：<code>'+E(value['original_sources']['public-website']['commit'])+'</code>。文件SHA与来源URL见对照JSON；新的统计提取证据独立封存，原200回合验收证明不改写。</p></main></html>'

def build(source,out):
    value=prepare(source,out)
    if value is None:return None
    (out/'data/blog-comparison.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    (out/'blog-comparison.html').write_text(render(value))
    from render_gpt_progress import render as render_progress
    render_progress(out);render_progress(out,valid=True,update_board=False)
    print(json.dumps(dict(status='blog_comparison_verified',historical_equivalence_verified=False,common_case_pairs=value['robodojo']['case_alignment']['common_case_pairs'],native_episodes=200)))
    return value

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);args=ap.parse_args();build(args.source,args.out)
