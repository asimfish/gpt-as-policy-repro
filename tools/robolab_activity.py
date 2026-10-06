"""Sanitized live activity, independent of native outcome eligibility."""
import json
from pathlib import Path
import re


def read(path, default=None):
    try:return json.loads(path.read_text())
    except FileNotFoundError:return default


def activity(source):
    frozen=read(source/'fixtures/robolab_two_methods_frozen.json',{})
    allowed={(r['task'],r['seed'],r['method']) for r in frozen.get('entries',[])}
    reservations=read(source/'robolab_gpt_parallel_leases.json')
    records=[]
    if reservations is None:
        records=[read(source/'robolab_gpt_active.json',{})]
    else:
        for lease in reservations['leases']:
            identity=(lease['task'],lease['seed'],lease['method'])
            assert identity in allowed and type(lease['seed']) is int
            prefix='direct_' if lease['method']=='gpt_only' else 'hybrid_'
            assert re.fullmatch(prefix+r'20[0-9]{6}T[0-9]{6}Z_'+re.escape(lease['task'])+'_seed'+str(lease['seed']),lease['attempt'])
            record=read(source/'robolab_gpt_campaign'/lease['attempt']/'attempt.json')
            if record:
                assert (record['task'],record['seed'],record['method'],record['attempt'])==(*identity,lease['attempt'])
                records.append(record)
    rows=[]
    for record in records:
        if not record or record.get('finished_utc') or record.get('status') not in ('starting','controller_running','controller_finished'):
            continue
        assert (record['task'],record['seed'],record['method']) in allowed
        workspace=record.get('local_workspace')
        progress=read(Path(workspace)/'rollout/progress.json',{}) if workspace else {}
        step=progress.get('step_id',0)
        assert type(step) is int and step>=0
        rows.append(dict(task=record['task'],seed=record['seed'],method=record['method'],
            status=record['status'],started_utc=record.get('started_utc'),observed_control_steps=step))
    assert len(rows)<=3 and len({(r['task'],r['seed'],r['method']) for r in rows})==len(rows)
    return rows
