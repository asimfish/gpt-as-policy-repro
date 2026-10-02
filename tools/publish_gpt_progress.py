"""One locked, verified publication pulse. Authentication remains in Git's helper."""
import argparse
import base64
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request


GENERATED = ('docs/index.html', 'docs/scenes.html', 'docs/gpt-methods.html',
             'docs/data/gpt-methods-progress.json', 'docs/data/gpt-media-manifest.json',
             'docs/data/gpt-episodes/', 'docs/data/gpt-attempts/', 'docs/media/gpt-episodes/', 'docs/assets/gpt.css', 'docs/assets/gpt.js')


def git(repo, *args, env=None, stdin=None):
    result = subprocess.run(['git', '-C', str(repo), *args], input=stdin, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=180)
    if result.returncode:
        # Credential-helper or transport errors could contain sensitive headers.
        raise RuntimeError('Git operation failed: ' + args[0] + '; exit ' + str(result.returncode))
    return result.stdout.strip()


def owned(path):
    return any(path.startswith(p) if p.endswith('/') else path == p for p in GENERATED)


def check_worktree(repo):
    assert git(repo, 'branch', '--show-current') == 'docs/site', 'Unexpected publication branch'
    assert git(repo, 'remote', 'get-url', 'origin') == 'https://github.com/asimfish/gpt-as-policy-repro.git'
    assert not git(repo, 'diff', '--cached', '--name-only'), 'User staging must be preserved'
    result = subprocess.run(['git', '-C', str(repo), 'status', '--porcelain=v1', '-z', '--untracked-files=all'],
                            stdout=subprocess.PIPE, check=True, timeout=180)
    for record in result.stdout.decode().split('\0'):
        if not record:
            continue
        assert record[:2].strip() in ('M', '??'), 'Unexpected rename, deletion or staged change'
        assert owned(record[3:]), 'Source or unrelated changes present; publication pulse deferred'


def credential_env(credentials_repo):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_TRACE') and k != 'GIT_CURL_VERBOSE'}
    value = git(credentials_repo, 'credential', 'fill', env=env,
                stdin='protocol=https\nhost=github.com\n\n')
    credential = dict(line.split('=', 1) for line in value.splitlines() if '=' in line)
    token = credential['password']
    auth = base64.b64encode(('x-access-token:' + token).encode()).decode()
    env.update(GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='http.https://github.com/.extraheader',
               GIT_CONFIG_VALUE_0='Authorization: Basic ' + auth)
    return env


def verify_online(repo, source):
    # Exact published JSON bytes tie the hosted report to this committed pulse.
    # No deployment-success claim is inferred just from a successful push.
    files = ('scenes.html', 'gpt-methods.html', 'data/gpt-methods-progress.json', 'assets/gpt.js', 'assets/gpt.css')
    commit = git(repo, 'rev-parse', 'HEAD')
    rows = []
    committed = {}
    for name in files:
        expected = subprocess.check_output(['git', '-C', str(repo), 'show', commit + ':docs/' + name], timeout=180)
        committed[name] = expected
        url = 'https://asimfish.github.io/gpt-as-policy-repro/' + name + '?commit=' + commit + '&verify=' + str(time.time_ns())
        request = urllib.request.Request(url, headers={'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(request, timeout=30) as response:
            actual, status = response.read(), response.status
        rows.append(dict(file=name, http_status=status, local_sha256=hashlib.sha256(expected).hexdigest(),
                         online_sha256=hashlib.sha256(actual).hexdigest(), matches=actual == expected))
    assert all(r['matches'] and r['http_status'] == 200 for r in rows), 'Pages has not deployed this pulse yet'
    data = json.loads(committed['data/gpt-methods-progress.json'])
    proof = dict(repository='asimfish/gpt-as-policy-repro', branch='docs/site', commit=commit,
                 url='https://asimfish.github.io/gpt-as-policy-repro/scenes.html', status='published_and_http_verified',
                 verified_utc=datetime.now(timezone.utc).isoformat(), files=rows,
                 gpt_summary=data['summary'], snapshot=data['snapshot'])
    destination = source / 'online_publication.json'
    temp = destination.with_suffix('.tmp')
    temp.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')
    temp.replace(destination)
    evidence = source / 'online_site_verification' / proof['commit'][:12]
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / 'http.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(status=proof['status'], commit=proof['commit'], summary=data['summary'])), flush=True)


def await_online(repo, source, timeout=300, interval=15):
    """Finish delayed Pages verification before a later pulse changes the snapshot."""
    deadline = time.monotonic() + timeout
    attempts = 0
    while True:
        attempts += 1
        try:
            verify_online(repo, source)
            (source / 'online_publication_pending.json').unlink(missing_ok=True)
            return True
        except (AssertionError, OSError):
            pending = dict(status='pushed_pending_online_verification', commit=git(repo, 'rev-parse', 'HEAD'),
                           attempts=attempts, observed_utc=datetime.now(timezone.utc).isoformat())
            path = source / 'online_publication_pending.json'
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps(pending, indent=2)+'\n')
            temp.replace(path)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                print(json.dumps(pending), flush=True)
                return False
            time.sleep(min(interval, remaining))


def publish(repo, source, credentials_repo, proxy):
    check_worktree(repo)
    tools = repo / 'tools'
    old = json.loads((repo / 'docs/data/gpt-methods-progress.json').read_text())
    subprocess.run([sys.executable, str(tools / 'build_gpt_site.py'), '--source', str(source), '--out', str(repo / 'docs')], check=True)
    current = json.loads((repo / 'docs/data/gpt-methods-progress.json').read_text())
    assert {e['id'] for e in old['episodes']} <= {e['id'] for e in current['episodes']}, 'Audit regression; refuse to erase published episodes'
    subprocess.run([sys.executable, str(tools / 'verify_site.py'), str(repo / 'docs')], check=True)
    check_worktree(repo)
    changed = [p for p in git(repo, 'ls-files', '--modified').splitlines() if owned(p)]
    changed += [p for p in git(repo, 'ls-files', '--others', '--exclude-standard').splitlines() if owned(p)]
    if changed:
        git(repo, 'add', '--', *changed)
        assert set(git(repo, 'diff', '--cached', '--name-only').splitlines()) == set(changed), 'Concurrent staging detected; refuse commit'
        git(repo, 'commit', '-m', f'[report/build]: refresh {current["summary"]["complete_method_runs"]} audited method runs')
    env = credential_env(credentials_repo)
    # Also retries an earlier successful commit whose push failed. Normal push only.
    git(repo, '-c', 'http.proxy=' + proxy, 'push', 'origin', 'docs/site', env=env)
    await_online(repo, source)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--credentials-repo', type=Path)
    parser.add_argument('--proxy', default='http://127.0.0.1:7897')
    parser.add_argument('--verify-online-only', action='store_true')
    args = parser.parse_args()
    with open('/tmp/gpt-policy-report-publish.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another publication pulse is active; deferred.', flush=True)
            sys.exit(0)
        if args.verify_online_only:
            verify_online(args.repo.resolve(), args.source.resolve())
        else:
            assert args.credentials_repo is not None
            publish(args.repo.resolve(), args.source.resolve(), args.credentials_repo.resolve(), args.proxy)
