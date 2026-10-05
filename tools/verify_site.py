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

def verify_gpt_dataset(root, progress, manifest_name):
    assert progress['schema']=='gpt_policy_progress.v2'
    from build_gpt_site import summarize, task_summaries, METHODS
    episodes=progress['episodes']; cases=progress['cases']
    assert len(cases)==50 and len({c['case_id'] for c in cases})==50
    assert len({(e['case_id'],e['method']) for e in episodes})==len(episodes)
    assert summarize(cases,episodes)==progress['summary']
    assert task_summaries(cases,episodes)==progress['task_summary']
    lookup={e['id']:e for e in episodes}
    manifest=json.loads((root/manifest_name).read_text())
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
    return episodes


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
    episodes=verify_gpt_dataset(root, progress, 'data/gpt-media-manifest.json')
    from build_robolab_methods import summarize as summarize_robolab
    supplemental=json.loads((root/'data/robolab-methods-progress.json').read_text())
    assert len(supplemental['cases'])==50 and len({c['case_id'] for c in supplemental['cases']})==50
    assert supplemental['summary']==summarize_robolab(supplemental['cases'],supplemental['episodes'])
    assert supplemental['summary']==progress['supplementary']['robolab']['summary']
    infrastructure=Links();infrastructure.feed((root/'scenes.html').read_text())
    assert 'robolab-infra-progress' in infrastructure.ids
    count=supplemental['summary']['complete_method_runs']
    pairs=supplemental['summary']['completed_pairs']
    assert f'{count} / 100 条已完整审计，{pairs} / 50 对已完成' in (root/'scenes.html').read_text()
    for episode in supplemental['episodes']:
        audit=json.loads((root/episode['audit']).read_text())
        assert episode==json.loads((root/episode['evidence']).read_text())
        assert episode['eligible'] is True and audit['verified'] is True and audit['complete_episode'] is True
        assert audit['method']==episode['method'] and audit['native_actions']==episode['control_steps']
        assert audit['terminal']=={k:episode[k] for k in ('success','terminated','truncated')}
        assert hashlib.sha256((root/episode['video']).read_bytes()).hexdigest()==episode['video_sha256']
        assert hashlib.sha256((root/episode['audit']).read_bytes()).hexdigest()==episode['audit_sha256']
    bundle=progress.get('infrastructure')
    if bundle:
        assert bundle==json.loads((root/'data/infrastructure-bundle.json').read_text())
        assert bundle['contents_verified'] is True and bundle['full_reproduction_complete'] is False
        archive=root/bundle['archive']
        assert archive.stat().st_size==bundle['bytes']
        assert hashlib.sha256(archive.read_bytes()).hexdigest()==bundle['sha256']
        assert 'infra-bundle-download' in (root/'scenes.html').read_text()
    assert progress['snapshot'] in (root/'scenes.html').read_text()
    supplementary = progress.get('supplementary', {}).get('robolab')
    if supplementary:
        assert set(supplementary) == {'planned_pairs','planned_method_runs','status','task','seed','method',
            'started_utc','results_eligible','action_audit_status','direct_implementation_status','cohort','observed_control_steps','last_prefix_audit','summary','report'}
        assert supplementary['results_eligible'] is (supplementary['summary']['complete_method_runs']>0)
        assert supplementary['planned_pairs']==50 and supplementary['planned_method_runs']==100
        assert 'robolab-methods-progress' in (root/'scenes.html').read_text()
        if supplementary['last_prefix_audit']:
            prefix=json.loads((root/supplementary['last_prefix_audit']['evidence']).read_text())
            assert prefix['verified'] is True and prefix['complete_episode'] is False
            assert prefix['native_actions']==supplementary['last_prefix_audit']['native_actions']
    assert f"完整可计分主方法回合：{len(episodes)} / 100" in (root/'scenes.html').read_text()
    valid_path = root/'data/gpt-methods-valid-progress.json'
    valid_episodes = []
    if valid_path.is_file():
        selected = json.loads(valid_path.read_text())
        valid_episodes = verify_gpt_dataset(root, selected, 'data/gpt-valid-media-manifest.json')
        cohort = selected['cohort']
        metadata = json.loads((root/'data/gpt-valid-cohort.json').read_text())
        assert {k: v for k, v in metadata.items() if k != 'cases'} == cohort
        assert cohort['original_summary'] == progress['summary']
        assert cohort['diagnostic_episodes_in_denominator'] is False and cohort['overlapping_cohorts'] is True
        original_ids = {c['case_id'] for c in progress['cases']}
        selected_ids = {c['case_id'] for c in selected['cases']}
        assert original_ids - selected_ids == {cohort['replacement']['removed']}
        assert selected_ids - original_ids == {cohort['replacement']['added']}
        identities = {c['case_id']: c for c in metadata['cases']}
        assert len(identities) == 50 and set(identities) == selected_ids
        assert all(c['identity'] == identities[c['case_id']] for c in selected['cases'])
        old = {(e['case_id'], e['method']): e for e in episodes}
        assert all(e == old[(e['case_id'], e['method'])] for e in valid_episodes if e['case_id'] in original_ids)
        assert 'gpt-methods-valid.html' in (root/'scenes.html').read_text()
        assert 'gpt-methods.html' in (root/'gpt-methods-valid.html').read_text()
    names = ('index.html','scenes.html','robolab.html','gpt-methods.html','robolab-methods.html')
    if valid_path.is_file(): names += ('gpt-methods-valid.html',)
    for name in names:
        parser=Links();parser.feed((root/name).read_text())
        for link in parser.links:
            url=urlsplit(link)
            if url.scheme or url.netloc:continue
            if url.path:
                target=(root/unquote(url.path)).resolve();target.relative_to(root.resolve());assert target.is_file(),link
            elif url.fragment:assert unquote(url.fragment) in parser.ids,link
        assert parser.videos==(len(valid_episodes) if name=='gpt-methods-valid.html' else len(episodes) if name=='gpt-methods.html' else len(robolab) if name=='robolab.html' else len(supplemental['episodes']) if name=='robolab-methods.html' else sum(bool(r['video']) for r in rows))
    assert (root/'index.html').read_bytes()==(root/'scenes.html').read_bytes()
    forbidden=(r'/home/',r'/mnt/',r'github_pat_[A-Za-z0-9_]+',r'ghp_[A-Za-z0-9]+',r'127\.0\.0\.1',r'BEGIN .*PRIVATE KEY',r'Bearer\s+[A-Za-z0-9_.-]{12,}')
    for path in root.rglob('*'):
        if not path.is_file():continue
        assert not path.is_symlink(),path
        assert path.stat().st_size<95*1024*1024,path
        if path.suffix in ('.html','.js','.css','.json','.md'):
            text=path.read_text()
            for pattern in forbidden:assert not re.search(pattern,text),(path,pattern)
    print(json.dumps(dict(status='passed',cases=len(rows),videos=sum(bool(r['video']) for r in rows),robolab_complete_episodes=len(robolab),eligible_prefix15=len(valid),successes=summary['successes'],gpt_complete_method_runs=len(episodes),gpt_completed_pairs=progress['summary']['completed_pairs'],gpt_valid_method_runs=len(valid_episodes) if valid_path.is_file() else None,checks=['internal_links','unique_ids','score_denominators','public_export_fields','file_sizes','lazy_video','retained_original_cohort']),indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();verify(a.root)
