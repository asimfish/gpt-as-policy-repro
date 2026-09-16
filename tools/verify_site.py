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
    gpt=json.loads((root/'data/gpt-methods-progress.json').read_text())['direct']
    proof=json.loads((root/gpt['audit']).read_text())
    assert proof['verified'] and not proof['complete_episode'] and not gpt['complete'] and not gpt['eligible']
    assert proof['native_actions']==gpt['control_steps']==940
    assert hashlib.sha256((root/gpt['video']).read_bytes()).hexdigest()==gpt['video_sha256']
    for name in ('index.html','scenes.html','robolab.html','gpt-methods.html'):
        parser=Links();parser.feed((root/name).read_text())
        for link in parser.links:
            url=urlsplit(link)
            if url.scheme or url.netloc:continue
            if url.path:
                target=(root/unquote(url.path)).resolve();target.relative_to(root.resolve());assert target.is_file(),link
            elif url.fragment:assert unquote(url.fragment) in parser.ids,link
        assert parser.videos==(1 if name=='gpt-methods.html' else len(robolab) if name=='robolab.html' else sum(bool(r['video']) for r in rows))
    assert (root/'index.html').read_bytes()==(root/'scenes.html').read_bytes()
    forbidden=(r'/home/',r'/mnt/',r'github_pat_[A-Za-z0-9_]+',r'ghp_[A-Za-z0-9]+',r'127\.0\.0\.1',r'BEGIN .*PRIVATE KEY',r'Bearer\s+[A-Za-z0-9_.-]{12,}')
    for path in root.rglob('*'):
        if not path.is_file():continue
        assert not path.is_symlink(),path
        assert path.stat().st_size<95*1024*1024,path
        if path.suffix in ('.html','.js','.css','.json','.md'):
            text=path.read_text()
            for pattern in forbidden:assert not re.search(pattern,text),(path,pattern)
    print(json.dumps(dict(status='passed',cases=len(rows),videos=sum(bool(r['video']) for r in rows),robolab_complete_episodes=len(robolab),eligible_prefix15=len(valid),successes=summary['successes'],checks=['internal_links','unique_ids','score_denominators','public_export_fields','file_sizes','lazy_video']),indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();verify(a.root)
