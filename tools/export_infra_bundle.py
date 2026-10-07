"""Publish one verified source-only infrastructure snapshot, with no runtime logs."""
import hashlib
import json
from pathlib import Path,PurePosixPath
import re
import shutil
import tarfile

SECRET=re.compile(rb'-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----|github_pat_[A-Za-z0-9_]{30,}|ghp_[A-Za-z0-9]{30,}|sk-(?:proj-)?[A-Za-z0-9_-]{24,}|eyJ[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]{20,}\.')


def validate_completion_certificate(data, binding):
    """Validate the sealed gate receipt, not infer completion from bundle size."""
    assert hashlib.sha256(data).hexdigest()==binding['sha256']
    proof=json.loads(data)
    assert proof['schema']=='gpt_policy_full_reproduction_gate.v1'
    assert proof['status']=='complete' and proof['full_reproduction_complete'] is True
    assert proof['original_artifacts_verified'] is True and proof['public_episode_artifacts_verified'] is True
    assert proof['published_commit']==binding['published_commit']
    assert re.fullmatch('[a-f0-9]{40}',proof['published_commit'])
    assert proof['verified_native_episodes']==200 and proof['active'] is None
    assert set(proof['cohorts'])=={'robodojo','robolab'}
    for counts in proof['cohorts'].values():
        assert counts==dict(complete_method_runs=100,completed_pairs=50,remaining_method_runs=0,remaining_pairs=0)
    episodes=proof['original_episodes']
    assert len(episodes)==200
    for cohort in proof['cohorts']:
        rows=[e for e in episodes if e['cohort']==cohort]
        pairs={e['case_id'] for e in rows}
        assert len(rows)==100 and len(pairs)==50
        assert {(e['case_id'],e['method']) for e in rows}=={(c,m) for c in pairs for m in ('gpt_only','pi05_plus_gpt')}
    retained=proof['retained_original_episodes']
    assert len(retained)==1 and proof['original_robodojo']['complete_method_runs']==99
    for row in episodes+retained:
        assert row['audit_inputs']>0
        assert all(re.fullmatch('[a-f0-9]{64}',row[k]) for k in ('audit_sha256','original_video_sha256'))
    public=proof['public_files']
    assert len(public)>=804 and len({r['path'] for r in public})==len(public)
    assert all(r['bytes']>0 and re.fullmatch('[a-f0-9]{64}',r['sha256']) for r in public)
    assert proof['exact_commit_ci'] and all(r['conclusion']=='success' for r in proof['exact_commit_ci'])
    assert proof['finished_utc'] and proof['limitation']
    return proof


def export_bundle(source,out):
    path=source/'deliverables/infrastructure_bundle_verification.json'
    if not path.exists():return None
    receipt=json.loads(path.read_text());relative=PurePosixPath(receipt['path'])
    assert relative.parent==PurePosixPath('deliverables') and re.fullmatch(r'infrastructure_bundle_20[0-9]{6}(?:T[0-9]{6}Z)?\.tar\.gz',relative.name)
    archive=source/relative;data=archive.read_bytes()
    assert receipt['contents_verified'] is True and len(data)==receipt['bytes'] and len(data)<20*1024*1024
    assert hashlib.sha256(data).hexdigest()==receipt['sha256']
    with tarfile.open(archive) as tar:
        members=tar.getmembers();names=[m.name for m in members]
        assert len(names)==len(set(names)) and all(m.isfile() for m in members)
        assert all(0<=m.size<=64*1024*1024 for m in members) and sum(m.size for m in members)<128*1024*1024
        manifest=json.loads(tar.extractfile('manifest.json').read())
        assert manifest['active_methods']==['gpt_only','pi05_plus_gpt']
        assert type(manifest['full_reproduction_complete']) is bool
        assert set(names)=={'manifest.json'}|{row['path'] for row in manifest['files']}
        assert len(manifest['files'])==receipt['files']
        expected={row['path']:row for row in manifest['files']}
        for member in members:
            name=PurePosixPath(member.name)
            assert not name.is_absolute() and '..' not in name.parts
            assert name.name not in {'auth.json','config.toml','runtime.env','rpc_out.jsonl','rpc_in.jsonl'}
            assert not any(part in {'runtime_db','runtime_logs','codex_workspace'} for part in name.parts)
            content=tar.extractfile(member).read();assert not SECRET.search(content),member.name
            if member.name in expected:
                row=expected[member.name]
                assert len(content)==row['size'] and hashlib.sha256(content).hexdigest()==row['sha256']
        completion=manifest.get('completion_certificate')
        if manifest['full_reproduction_complete']:
            assert completion and completion['path'] in expected
            validate_completion_certificate(tar.extractfile(completion['path']).read(),completion)
            completion_data=tar.extractfile(completion['path']).read()
        else:
            assert completion is None, 'A partial snapshot must not claim a completion receipt'
    destination=out/'downloads'/archive.name;destination.parent.mkdir(parents=True,exist_ok=True)
    if not destination.exists() or hashlib.sha256(destination.read_bytes()).hexdigest()!=receipt['sha256']:
        temporary=destination.with_suffix('.tmp');shutil.copyfile(archive,temporary);temporary.replace(destination)
    value=dict(schema='gpt_policy_infrastructure_bundle.v1',archive='downloads/'+archive.name,
        bytes=len(data),sha256=receipt['sha256'],files=receipt['files'],created_utc=manifest['created_utc'],
        active_methods=manifest['active_methods'],full_reproduction_complete=manifest['full_reproduction_complete'],contents_verified=True)
    if completion:
        value['completion_certificate']=dict(completion,public_path='data/reproduction-completion.json')
        (out/'data/reproduction-completion.json').write_bytes(completion_data)
    (out/'data/infrastructure-bundle.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return value
