"""Compare the sealed independent cohort to immutable public author snapshots."""
import argparse
from collections import Counter
import hashlib
import html
import json
import math
from pathlib import Path
import re
import statistics

METHODS={'gpt_only':'GPT Direct','pi05_plus_gpt':'π0.5 + GPT Hybrid'}
ORIGINAL={'gpt':'gpt_only','mix':'pi05_plus_gpt'}
SEEDS=('eval_seed','layout_id','reset_seed','simulator_initial_seed','policy_rng_seed')
TOKEN_KEYS=('totalTokens','inputTokens','cachedInputTokens','cacheWriteInputTokens','outputTokens','reasoningOutputTokens')
RECORDED_FIELDS=('states','eef_positions','eef_quaternions_wxyz')
CONFIG_MATCHES=('layout_matches','resolved_configuration_matches','native_horizon_matches',
    'control_dt_matches','decision_cap_matches','context_version_matches','teacher_prompt_hash_matches','student_identity_matches')


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
    native=[r['native_complete'] for r in rows if 'native_complete' in r]
    assert all(type(v) is bool for v in native)
    return dict(episodes=len(rows),successes=sum(r['success'] for r in rows),
        native_completion_samples=len(native),native_complete=sum(native) if native else None,
        adjudicated_failures=sum(not v for v in native) if len(native)==len(rows) else None,
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
            original_native_complete=a.get('native_complete'),reproduction_native_complete=b.get('native_complete'),
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
                native_complete=True,
                steps=e['control_steps'],chunks=len(executed),decision_events=e['decisions'],corrected_steps=corrected,
                tokens=tokens,evidence=e['evidence'],max_decisions=integer(run_config['max_decisions']))
            if cohort=='robodojo':row['seeds']={k:e['identity'][k] for k in SEEDS}
            records.append(row)
    assert len(records)==200
    return records,inputs,extra_inputs

def recovered_summary(rows):
    assert len(rows)==98 and len(indexed(rows))==98
    for r in rows:
        actual={k:all(r['original_recorded_fields'][k][field]==r['reproduction_recorded_fields'][k][field]
                 for field in ('shape','dtype','sha256')) for k in RECORDED_FIELDS}
        assert actual==r['recorded_field_matches']
        assert all(type(r[k]) is bool for k in CONFIG_MATCHES)
        assert r['teacher_prompt_hash_matches']==(r['original_teacher_prompt_sha256']==r['reproduction_teacher_prompt_sha256'])
    return dict(common_method_runs=len(rows),common_case_pairs=len({r['case_id'] for r in rows}),
        recorded_field_matches={k:sum(r['recorded_field_matches'][k] for r in rows) for k in RECORDED_FIELDS},
        **{k:sum(r[k] for r in rows) for k in CONFIG_MATCHES},
        all_recorded_robot_fields_match=sum(all(r['recorded_field_matches'].values()) for r in rows))

def inspection_summary(rows):
    assert len(rows)==len(indexed(rows))==98
    for r in rows:
        assert all(type(r['max_absolute_difference'][k]) in (float,int) and math.isfinite(r['max_absolute_difference'][k]) and r['max_absolute_difference'][k]>=0 for k in RECORDED_FIELDS)
        assert type(r['prompt_equal_after_replacing_working_directory_line']) is bool
        assert type(r['archived_prompt_matches_prearchive_run_hash']) is bool
    return dict(episodes=len(rows),max_absolute_difference={k:max(r['max_absolute_difference'][k] for r in rows) for k in RECORDED_FIELDS},
        prompt_equal_after_replacing_working_directory_line=sum(r['prompt_equal_after_replacing_working_directory_line'] for r in rows),
        archived_prompt_matches_prearchive_run_hash=sum(r['archived_prompt_matches_prearchive_run_hash'] for r in rows))

