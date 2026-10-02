"""Publish one verified source-only infrastructure snapshot, with no runtime logs."""
import hashlib
import json
from pathlib import Path,PurePosixPath
import re
import shutil
import tarfile

SECRET=re.compile(rb'-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----|github_pat_[A-Za-z0-9_]{30,}|ghp_[A-Za-z0-9]{30,}|sk-(?:proj-)?[A-Za-z0-9_-]{24,}|eyJ[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]{20,}\.')


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
        assert manifest['full_reproduction_complete'] is False
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
    destination=out/'downloads'/archive.name;destination.parent.mkdir(parents=True,exist_ok=True)
    if not destination.exists() or hashlib.sha256(destination.read_bytes()).hexdigest()!=receipt['sha256']:
        temporary=destination.with_suffix('.tmp');shutil.copyfile(archive,temporary);temporary.replace(destination)
    value=dict(schema='gpt_policy_infrastructure_bundle.v1',archive='downloads/'+archive.name,
        bytes=len(data),sha256=receipt['sha256'],files=receipt['files'],created_utc=manifest['created_utc'],
        active_methods=manifest['active_methods'],full_reproduction_complete=False,contents_verified=True)
    (out/'data/infrastructure-bundle.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return value
