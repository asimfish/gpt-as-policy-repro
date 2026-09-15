"""Publish only completed RoboLab episodes with full independent action audits."""
import argparse
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
import subprocess
from build_site import digest, read, write


def build(root, out):
    records=[]
    for result_path in sorted(root.glob('mainskill_robolab_pi05*/**/rollout/result.json')):
        run=result_path.parents[1];audit_path=run/'action_audit.json'
        if not audit_path.exists():continue
        audit=read(audit_path);result=read(result_path)
        assert audit['verified'] and audit['complete_episode'] and result['complete']
        assert result['terminated'] or result['truncated']
        assert audit['native_actions']==result['control_steps'] and audit['terminal']['success']==result['success']
        metadata=read(result_path.with_name('run.json'));identity=read(result_path.with_name('policy_identity.json'))
        uid='robolab_pi05_'+metadata['task']+'_seed'+str(metadata['seed'])+'_'+run.name
        assert re.fullmatch(r'[A-Za-z0-9_-]+',uid)
        source=run/'sim/sensors.mp4'
        info=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=nb_frames,width,height,duration','-of','json',str(source)],text=True))['streams'][0]
        assert int(info['nb_frames'])==result['native']['video_frames']
        video=out/'media'/f'{uid}.mp4';poster=video.with_suffix('.jpg');video.parent.mkdir(exist_ok=True)
        if not video.exists():
            temp=video.with_suffix('.tmp.mp4')
            subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(source),'-an','-vf','scale=1440:-2,fps=15','-c:v','libx264','-preset','fast','-crf','26','-threads','2','-movflags','+faststart','-y',str(temp)],check=True);temp.replace(video)
        if not poster.exists():
            subprocess.run(['ffmpeg','-nostdin','-v','error','-ss','0','-i',str(video),'-frames:v','1','-q:v','3','-threads','1','-y',str(poster)],check=True)
        pilot=run.parent.name=='mainskill_robolab_pi05'
        record=dict(id=uid,task=metadata['task'],seed=metadata['seed'],success=result['success'],control_steps=result['control_steps'],
            predictions=audit['queries'],complete=True,scope='pilot_not_in_50_case_cohort' if pilot else 'new_fixed_seed_cohort',
            historical_paired_benchmark=False,terminated=result['terminated'],truncated=result['truncated'],
            initial_state_sha256=audit['initial_state_sha256'],checkpoint_manifest_sha256=audit['checkpoint_manifest_sha256'],
            policy={k:identity[k] for k in ('config','action_horizon','openpi_revision')},
            video='media/'+video.name,poster='media/'+poster.name,duration_seconds=float(info['duration']),
            native_video_frames=int(info['nb_frames']),source_video_sha256=digest(source),video_sha256=digest(video),
            audit='data/robolab/'+uid+'-audit.json',evidence='data/robolab/'+uid+'.json')
        write(out/record['audit'],audit);write(out/record['evidence'],record);records.append(record)
    assert records,'No completely audited native RoboLab episode'
    now=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    write(out/'data/robolab-report.json',dict(generated_at=now,episodes=records,complete_episodes=len(records),
        interpretation='Independent native rollouts. Pilot is separate from the 50-case cohort; historical paired benchmark not reproduced yet.'))
    cards=[]
    for row in records:
        e=html.escape;status='原生成功' if row['success'] else '原生失败'
        scope='完整链路验证 · 不计入 50 案例队列' if row['scope'].startswith('pilot') else '新固定种子案例'
        cards.append(f'''<article class="panel report-section" id="{e(row['id'])}"><div class="panel-head" style="flex-wrap:wrap"><h2>{e(row['task'])} · seed {row['seed']}</h2><span class="badge {'success' if row['success'] else 'pending'}">{status}</span></div><p>{scope}</p><video controls playsinline preload="none" poster="{e(row['poster'])}" style="width:100%;height:auto" aria-label="RoboLab 官方 π0.5 完整原生回放"><source src="{e(row['video'])}" type="video/mp4"></video><p class="muted">本次执行的主相机与腕相机 · 完整时间线 · {row['duration_seconds']:.2f} 秒仿真视频</p><div class="stats robolab-stats"><article><span>原生控制步</span><strong>{row['control_steps']:,}</strong></article><article><span>真实模型推理</span><strong>{row['predictions']}</strong></article><article><span>动作最大绝对误差</span><strong>0</strong></article></div><p>每次预测均与独立原生 chunk 记录核对，包含输入图像、关节状态、动作、步序及终止回执。任务由模拟器原生成功条件判定。</p><p><a class="text-link" href="{e(row['evidence'])}">结果与视频校验 ↗</a> · <a class="text-link" href="{e(row['audit'])}">完整动作审计 ↗</a></p></article>''')
    document=f'''<!doctype html><html lang="zh-CN" data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RoboLab · 独立原生回合</title><link rel="icon" href="assets/favicon.svg"><link rel="stylesheet" href="assets/site.css"><style>.robolab-stats{{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:640px){{.robolab-stats{{grid-template-columns:1fr}}}}</style></head><body><header class="topbar"><div class="wrap top-inner"><a class="brand" href="scenes.html">GPT-AS-POLICY</a><a class="text-link" href="scenes.html">返回报告 ↗</a></div></header><main class="wrap"><section class="report-section"><p class="eyebrow accent">ROBOLAB / A100 / OFFICIAL PI0.5</p><h1>我们自己的 RoboLab 回合</h1><p class="hero-lead">官方权重 → 原生观测 → 模型推理 → 原生执行 → 独立动作审计。</p><p>已收录 {len(records)} 条完整审计轨迹。这里的结果来自本项目实际运行；50 案例与跨方法比较尚未完成，不据此估计论文整体成功率。</p><p>先导回合单独标记，后续失败回合同样完整保留。当前 BlocksInBinTask 的 seed 0 与 seed 1 初始物理状态哈希相同：原生默认重置没有自动生成不同布局。初始状态相同也不保证渲染观测和闭环轨迹完全相同。</p><p class="updated">数据快照 · {now}</p></section>{''.join(cards)}<p><a href="data/robolab-report.json">下载本页数据 JSON ↗</a></p></main></body></html>'''
    (out/'robolab.html').write_text(document)
    print(json.dumps(dict(complete_robolab_episodes=len(records),native_controls=sum(r['control_steps'] for r in records))))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();build(a.source.resolve(),a.out.resolve())