def load_recovery(source,original,current,gate_sha):
    q=source/'publication_checks/historical_protocol_20261008'
    if not (q/'recovered_comparison.json').exists():return None
    proof_data=(q/'original_record_recount.json').read_bytes();proof=json.loads(proof_data)
    recovered=read(q/'recovered_comparison.json')
    assert proof['verified'] is True and proof['core_archives_verified']==100
    assert proof['original_control_steps_verified']==80971
    assert recovered['verified'] is True and recovered['original_record_recount_sha256']==sha(proof_data)
    assert recovered['native_certificate_sha256']==gate_sha
    assert recovered['original_gallery_sha256']==sha((q/'original_robolab_gallery.json').read_bytes())
    for name,digest in recovered['files_sha256'].items():
        path=Path(name);assert not path.is_absolute() and '..' not in path.parts
        assert sha((source/path).read_bytes())==digest,name
    old=indexed(original);new=indexed([r for r in current if r['cohort']=='robodojo'])
    original_archives=[]
    for r in proof['records']:
        method={'direct':'gpt_only','hybrid':'pi05_plus_gpt'}[r['method']];row=old[r['case_id'],method]
        assert r['evaluation_success']==row['success'] and r['native_score']==row['score']
        assert r['native_complete']==row['native_complete'] and r['control_steps']==row['steps']
        assert r['decision_count']==row['chunks'] and r['tokens']==row['tokens']
        expected=r['source_steps'].get('edit',0)+r['source_steps'].get('eef',0) if method=='pi05_plus_gpt' else 0
        assert expected==row['corrected_steps']
        original_archives.append(dict(case_id=r['case_id'],method=method,core_sha256=r['core_sha256']))
    assert len(original_archives)==100 and len(indexed(original_archives))==100
    for r in recovered['robodojo']['cases']:assert r['run_id']==new[r['case_id'],r['method']]['run_id']
    assert recovered['robodojo']['summary']==recovered_summary(recovered['robodojo']['cases'])
    inspection=read(q/'initial_difference_inspection.json')
    assert inspection['verified'] is True and inspection['original_record_recount_sha256']==sha(proof_data)
    assert inspection['recovered_comparison_sha256']==sha((q/'recovered_comparison.json').read_bytes())
    assert inspection['summary']==inspection_summary(inspection['cases'])
    assert set(indexed(inspection['cases']))==set(indexed(recovered['robodojo']['cases']))
    for name,digest in inspection['files_sha256'].items():
        path=Path(name);assert not path.is_absolute() and '..' not in path.parts
        assert sha((source/path).read_bytes())==digest,name
    return dict(dataset=proof['dataset'],revision=proof['revision'],
        source_url='https://huggingface.co/datasets/'+proof['dataset']+'/tree/'+proof['revision'],
        attribution='Original GPT-as-Policy authors; YuMoool public archival dataset, CC BY 4.0.',
        core_archives_verified=100,original_control_steps_verified=80971,
        original_record_recount_sha256=sha(proof_data),original_archives=original_archives,
        recorded_joint_action_state_joins_verified=True,full_observation_archives_verified=False,
        historical_full_physics_state_verified=False,configuration_comparison=recovered,
        recorded_initial_difference_inspection=inspection)

def worker_fidelity_summary(rows):
    assert len(rows)==len(indexed(rows))==98
    for r in rows:
        assert r['original_cli']=='codex-cli 0.153.4'
        assert r['original_rejection_stop'] in (None,5)
        count=integer(r['reproduction_recorded_rejections'])
        assert r['crosses_original_five_rejection_stop']==(r['original_rejection_stop']==5 and count>=5)
        assert all(type(r['images'][name]['pixel_equal']) is bool for name in ('cam_high','cam_left_wrist','cam_right_wrist'))
    return dict(common_method_runs=98,crosses_original_five_rejection_stop=sum(r['crosses_original_five_rejection_stop'] for r in rows),
        original_cli_counts=dict(Counter(r['original_cli'] for r in rows)),
        reproduction_cli_counts=dict(Counter(r['reproduction_cli'] for r in rows)),
        initial_model_preview_pixel_matches={name:sum(r['images'][name]['pixel_equal'] for r in rows) for name in ('cam_high','cam_left_wrist','cam_right_wrist')})

