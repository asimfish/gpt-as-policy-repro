"""Export audited original-controller episodes; raw model/server logs stay private."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

from build_site import TASKS

METHODS = {'gpt_only': 'GPT Direct', 'pi05_plus_gpt': 'π0.5 + GPT Hybrid'}
IDENTITY_KEYS = ('panel_id', 'panel_sha256', 'case_id', 'task', 'runtime_task',
                 'variant', 'eval_seed', 'layout_id', 'reset_seed',
                 'simulator_initial_seed', 'policy_rng_seed', 'layout_sha256')
PROOF_KEYS = ('verified', 'complete_episode', 'scope', 'model', 'reasoning_effort',
              'decisions', 'native_actions', 'pi05_inference_calls', 'actions_by_mode',
              'max_absolute_action_error', 'initial_state_hash', 'limitation',
              'model_tool_event_sha256', 'files_sha256')


def read(path, default=None):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    if path.exists() and path.read_text() == encoded:
        return
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(encoded)
    tmp.replace(path)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def robolab_status(source):
    """Export only supplementary readiness; partial actions never join the main score."""
    frozen = read(source/'fixtures/robolab_two_methods_frozen.json')
    if not frozen:
        return None
    tasks = {row['task'] for row in frozen['entries']}
    assert len(frozen['entries']) == 100 and frozen['cases'] == 50
    pairs = {(row['task'], row['seed']) for row in frozen['entries']}
    assert len(tasks) == 10 and len(pairs) == 50
    assert {(row['task'], row['seed'], row['method']) for row in frozen['entries']} == {
        (task, seed, method) for task in tasks for seed in range(5) for method in METHODS}
    active = read(source/'robolab_gpt_active.json', {})
    status = active.get('status', 'not_started')
    assert status in ('not_started', 'starting', 'controller_running',
                      'controller_finished', 'infrastructure_interrupted')
    task, seed = active.get('task'), active.get('seed')
    assert not active or (task in tasks and type(seed) is int and seed in range(5))
    assert not active or active.get('method') in METHODS
    result = dict(planned_pairs=50, planned_method_runs=100,
                  status=status, task=task, seed=seed, method=active.get('method'),
                  started_utc=active.get('started_utc'),
                  results_eligible=False, action_audit_status='pending',
                  direct_implementation_status='implemented_pending_native_validation',
                  cohort='new fixed-seed cohort; historical raw initial states unavailable')
    prefix=read(source/'robolab_gpt_latest_prefix_audit.json')
    result['last_prefix_audit']=None
    if prefix:
        assert prefix['verified'] is True and prefix['complete_episode'] is False
        result['last_prefix_audit']={k:prefix[k] for k in ('method','decisions','native_actions','complete_episode')}
        result['last_prefix_audit']['evidence']='data/robolab-gpt-prefix-audit.json'
    # The workspace is a private input only. No host paths or raw model logs leave it.
    workspace = active.get('local_workspace')
    progress = read(Path(workspace)/'rollout/progress.json', {}) if workspace else {}
    step = progress.get('step_id', 0)
    assert type(step) is int and step >= 0
    result['observed_control_steps'] = step
    return result


def check_episode(run, expected):
    """Fail closed on missing full audit, changed audit inputs, or identity mismatch."""
    result = read(run / 'rollout/result.json', {})
    outcome = read(run / 'sim/evaluation_outcome.json', {})
    proof = read(run / 'complete_action_audit.json', {})
    assert result.get('complete') is True and outcome.get('complete') is True
    assert outcome.get('valid_for_success_rate') is True
    assert result.get('terminated') is True or result.get('truncated') is True
    assert proof.get('verified') is True and proof.get('complete_episode') is True
    assert proof.get('scope') == 'complete_native_episode'
    assert (proof.get('model'), proof.get('reasoning_effort')) == ('gpt-6-astra', 'xhigh')
    for value in (result.get('evaluation_case', {}), outcome.get('evaluation_case', {})):
        assert {k: value.get(k) for k in IDENTITY_KEYS} == expected
    assert type(result.get('success')) is bool
    assert result['success'] == outcome['native_success']
    assert result['step_id'] == outcome['native_control_steps'] == proof['native_actions']
    assert result['decisions'] == proof['decisions']
    assert proof['max_absolute_action_error'] == 0
    if run.name == 'gpt_only':
        assert proof.get('pi05_inference_calls') == 0
    else:
        assert proof['actions_by_mode'] == dict(student=result['student_steps'],
                                                edit=result['edited_steps'], eef=result['recovery_steps'])
        assert sum(proof['actions_by_mode'].values()) == result['step_id']
    if 'terminal' in proof:
        assert proof['terminal'] == {k: result[k] for k in ('success', 'terminated', 'truncated')}
    if 'native_score' in proof:
        assert proof['native_score'] == outcome['native_score']
    # Full action provenance was checked by the complete-episode auditor. Rebind
    # its terminal data and model identity here, without republishing raw inputs.
    for name in ('rollout/result.json', 'sim/evaluation_outcome.json',
                 'rollout/run.json', 'rollout/codex_workspace/worker.json'):
        assert proof['files_sha256'].get(name) == digest(run / name), name
    for name, value in proof['files_sha256'].items():
        assert not Path(name).is_absolute() and '..' not in Path(name).parts
        assert re.fullmatch('[a-f0-9]{64}', value)
    return result, outcome, proof


def failure_class(attempt, failure):
    # Errors are classified locally; arbitrary exception text never enters HTML/JSON.
    text = json.dumps([attempt.get('error', ''), failure], ensure_ascii=False).lower()
    if 'serveroverloaded' in text or 'capacity' in text and 'model' in text:
        return 'model_capacity'
    if any(word in text for word in ('stream disconnected', 'connection reset', 'network', 'websocket')):
        return 'network'
    if 'codex' in text and 'timed out' in text:
        return 'model_response_timeout'
    if attempt.get('status') == 'interrupted':
        return 'supervisor_interrupted'
    return 'infrastructure'


def summarize(cases, episodes):
    lookup = {(e['case_id'], e['method']): e for e in episodes}
    paired = [c['case_id'] for c in cases if all((c['case_id'], m) in lookup for m in METHODS)]
    result = dict(planned_pairs=len(cases), planned_method_runs=len(cases) * len(METHODS),
                  completed_pairs=len(paired), complete_method_runs=len(episodes), methods={})
    for method in METHODS:
        own = [e for e in episodes if e['method'] == method]
        matched = [lookup[c, method] for c in paired]
        def stats(rows):
            n = len(rows)
            wins = sum(e['success'] for e in rows)
            return dict(evaluated=n, successes=wins, failures=n-wins,
                        success_rate=wins/n if n else None,
                        mean_score=sum(e['score'] for e in rows)/n if n else None)
        result['methods'][method] = dict(all_completed=stats(own), paired_completed=stats(matched))
    return result


def first_complete(runs):
    """A preceding unaudited native terminal run must be resolved before selection."""
    first = min(runs, key=lambda r: (r[0]['started_utc'] or '', r[0]['run_id']))
    return first if first[0]['eligible'] else None


def task_summaries(cases, episodes):
    result = []
    for task in TASKS:
        own_cases = [c for c in cases if c['identity']['task'] == task]
        ids = {c['case_id'] for c in own_cases}
        result.append(dict(task=task, task_label=TASKS[task],
                           **summarize(own_cases, [e for e in episodes if e['case_id'] in ids])))
    return result


def media(run, uid, out, old):
    source = run / 'sim/sensors.mp4'
    assert source.is_file() and source.stat().st_size > 1000
    video = 'media/gpt-episodes/' + uid + '.mp4'
    poster = 'media/gpt-episodes/' + uid + '.jpg'
    dest = out / video
    dest.parent.mkdir(parents=True, exist_ok=True)
    source_hash = digest(source)
    previous = old.get(uid, {})
    if not dest.exists() or previous.get('source_video_sha256') != source_hash:
        temp = dest.with_suffix('.tmp.mp4')
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(source), '-an',
                        '-vf', 'scale=1440:-2,fps=15', '-c:v', 'libx264', '-preset', 'fast',
                        '-crf', '26', '-threads', '2', '-movflags', '+faststart', '-y', str(temp)], check=True)
        temp.replace(dest)
        (out / poster).unlink(missing_ok=True)
    if not (out / poster).exists():
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(dest), '-frames:v', '1',
                        '-q:v', '3', '-threads', '1', '-y', str(out / poster)], check=True)
    info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
                                              'format=duration:stream=width,height', '-of', 'json', str(dest)]))
    return dict(video=video, poster=poster, video_sha256=digest(dest), source_video_sha256=source_hash,
                video_bytes=dest.stat().st_size, duration_seconds=float(info['format']['duration']))


def build(source, out):
    for name in ('gpt.css', 'gpt.js'):
        destination = out / 'assets' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(__file__).resolve().parents[1] / 'web/assets' / name, destination)
    fixture_dir = source / 'fixtures/cases'
    fixtures = {}
    for path in sorted(fixture_dir.glob('gpt__*.json')):
        raw = read(path)
        identity = {k: raw['identity'][k] for k in IDENTITY_KEYS}
        cid = identity['case_id']
        assert re.fullmatch('[a-z0-9_]+', cid)
        assert identity == {k: read(fixture_dir / ('mix__' + cid + '.json'))['identity'][k] for k in IDENTITY_KEYS}
        fixtures[cid] = identity
    assert len(fixtures) == 50
    queue = read(source / 'gpt_queue_state.json', {})
    attempts, candidates = [], {}
    for parent in sorted((source / 'gpt_pair_campaign').iterdir()):
        if not parent.is_dir():
            continue
        for method in METHODS:
            run = parent / method
            attempt = read(run / 'attempt.json')
            if not attempt:
                continue
            cid = attempt.get('case', '').removeprefix('gpt__').removeprefix('mix__')
            if cid not in fixtures:
                continue
            assert re.fullmatch('[a-zA-Z0-9_]+', parent.name)
            row = dict(run_id=parent.name, case_id=cid, method=method,
                       started_utc=attempt.get('started_utc'), finished_utc=attempt.get('finished_utc'),
                       supervisor_status=attempt.get('status'), eligible=False, status='interrupted')
            result = read(run / 'rollout/result.json', {})
            outcome = read(run / 'sim/evaluation_outcome.json', {})
            failure = read(run / 'rollout/failure.json', {})
            row['control_steps'] = result.get('step_id', outcome.get('native_control_steps', failure.get('step_id', 0)))
            history = read(run / 'rollout/history.json', []) if 'decisions' not in result else []
            row['decisions'] = result.get('decisions', len(history))
            if history:
                row['control_steps'] = max(row['control_steps'], history[-1]['end_tick'])
            native_complete = result.get('complete') is True and outcome.get('complete') is True
            if native_complete:
                try:
                    values = check_episode(run, fixtures[cid])
                except (AssertionError, KeyError, FileNotFoundError, TypeError, ValueError):
                    row['status'] = 'audit_pending'
                    row['reason_class'] = 'missing_or_inconsistent_complete_audit'
                    candidates.setdefault((cid, method), []).append((row, run, None))
                else:
                    row['status'], row['eligible'] = 'complete', True
                    candidates.setdefault((cid, method), []).append((row, run, values))
            elif not attempt.get('finished_utc') and queue.get('cases', {}).get(cid, {}).get(method, {}).get('status') == 'running':
                row['status'] = 'running'
            else:
                row['reason_class'] = failure_class(attempt, failure)
            attempts.append(row)
    old = {e['id']: e for e in read(out / 'data/gpt-methods-progress.json', {}).get('episodes', [])}
    old_attempts = {a['method'] + '__' + a['run_id']: a for a in
                    read(out / 'data/gpt-methods-progress.json', {}).get('attempts', [])}
    for attempt in attempts:
        if attempt['status'] != 'interrupted' or not attempt['control_steps']:
            continue
        run = source / 'gpt_pair_campaign' / attempt['run_id'] / attempt['method']
        proofs = [read(path) for path in run.glob('*audit.json')]
        proofs = [p for p in proofs if p.get('verified') is True and p.get('complete_episode') is False
                  and (p.get('model'), p.get('reasoning_effort')) == ('gpt-6-astra', 'xhigh')
                  and p.get('native_actions', 0) <= attempt['control_steps']]
        if not proofs:
            continue
        proof = max(proofs, key=lambda p: p['native_actions'])
        uid = attempt['method'] + '__' + attempt['run_id']
        attempt['audit'] = 'data/gpt-attempts/' + uid + '-audit.json'
        attempt['audited_control_steps'] = proof['native_actions']
        attempt['audited_decisions'] = proof['decisions']
        write(out / attempt['audit'], {k: proof[k] for k in PROOF_KEYS if k in proof})
        if (run / 'sim/sensors.mp4').is_file():
            attempt.update(media(run, 'attempt__' + uid, out,
                                 {'attempt__' + uid: old_attempts.get(uid, {})}))
    episodes = []
    for (cid, method), runs in sorted(candidates.items()):
        # Keep the first eligible attempt, including native failures. Never select
        # a later success over an earlier valid failure.
        selected = first_complete(runs)
        if selected is None:
            continue
        row, run, (result, outcome, proof) = selected
        uid = method + '__' + cid
        episode = dict(id=uid, case_id=cid, method=method, method_label=METHODS[method],
                       identity=fixtures[cid], task_label=TASKS[fixtures[cid]['task']],
                       run_id=row['run_id'], started_utc=row['started_utc'], finished_utc=row['finished_utc'],
                       supervisor_status=row['supervisor_status'], complete=True, eligible=True,
                       success=result['success'], score=outcome['native_score'], control_steps=result['step_id'],
                       decisions=result['decisions'], terminated=result['terminated'], truncated=result['truncated'],
                       native_horizon=outcome['native_step_limit'], model=proof['model'],
                       reasoning_effort=proof['reasoning_effort'], initial_robot_state_sha256=proof['initial_state_hash'],
                       scene_layout_record_sha256=digest(run / 'sim/scene_layout.json'),
                       actions_by_mode=proof.get('actions_by_mode'), audit='data/gpt-episodes/' + uid + '-audit.json',
                       evidence='data/gpt-episodes/' + uid + '.json')
        public_proof = {k: proof[k] for k in PROOF_KEYS if k in proof}
        public_proof.update(terminal={k: result[k] for k in ('success', 'terminated', 'truncated')},
                            native_score=outcome['native_score'],
                            terminal_source='SHA256-bound native result and outcome',
                            result_identity=fixtures[cid])
        write(out / episode['audit'], public_proof)
        episode['audit_sha256'] = digest(out / episode['audit'])
        episode.update(media(run, uid, out, old))
        write(out / episode['evidence'], episode)
        episodes.append(episode)
    lookup = {(e['case_id'], e['method']): e for e in episodes}
    cases = []
    for cid, identity in fixtures.items():
        case = dict(case_id=cid, identity=identity, task_label=TASKS[identity['task']], methods={})
        for method in METHODS:
            relevant = [a for a in attempts if (a['case_id'], a['method']) == (cid, method)]
            episode = lookup.get((cid, method))
            status = 'complete' if episode else ('running' if queue.get('cases', {}).get(cid, {}).get(method, {}).get('status') == 'running'
                     else 'audit_pending' if any(a['status'] == 'audit_pending' for a in relevant)
                     else 'interrupted' if relevant else 'pending')
            case['methods'][method] = dict(status=status, attempts=len(relevant),
                                          episode_id=episode['id'] if episode else None)
        case['paired_complete'] = all((cid, m) in lookup for m in METHODS)
        case['robot_joint_states_equal'] = (lookup[cid, 'gpt_only']['initial_robot_state_sha256'] ==
                                            lookup[cid, 'pi05_plus_gpt']['initial_robot_state_sha256']) if case['paired_complete'] else None
        case['scene_layout_records_equal'] = (lookup[cid, 'gpt_only']['scene_layout_record_sha256'] ==
                                             lookup[cid, 'pi05_plus_gpt']['scene_layout_record_sha256']) if case['paired_complete'] else None
        if case['paired_complete']:
            assert case['scene_layout_records_equal'], 'Completed pair has different recorded scene layouts'
        cases.append(case)
    interrupted = [a for a in attempts if a['status'] == 'interrupted']
    data = dict(schema='gpt_policy_progress.v2', snapshot=datetime.now(timezone.utc).isoformat(),
                summary=summarize(cases, episodes), task_summary=task_summaries(cases, episodes),
                cases=cases, episodes=episodes, attempts=attempts,
                interruptions=dict(count=len(interrupted), by_reason=dict(Counter(a['reason_class'] for a in interrupted))),
                protocol=dict(model='gpt-6-astra', reasoning_effort='xhigh', controller='original_persistent_codex',
                              selection='first audited native complete attempt per frozen case and method',
                              denominator='complete native successes and failures only; no partial/capacity/infrastructure attempts',
                              comparability='Matched layouts and seeds, not a historical-model-identical replication.',
                              limitation='Recorded joint actions audited; IK and full simulator state not independently recomputed.'))
    supplementary = robolab_status(source)
    if supplementary:
        data['supplementary'] = dict(robolab=supplementary)
        prefix=read(source/'robolab_gpt_latest_prefix_audit.json')
        if prefix:
            assert prefix['complete_episode'] is False and prefix['verified'] is True
            public_prefix={k:prefix[k] for k in PROOF_KEYS if k in prefix}
            public_prefix.update(method=prefix['method'],terminal=prefix['terminal'])
            write(out/'data/robolab-gpt-prefix-audit.json',public_prefix)
    # An unchanged poll must not create a new publication merely for a timestamp.
    previous = read(out / 'data/gpt-methods-progress.json', {})
    compare = lambda d: {k: v for k, v in d.items() if k != 'snapshot'}
    if compare(previous) == compare(data):
        data['snapshot'] = previous['snapshot']
    write(out / 'data/gpt-methods-progress.json', data)
    write(out / 'data/gpt-media-manifest.json', [{k: e[k] for k in
          ('id', 'run_id', 'video', 'video_bytes', 'duration_seconds', 'video_sha256', 'source_video_sha256')} for e in episodes])
    from render_gpt_progress import render
    render(out)
    print(json.dumps(data['summary'], ensure_ascii=False), flush=True)
    return data


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    build(args.source.resolve(), args.out.resolve())
