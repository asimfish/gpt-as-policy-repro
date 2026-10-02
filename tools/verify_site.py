"""Check published data, all internal links, and the public export boundary."""
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urlsplit,unquote

class Links(HTMLParser):
    def __init__(self):super().__init__();self.links=[];self.ids=set();self.videos=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if 'id' in a:
            assert a['id'] not in self.ids,('duplicate id',a['id'])
            self.ids.add(a['id'])
        for key in ('src','href','poster'):
            if key in a:self.links.append(a[key])
        if tag=='video':self.videos+=1;assert a.get('preload')=='none'

def verify(root):
    report=json.loads((root/'data/report.json').read_text());rows=report['episodes']
    summary=report['summary']['pi05_prefix15'];prefix=[r for r in rows if r['method']=='pi05_prefix15']
    valid=[r for r in prefix if r['eligible']]
    assert len(prefix)==50
    assert len(valid)==summary['evaluated']==48
    assert sum(r['success'] is True for r in valid)==summary['successes']==10
    assert len(report['tasks'])==10
    assert len({r['id'] for r in rows})==len(rows)
    for row in rows:
        evidence=json.loads((root/row['evidence']).read_text())
        assert evidence['id']==row['id'] and evidence['eligible']==row['eligible']
        if row['status']=='excluded':assert not row['eligible'] and row['score'] is None
    robolab=json.loads((root/'data/robolab-report.json').read_text())['episodes']
    assert robolab
    for row in robolab:
        evidence=json.loads((root/row['evidence']).read_text());audit=json.loads((root/row['audit']).read_text())
        assert evidence==row and row['complete'] and audit['verified'] and audit['complete_episode']
        assert row['control_steps']==audit['native_actions'] and row['predictions']==audit['queries']
        assert row['success']==audit['terminal']['success'] and (row['terminated'] or row['truncated'])
        assert hashlib.sha256((root/row['video']).read_bytes()).hexdigest()==row['video_sha256']
    progress=json.loads((root/'data/gpt-methods-progress.json').read_text())
    assert progress['schema']=='gpt_policy_progress.v2'
    from build_gpt_site import summarize, task_summaries, METHODS
    episodes=progress['episodes']; cases=progress['cases']
    assert len(cases)==50 and len({c['case_id'] for c in cases})==50
    assert len({(e['case_id'],e['method']) for e in episodes})==len(episodes)
    assert summarize(cases,episodes)==progress['summary']
    assert task_summaries(cases,episodes)==progress['task_summary']
    lookup={e['id']:e for e in episodes}
    manifest=json.loads((root/'data/gpt-media-manifest.json').read_text())
    assert {r['id'] for r in manifest}==set(lookup)
    for episode in episodes:
        assert episode['complete'] is True and episode['eligible'] is True
        assert type(episode['success']) is bool
        assert episode['terminated'] is True or episode['truncated'] is True
        evidence=json.loads((root/episode['evidence']).read_text())
        assert evidence==episode
        audit=json.loads((root/episode['audit']).read_text())
        assert audit['verified'] is True and audit['complete_episode'] is True
        assert audit['scope']=='complete_native_episode'
        assert (audit['model'],audit['reasoning_effort'])==('gpt-6-astra','xhigh')
        assert audit['native_actions']==episode['control_steps'] and audit['decisions']==episode['decisions']
        assert audit['terminal']=={k:episode[k] for k in ('success','terminated','truncated')}
        assert audit['native_score']==episode['score']
        assert audit['result_identity']==episode['identity']
        if episode['method']=='gpt_only':assert audit['pi05_inference_calls']==0
        else:assert audit['actions_by_mode']==episode['actions_by_mode'] and sum(audit['actions_by_mode'].values())==episode['control_steps']
        for path,sha in ((episode['video'],episode['video_sha256']),(episode['audit'],episode['audit_sha256'])):
            assert hashlib.sha256((root/path).read_bytes()).hexdigest()==sha
        item=next(r for r in manifest if r['id']==episode['id'])
        assert all(item[k]==episode[k] for k in item)
    for case in cases:
        for method in METHODS:
            value=case['methods'][method]
            if value['episode_id']:
                episode=lookup[value['episode_id']]
                assert (episode['case_id'],episode['method'])==(case['case_id'],method)
                assert episode['identity']==case['identity'] and value['status']=='complete'
            else:assert value['status']!='complete'
        assert case['paired_complete']==all(case['methods'][m]['episode_id'] for m in METHODS)
    assert sum(a['status']=='interrupted' for a in progress['attempts'])==progress['interruptions']['count']
    for attempt in progress['attempts']:
        if attempt['status'] in ('interrupted','audit_pending'):assert attempt['eligible'] is False
        if attempt.get('audit'):
            audit=json.loads((root/attempt['audit']).read_text())
            assert audit['verified'] is True and audit['complete_episode'] is False
            assert audit['native_actions']==attempt['audited_control_steps']<=attempt['control_steps']
        if attempt.get('video'):
            assert hashlib.sha256((root/attempt['video']).read_bytes()).hexdigest()==attempt['video_sha256']
    assert progress['snapshot'] in (root/'scenes.html').read_text()
    supplementary = progress.get('supplementary', {}).get('robolab')
    if supplementary:
        assert set(supplementary) == {'planned_pairs','planned_method_runs','status','task','seed','method',
            'started_utc','results_eligible','action_audit_status','direct_implementation_status','cohort','observed_control_steps','last_prefix_audit'}
        assert supplementary['results_eligible'] is False
        assert supplementary['planned_pairs']==50 and supplementary['planned_method_runs']==100
        assert 'robolab-methods-progress' in (root/'scenes.html').read_text()
        if supplementary['last_prefix_audit']:
            prefix=json.loads((root/supplementary['last_prefix_audit']['evidence']).read_text())
            assert prefix['verified'] is True and prefix['complete_episode'] is False
            assert prefix['native_actions']==supplementary['last_prefix_audit']['native_actions']
    assert f"完整可计分主方法回合：{len(episodes)} / 100" in (root/'scenes.html').read_text()
    for name in ('index.html','scenes.html','robolab.html','gpt-methods.html'):
        parser=Links();parser.feed((root/name).read_text())
        for link in parser.links:
            url=urlsplit(link)
            if url.scheme or url.netloc:continue
            if url.path:
                target=(root/unquote(url.path)).resolve();target.relative_to(root.resolve());assert target.is_file(),link
            elif url.fragment:assert unquote(url.fragment) in parser.ids,link
        assert parser.videos==(len(episodes) if name=='gpt-methods.html' else len(robolab) if name=='robolab.html' else sum(bool(r['video']) for r in rows))
    assert (root/'index.html').read_bytes()==(root/'scenes.html').read_bytes()
    forbidden=(r'/home/',r'/mnt/',r'github_pat_[A-Za-z0-9_]+',r'ghp_[A-Za-z0-9]+',r'127\.0\.0\.1',r'BEGIN .*PRIVATE KEY',r'Bearer\s+[A-Za-z0-9_.-]{12,}')
    for path in root.rglob('*'):
        if not path.is_file():continue
        assert not path.is_symlink(),path
        assert path.stat().st_size<95*1024*1024,path
        if path.suffix in ('.html','.js','.css','.json','.md'):
            text=path.read_text()
            for pattern in forbidden:assert not re.search(pattern,text),(path,pattern)
    print(json.dumps(dict(status='passed',cases=len(rows),videos=sum(bool(r['video']) for r in rows),robolab_complete_episodes=len(robolab),eligible_prefix15=len(valid),successes=summary['successes'],gpt_complete_method_runs=len(episodes),gpt_completed_pairs=progress['summary']['completed_pairs'],checks=['internal_links','unique_ids','score_denominators','public_export_fields','file_sizes','lazy_video']),indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();verify(a.root)