def validate_historical_execution(value):
    assert value['verified'] is True
    assert value['historical_protocol_equivalence'] is False and value['full_blog_reproduction_complete'] is False
    assert value['pilot_included_in_benchmark'] is False and value['automatic_physical_retries']==0
    rows=value['canary_results'];assert len(rows)==2 and {r['method'] for r in rows}==set(METHODS)
    for r in rows:
        assert r['status']=='native_complete_audited' and r['benchmark_eligible'] is False
        assert type(r['native_success']) is bool and type(r['native_score']) in (int,float) and 0<=r['native_score']<=1
        assert integer(r['native_actions'])==1050 and integer(r['decisions'])>0
        assert r['source_video']['frames']==r['native_actions']+1 and r['source_video']['complete_decode_passed'] is True
        assert r['historical_protocol_equivalence'] is False and r['full_blog_reproduction_complete'] is False
    queue=value['remaining_cohort']
    assert queue['pairs_planned']==49 and queue['episodes_planned']==98 and queue['pilot_reused_for_grading'] is False
    assert 0<=integer(queue['native_complete_audited'])<=integer(queue['first_attempts_audited'])<=98
    assert queue['automatic_physical_retries']==0
    assert queue['historical_protocol_equivalence'] is False and queue['full_blog_reproduction_complete'] is False

def load_historical_execution(source):
    q=source/'publication_checks/worker_fidelity_20261008';out=source/'publication_checks/historical_cohort_20261010'
    if not (q/'historical_canary_evidence_gate.json').exists() or not (out/'runtime_snapshot.json').exists():return None
    gate=read(q/'historical_canary_evidence_gate.json');admission=read(q/'historical_canary_admission.json')
    assert gate['verified'] is True and gate['complete_native_audited']==2
    assert gate['admission_sha256']==sha((q/'historical_canary_admission.json').read_bytes())
    root=source/gate['cohort'];assert gate['plan_sha256']==admission['plan_sha256']==sha((root/'pair_plan.json').read_bytes())
    assert (root/'pair_plan.json').read_bytes()==(q/'historical_pair_preflight.json').read_bytes()
    for row in gate['results']:
        run=root/row['method'];proof=read(run/'complete_action_audit.json')
        assert sha((run/'complete_action_audit.json').read_bytes())==row['complete_action_audit_sha256']
        assert proof['verified'] is True and proof['complete_episode'] is True
        assert proof['native_actions']==row['native_actions'] and proof['decisions']==row['decisions']
        for name,digest in proof['files_sha256'].items():
            path=Path(name);assert not path.is_absolute() and '..' not in path.parts
            assert sha((run/path).read_bytes())==digest
        assert sha((run/'sim/sensors.mp4').read_bytes())==row['source_video']['sha256']
        outcome=read(run/'sim/evaluation_outcome.json')
        assert outcome['native_success']==row['native_success'] and outcome['native_score']==row['native_score']
    snapshot=read(out/'runtime_snapshot.json');plan=read(out/'cohort_plan.json');activation=read(out/'activation.json')
    digest=sha((out/'cohort_plan.json').read_bytes())
    assert digest==snapshot['plan_sha256']==activation['plan_sha256']
    assert plan['episodes_planned']==98 and len(plan['pairs'])==49 and plan['physical_retry_limit']==0
    assert plan['pilot']['reused_for_grading'] is False and snapshot['progress']['episodes_planned']==98
    original=read(source/'publication_checks/historical_protocol_20261008/original_record_recount.json')
    original_rows={r['episode_id']:r for r in original['records']}
    results=[]
    for row in gate['results']:
        previous=original_rows[row['episode_id']]
        results.append(dict(row,original_native_score=previous['native_score'],
                            original_success=previous['evaluation_success'],original_decisions=previous['decision_count']))
    progress=snapshot['progress']
    assert progress['first_attempts_audited']==len(progress['results'])
    assert progress['native_complete_audited']==sum(r['status']=='native_complete_audited' for r in progress['results'])
    for name,digest in plan['source_sha256'].items():assert sha((source/name).read_bytes())==digest
    assert plan['receipt_sha256']['historical_worker_manifest.json']==sha((q/'historical_worker_manifest.json').read_bytes())
    # Running observations remain separate from audited scores. A capture is a
    # dated snapshot and cannot assert that a background process is still alive.
    remaining=dict(pairs_planned=49,episodes_planned=98,pilot_reused_for_grading=False,
        first_attempts_audited=progress['first_attempts_audited'],native_complete_audited=progress['native_complete_audited'],
        phase_at_snapshot=progress['phase'],current_episode_at_snapshot=progress['current_episode'],
        captured_utc=snapshot['captured_utc'],observed_native_steps=snapshot['observed_native_steps'],
        current_run_complete_audit=False,automatic_physical_retries=0,
        historical_protocol_equivalence=False,full_blog_reproduction_complete=False)
    value=dict(verified=True,canary_results=results,remaining_cohort=remaining,
        pilot_included_in_benchmark=False,automatic_physical_retries=0,
        evidence_sha256={'worker_fidelity_20261008/'+name:sha((q/name).read_bytes()) for name in
                        ('historical_canary_evidence_gate.json','historical_canary_admission.json','historical_pair_preflight.json')},
        historical_protocol_equivalence=False,full_blog_reproduction_complete=False)
    value['evidence_sha256'].update({'historical_cohort_20261010/'+name:sha((out/name).read_bytes()) for name in
                                   ('cohort_plan.json','runtime_snapshot.json','activation.json','implementation_checks.json')})
    validate_historical_execution(value);return value

