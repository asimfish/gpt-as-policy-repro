import json
from pathlib import Path
import tempfile
import unittest

from build_gpt_site import robolab_status,write
from build_robolab_methods import build
from render_gpt_progress import robolab_html
from robolab_activity import activity


class LiveActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.source=Path(self.temp.name)/'source';self.out=Path(self.temp.name)/'site'
        self.tasks=['BlocksInBinTask']+['task'+str(i) for i in range(9)]
        write(self.source/'fixtures/robolab_two_methods_frozen.json',dict(cases=50,entries=[
            dict(task=t,seed=s,method=m) for t in self.tasks for s in range(5) for m in ('gpt_only','pi05_plus_gpt')]))
    def worker(self,seed,slot,steps):
        attempt=f'direct_20261006T000000Z_BlocksInBinTask_seed{seed}'
        workspace=self.source/f'private-workspace-{slot}'
        record=dict(task='BlocksInBinTask',seed=seed,method='gpt_only',attempt=attempt,
            status='controller_running',worker_slot=slot,local_workspace=str(workspace),
            remote_output='/private/remote',secret='never-export',started_utc='2026-10-06T00:00:00Z')
        write(self.source/'robolab_gpt_campaign'/attempt/'attempt.json',record)
        write(workspace/'rollout/progress.json',dict(step_id=steps))
        return dict(task='BlocksInBinTask',seed=seed,method='gpt_only',attempt=attempt)
    def test_three_live_workers_are_visible_and_none_changes_denominators(self):
        leases=[self.worker(i,i,(i+1)*10) for i in range(3)]
        write(self.source/'robolab_gpt_parallel_leases.json',dict(leases=leases))
        exported=robolab_status(self.source)
        self.assertEqual(len(exported['active_runs']),3)
        self.assertEqual([r['observed_control_steps'] for r in exported['active_runs']],[10,20,30])
        self.assertFalse(exported['results_eligible'])
        serialized=json.dumps(exported)
        for private in ('private','secret','workspace','worker_slot','remote_output','attempt'):
            self.assertNotIn(private,serialized)
        data=build(self.source,self.out)
        self.assertEqual(data['summary']['complete_method_runs'],0)
        self.assertEqual(data['summary']['completed_pairs'],0)
        running=[v for c in data['cases'] for v in c['methods'].values() if v['status']=='running']
        self.assertEqual(len(running),3);self.assertTrue(all(v['episode_id'] is None for v in running))
        document=(self.out/'robolab-methods.html').read_text()
        self.assertEqual(document.count('运行中 ·'),3)
        self.assertIn('当前并行推进 3 个独立原生回合',robolab_html(dict(supplementary=dict(robolab=exported))))
    def test_finished_worker_is_omitted_and_stale_legacy_record_is_not_revived(self):
        lease=self.worker(0,0,20)
        path=self.source/'robolab_gpt_campaign'/lease['attempt']/'attempt.json'
        original=json.loads(path.read_text());original['finished_utc']='now';write(path,original)
        write(self.source/'robolab_gpt_active.json',dict(original,finished_utc=None))
        write(self.source/'robolab_gpt_parallel_leases.json',dict(leases=[lease]))
        self.assertEqual(activity(self.source),[])
        self.assertEqual(build(self.source,self.out)['summary']['complete_method_runs'],0)
    def test_native_terminal_with_audit_gap_is_not_relabelled_as_running(self):
        lease=self.worker(0,0,20)
        write(self.source/'robolab_gpt_parallel_leases.json',dict(leases=[lease]))
        write(self.source/'robolab_gpt_campaign'/lease['attempt']/'rollout/result.json',dict(complete=True,truncated=True))
        data=build(self.source,self.out)
        case=next(c for c in data['cases'] if c['task']=='BlocksInBinTask' and c['seed']==0)
        self.assertEqual(case['methods']['gpt_only']['status'],'audit_pending')
        self.assertEqual(data['summary']['complete_method_runs'],0)
    def test_reservation_traversal_and_identity_substitution_fail_closed(self):
        lease=self.worker(0,0,20)
        for change in (dict(attempt='../../private'),dict(seed=4)):
            with self.subTest(change=change):
                write(self.source/'robolab_gpt_parallel_leases.json',dict(leases=[dict(lease,**change)]))
                with self.assertRaises(AssertionError):activity(self.source)


if __name__=='__main__':unittest.main()