def load_worker_fidelity(source,gate_sha,recovery,current):
    q=source/'publication_checks/worker_fidelity_20261008'
    if not (q/'historical_worker_offline_gate.json').exists():return None
    documents={name:read(q/name) for name in ('worker_protocol_inspection.json','historical_worker_manifest.json',
        'historical_worker_offline_gate.json','original_cli_toolchain.json','original_cli_zero_turn_probe.json','initial_model_rgb_differences.json')}
    hashes={name:sha((q/name).read_bytes()) for name in documents}
    inspection=documents['worker_protocol_inspection.json'];manifest=documents['historical_worker_manifest.json']
    offline=documents['historical_worker_offline_gate.json'];cli=documents['original_cli_zero_turn_probe.json']
    assert inspection['verified'] is True and inspection['native_certificate_sha256']==gate_sha
    assert inspection['original_record_recount_sha256']==recovery['original_record_recount_sha256']
    assert len(inspection['original'])==len(inspection['reproduction'])==100
    assert set(indexed(inspection['reproduction']))==set(indexed([r for r in current if r['cohort']=='robodojo']))
    assert all(r['worker']['codex_version']=='codex-cli 0.153.4' for r in inspection['original'])
    # Capture-time readings are bound to the original audits or separately SHA
    # recorded. Recheck audit proofs, worker identity and additional inputs;
    # this is not a new scan of all sealed native action evidence.
    for r in inspection['reproduction']:
        required=set(r['separately_captured_inputs'])|{name for name in r['inputs_sha256'] if name.endswith(('complete_action_audit.json','worker.json'))}
        for name in required:
            path=Path(name);assert not path.is_absolute() and '..' not in path.parts
            assert sha((source/path).read_bytes())==r['inputs_sha256'][name]
    assert manifest['verified'] is True and len(manifest['cases'])==100 and len(manifest['source_profiles'])==5
    assert manifest['cli']['toolchain_receipt_sha256']==hashes['original_cli_toolchain.json']
    for gate in (offline,cli):
        assert gate['verified'] is True and gate['manifest_sha256']==hashes['historical_worker_manifest.json']
        assert len(gate['profiles'])==5 and gate['model_calls']==gate['simulator_steps']==0
    rgb=documents['initial_model_rgb_differences.json']
    assert rgb['verified'] is True and rgb['worker_protocol_inspection_sha256']==hashes['worker_protocol_inspection.json']
    assert set(indexed(rgb['cases']))==set(indexed(inspection['common_cases']))
    value=dict(evidence_sha256=hashes,common_cases=inspection['common_cases'],
        common_summary=worker_fidelity_summary(inspection['common_cases']),
        original_cli_counts=inspection['summary']['original_cli_counts'],reproduction_cli_counts=inspection['summary']['reproduction_cli_counts'],
        original_five_rejection_stop_episodes=inspection['summary']['original_five_rejection_stop_episodes'],
        initial_model_rgb_difference_summary=rgb['summary'],
        reconstructed_source_profiles=5,reconstructed_worker_versions=4,historical_case_assignments=100,
        isolated_cli_version='codex-cli 0.153.4',offline_source_profiles_verified=5,offline_protocol_scenarios_verified=30,
        real_cli_initialization_profiles_verified=5,compatibility_probe_model_calls=0,compatibility_probe_ephemeral_override=True,
        original_gateway_source_recovered=False,original_model_service_snapshot_recovered=False,
        historical_protocol_equivalence=False,full_blog_reproduction_complete=False,
        original_version_execution=load_historical_execution(source),
        scope='Recorded rejection branches and initial model-preview bytes; exact historical source staging plus offline execution and zero-turn CLI initialization. '
            'Fresh physical execution has separate evidence and never changes the sealed 200-run cohort. Fifth-stop crossings are not counterfactual success estimates.')
    validate_worker_fidelity(value)
    return value

def validate_worker_fidelity(value):
    assert value['common_summary']==worker_fidelity_summary(value['common_cases'])
    assert value['original_cli_counts']=={'codex-cli 0.153.4':100}
    assert value['reproduction_cli_counts']=={'codex-cli 0.159.2':96,'codex-cli 0.153.4':4}
    assert value['original_five_rejection_stop_episodes']==78
    for name in ('reconstructed_source_profiles','offline_source_profiles_verified','real_cli_initialization_profiles_verified'):assert value[name]==5
    assert value['reconstructed_worker_versions']==4 and value['historical_case_assignments']==100
    assert value['offline_protocol_scenarios_verified']==30 and value['compatibility_probe_model_calls']==0
    assert value['original_gateway_source_recovered'] is False and value['original_model_service_snapshot_recovered'] is False
    assert value['historical_protocol_equivalence'] is False and value['full_blog_reproduction_complete'] is False
    if value.get('original_version_execution') is not None:validate_historical_execution(value['original_version_execution'])
    for r in value['initial_model_rgb_difference_summary'].values():
        assert r['episodes']==98 and r['pixel_identical_episodes']==0
        assert 0<=r['mean_absolute_channel_difference_mean']<=r['mean_absolute_channel_difference_max']<=255
        assert 0<=r['changed_pixel_fraction_mean']<=1

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
        native_complete=r['native_complete'],status=r['status'],
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
        original_record_recovery=load_recovery(source,original,current,sha(gate_data)),
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
            '原RoboDojo Direct为48条原生完整轨迹加2条RPC超时前缀裁定失败；本次50条均原生完整，基础设施中断另行保留并有界重试。两个口径分列，不能据成功总数相同认定协议一致。',
            '匹配案例ID与种子不能证明历史完整物理初态相同；RoboLab仅按任务汇总比较。',
            'RoboLab Direct 使用自有 EEF 适配器，历史完整源码与prompt未恢复。',
            '原 RoboLab 含历史结果及授权重试，两个 BlocksInBin Direct 重试使用500而非180决策；本次不采用该混合预算协议。',
            '本次RoboLab日志的决策上限为100000，主要受原生控制时域约束；180/500决策表仅截看已有轨迹，不是新预算评测或因果解释。',
            'Token 为控制器最后记录的累计计数，包含缓存输入；RoboLab缺少独立用量汇总，保持未知，不能作为零消耗或账单金额。',
            'π0.5、Cosmos和DreamZero全量基线尚未纳入此前两方法范围。'])
    comparison['historical_worker_fidelity']=load_worker_fidelity(source,sha(gate_data),comparison['original_record_recovery'],current)
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
            assert row['native_complete'] is True
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
    assert sum(r['native_complete'] for r in old if r['method']=='gpt_only')==48
    assert sum(r['native_complete'] for r in old if r['method']=='pi05_plus_gpt')==50
    adjudicated=[r for r in old if not r['native_complete']]
    assert {r['case_id'] for r in adjudicated}=={'classify_objects_by_language__standard__g0__l1','pack_objects_into_box__random__g0__l2'}
    assert all(r['method']=='gpt_only' and r['success'] is False and r['score'] is None for r in adjudicated)
    recovery=value.get('original_record_recovery')
    if recovery is not None:
        assert recovery['core_archives_verified']==100 and recovery['original_control_steps_verified']==sum(r['steps'] for r in old)==80971
        assert recovery['full_observation_archives_verified'] is False and recovery['historical_full_physics_state_verified'] is False
        assert set(indexed(recovery['original_archives']))==set(indexed(old))
        config=recovery['configuration_comparison'];assert config['verified'] is True
        assert config['native_certificate_sha256']==value['native_completion_sha256']
        assert config['original_record_recount_sha256']==recovery['original_record_recount_sha256']
        assert config['robodojo']['summary']==recovered_summary(config['robodojo']['cases'])
        aligned=indexed(config['robodojo']['cases']);own_lookup=indexed(own)
        assert set(aligned)==set(indexed(old))&set(own_lookup)
        for key,r in aligned.items():assert r['run_id']==own_lookup[key]['run_id']
        inspection=recovery['recorded_initial_difference_inspection']
        assert inspection['verified'] is True and inspection['historical_full_physics_state_verified'] is False
        assert inspection['original_record_recount_sha256']==recovery['original_record_recount_sha256']
        assert inspection['summary']==inspection_summary(inspection['cases'])
        assert set(indexed(inspection['cases']))==set(aligned)
        for r in inspection['cases']:assert r['run_id']==own_lookup[r['case_id'],r['method']]['run_id']
        lab=config['robolab']['task_method_control_horizons'];assert len(lab)==20
        assert {(r['task'],r['method']) for r in lab}=={(r['task'],r['method']) for r in current if r['cohort']=='robolab'}
        for r in lab:
            assert r['control_horizon_matches']==(r['original_control_horizon']==r['reproduction_control_horizon'])
            assert r['original_slots_are_seed_identities'] is False and r['historical_per_slot_decision_caps_verified'] is False
            task=next(t for t in value['robolab']['tasks'] if t['task']==r['task'] and t['method']==r['method'])
            assert task['original_successes']==r['original_successes']
    worker=value.get('historical_worker_fidelity')
    if worker is not None:
        validate_worker_fidelity(worker)
        assert set(indexed(worker['common_cases']))==set(indexed(old))&set(indexed(own))
        for r in worker['common_cases']:assert r['run_id']==indexed(own)[r['case_id'],r['method']]['run_id']
    assert (docs/'blog-comparison.html').read_text()==render(value)
    assert 'blog-comparison.html' in (docs/'scenes.html').read_text()

def worker_fidelity_panel(value):
    worker=value.get('historical_worker_fidelity')
    if worker is None:return ''
    s=worker['common_summary'];rgb=worker['initial_model_rgb_difference_summary']
    differences=[r['mean_absolute_channel_difference_mean'] for r in rgb.values()]
    execution=worker.get('original_version_execution');physical=''
    if execution:
        rows={r['method']:r for r in execution['canary_results']};queue=execution['remaining_cohort']
        physical=('<p id="historical-native-execution">原版本配对试跑已完成：Direct '+str(rows['gpt_only']['native_actions'])
            +'步 / '+str(rows['gpt_only']['decisions'])+'次决策；Hybrid '+str(rows['pi05_plus_gpt']['native_actions'])
            +'步 / '+str(rows['pi05_plus_gpt']['decisions'])+'次决策。Direct '+('成功' if rows['gpt_only']['native_success'] else '失败')
            +'，分数'+str(rows['gpt_only']['native_score'])+'；Hybrid '+('成功' if rows['pi05_plus_gpt']['native_success'] else '失败')
            +'，分数'+str(rows['pi05_plus_gpt']['native_score'])+'。完整动作和原视频审计通过。'
            '同案例原Hybrid分数为'+str(rows['pi05_plus_gpt']['original_native_score'])
            +'，不能据链路审计通过声称结果一致。试跑单独保留，不计入基准面板。</p>'
            '<p>其余49对 / 98次首次尝试已独立冻结并启动。快照UTC '+html.escape(queue['captured_utc'])
            +'：已审计首次尝试 '+str(queue['first_attempts_audited'])+'/98，原生完整 '+str(queue['native_complete_audited'])
            +'；当时案例 <span style="overflow-wrap:anywhere">'+html.escape(queue['current_episode_at_snapshot'] or '无')+'</span>，观察到 '
            +str(queue['observed_native_steps'])+'个控制步。运行观察不是完整成绩；后台状态可能已推进。'
            '自动物理重试0，未完成前缀和无效布局不计成绩。</p>')
    return ('<section class="panel" id="historical-worker-fidelity"><h2>历史控制器与CLI恢复</h2>'
        '<p>原100条全部使用Codex CLI 0.153.4；本次封存结果中96条使用0.159.2，4条使用0.153.4。'
        '原源码包含5套文件组合、4个控制器版本；其中78条对应累计5次输入拒绝后终止的版本。'
        '共同98条中，有'+str(s['crosses_original_five_rejection_stop'])+'条本次轨迹超过对应原版的5次终止阈值。'
        '这是实际记录与停止规则的差异，不是按原版重跑成绩，也不能推断成功率会如何变化。</p>'
        '<p>已独立安装0.153.4并逐字节恢复5套历史源码，100个原案例均绑定对应版本。'
        '5套源码通过30项离线事件循环场景及5次真实CLI初始化，兼容性检查未启动模型推理。'
        '初始化检查使用临时线程，尚未验证原持久历史行为；缺失的历史网关模块由明确标注的当前授权运行环境桥接。</p>'
        +physical+'<p>独立历史版本执行使用原布局、种子、时域和预算，保留首次尝试。'
        '封存200回合及其证明保持原样。RoboLab历史Direct源码、逐槽180/500预算与重试选择协议仍未恢复。</p>'
        '<p>三个相机初始模型图像均0/98逐像素相同；0–255通道范围内的跨案例平均绝对差为'
        +format(min(differences),'.3f')+'–'+format(max(differences),'.3f')+'。这些RGB测量不证明隐藏物理状态相同，也不解释结果差异。'
        '版本对应、图像测量和独立检查SHA见<a href="data/blog-comparison.json">完整JSON</a>。</p></section>')

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
        rows.append([METHODS[method],f'{a["successes"]}/{a["episodes"]}',f'{b["successes"]}/{b["episodes"]}',f'{a["native_complete"]} / {b["native_complete"]}',score(a),score(b),f'{a["control_steps"]:,} / {b["control_steps"]:,}',f'{a["executed_chunks"]:,} / {b["executed_chunks"]:,}',usage(a)+' / '+usage(b)])
    main=table(['方法','原成功数','本次成功数','原生完整 原/本次','原Score×100','本次Score×100','控制步 原/本次','执行段 原/本次','累计Token 原/本次'],rows)
    a=value['robodojo']['methods']['pi05_plus_gpt']['original'];b=value['robodojo']['methods']['pi05_plus_gpt']['reproduction']
    correction=f'Hybrid 原纠错 {a["corrected_steps"]:,}/{a["control_steps"]:,} 步（{a["correction_fraction"]:.2%}）；本次 {b["corrected_steps"]:,}/{b["control_steps"]:,} 步（{b["correction_fraction"]:.2%}）。纠错按实际执行的 edit/EEF 控制步计数。累计Token包含缓存输入，不能直接换算费用；执行段只计 executed_steps&gt;0，与作者提取口径一致。'
    tasks=table(['RoboDojo任务','方法','原成功数/5','本次成功数/5'],[[t['task'],METHODS[t['method']],t['original']['successes'],t['reproduction']['successes']] for t in value['robodojo']['tasks']])
    lab=table(['RoboLab任务','方法','原成功数/5','本次成功数/5'],[[t['task'],METHODS[t['method']],t['original_successes'],t['reproduction_successes']] for t in value['robolab']['tasks']])
    budgets=table(['方法','观察到的决策数','已成功终止','已原生失败','在已录轨迹中尚未终止'],[[METHODS[m],r['budget'],r['success_already_observed'],r['native_failure_already_observed'],r['still_unfinished_in_recorded_prefix']] for m,rows in value['robolab']['recorded_budget_observations'].items() for r in rows])
    alignment=value['robodojo']['case_alignment'];paired=table(['共同案例','方法','原成功','本次成功','原Score','本次Score','本次证据'],[[r['case_id'],METHODS[r['method']],'是' if r['original_success'] else '否','是' if r['reproduction_success'] else '否',r['original_score'] if r['original_score'] is not None else '缺失',r['reproduction_score'],dict(href=r['evidence'],text='案例JSON')] for r in alignment['cases']])
    changed='；'.join(METHODS[m]+f'：{r["changed_success_outcomes"]}/{r["episodes"]}条成功判定不同' for m,r in alignment['methods'].items())
    document='<h2>RoboLab决策预算观察</h2><p>本次决策上限100000，主要受原生控制时域约束。原报告部分Direct回合采用180/500决策。下表只观察已有轨迹在相应决策数内是否已终止，不能当作新预算的实际成功率；尚未终止不计为失败。</p>'+budgets
    recovery=value.get('original_record_recovery');recovery_panel=worker_fidelity_panel(value)
    if recovery:
        s=recovery['configuration_comparison']['robodojo']['summary']
        n=recovery['recorded_initial_difference_inspection']['summary']
        delta=n['max_absolute_difference']
        recovery_panel+='<section class="panel" id="original-record-recovery"><h2>原始公开档案独立重算</h2><p>100个核心档案已逐包校验SHA，80,971步控制的动作及执行后关节状态已与轨迹逐步核对；原Direct13/50与Hybrid24/50及其Score、纠错和累计Token均重算一致。这是原记录的核验；本次独立运行结果仍保持下表中的13/50与21/50。</p><p>原Direct仅48条原生完整，另2条RPC超时前缀按作者协议裁定失败。本次Direct50条均原生完整；已保留的中断不补入原生失败。</p><p>共同98条回合：布局、解析配置、原生时域、控制步长均'+str(s['layout_matches'])+'/98一致；初始关节状态哈希'+str(s['recorded_field_matches']['states'])+'/98、末端位置'+str(s['recorded_field_matches']['eef_positions'])+'/98、姿态四元数哈希'+str(s['recorded_field_matches']['eef_quaternions_wxyz'])+'/98、prompt哈希'+str(s['teacher_prompt_hash_matches'])+'/98一致。</p><p>这些字节差异很小：初始关节最大绝对数值差'+format(delta['states'],'.3e')+'，四元数'+format(delta['eef_quaternions_wxyz'],'.3e')+'，末端位置为零。'+str(n['prompt_equal_after_replacing_working_directory_line'])+'/98条归档prompt只替换工作目录行后，其余字节完全一致；数据导出曾规范化私有路径，归档prompt不保留运行时原哈希。不能把哈希不同直接解释为控制指令或物理环境发生实质变化，也未证明原始模型输入、隐藏物理状态和服务状态完全相同。</p><p>RoboLab20个任务/方法组合的原生控制时域全部一致；视频最终槽位不是配对种子，也未证明逐槽位决策预算。</p><p><a href="'+E(recovery['source_url'],quote=True)+'">公开原始数据集（固定版本）</a> · '+E(recovery['attribution'])+' 完整RGB档案及隐藏物理、模型状态尚未核验；原源码存在多个已归档版本。</p></section>'
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>与原 blog 的逐项对照</title><style>body{font:16px/1.65 system-ui,sans-serif;max-width:1200px;margin:auto;padding:24px;color:#182238;background:#f6f8fb}h1,h2{line-height:1.3}a{color:#1555b0}.panel{background:white;border:1px solid #dce2ec;border-radius:12px;padding:18px;margin:20px 0}.scroll{overflow-x:auto}table{border-collapse:collapse;min-width:620px;width:100%}th,td{text-align:left;border-bottom:1px solid #e1e6ef;padding:9px;font-size:14px}th{background:#eef2f9}li{margin:8px 0}details{margin:20px 0}code{overflow-wrap:anywhere}@media(max-width:600px){body{padding:14px}}</style><main><a href="scenes.html">← 复现报告</a><h1>与原 blog 的逐项对照</h1><div class="panel"><strong>两方法200回合执行和审计已完成；历史等价性尚未证明。</strong><p>本页比较独立运行与作者公开快照。相同总成功数不能证明案例结果或控制实现一致，数值差异也不能单独定位原因。</p><p><a href="data/blog-comparison.json">下载完整对照 JSON</a> · <a href="data/reproduction-completion.json">查看原始执行验收证明</a> · <a href="https://github.com/anonymous-report-421/GPT-as-Policy">作者公开源码</a></p></div>'+recovery_panel+'<h2>RoboDojo 主结果与执行统计</h2>'+main+'<p>'+correction+'</p><h2>逐任务比较</h2>'+tasks+lab+document+'<h2>共同案例对照</h2><p>共同49对、98条方法回合的案例ID与五个种子字段相同；完整历史物理初态未核验。'+E(changed)+'。layout4与layout5保持分列，未合并为相同案例。</p><details><summary>展开98条共同案例</summary>'+paired+'</details><h2>协议与来源限制</h2><ul>'+''.join('<li>'+E(t)+'</li>' for t in value['limitations'])+'</ul><p>原RoboLab总数为 Direct49/50、Hybrid46/50；本次同为49/50、46/50，逐任务表展示了失败分布差异。两批历史初态未配对，不能计算逐seed一致率。</p><p>原数据固定提交：<code>'+E(value['original_sources']['GPT-as-Policy']['commit'])+'</code>；网站数据提交：<code>'+E(value['original_sources']['public-website']['commit'])+'</code>。文件SHA与来源URL见对照JSON；新的统计提取证据独立封存，原200回合验收证明不改写。</p></main></html>'

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
