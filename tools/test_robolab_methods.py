"""Supplemental report preserves first failures, refuses audit gaps, and separates scores."""
import json,tempfile,unittest
from pathlib import Path
from build_gpt_site import write,digest
from build_robolab_methods import eligible,select,summarize


class RoboLabPublication(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.entry=dict(task='blocks',seed=0,method='gpt_only')
    def fixture(self,name,success=False):
        run=self.root/name
        result=dict(complete=True,terminated=success,truncated=not success,success=success,step_id=3,decisions=1,pi05_inference_calls=0)
        identity=dict(task='blocks',seed=0,evaluation_method='gpt_only',initial_state_hash='a'*64,max_episode_steps=3)
        summary=dict(complete=True,terminated=success,truncated=not success,success=success,control_steps=3,task='blocks',seed=0,max_episode_steps=3,native_max_episode_steps=3)
        for file,data in (('rollout/result.json',result),('rollout/run.json',identity),('rollout/codex_workspace/worker.json',dict(model='gpt-6-astra')),('remote/sim/episode/summary.json',summary)):write(run/file,data)
        proof=dict(verified=True,complete_episode=True,scope='complete_native_episode',method='gpt_only',model='gpt-6-astra',reasoning_effort='xhigh',native_actions=3,decisions=1,max_absolute_action_error=0,
            actions_by_mode=dict(student=0,edit=0,eef=3),terminal={k:result[k] for k in ('terminated','truncated','success')},initial_state_hash='a'*64,pi05_inference_calls=0,student_identity_sha256=None,
            files_sha256={file:digest(run/file) for file in ('rollout/result.json','rollout/run.json','rollout/codex_workspace/worker.json','remote/sim/episode/summary.json')})
        write(run/'complete_action_audit.json',proof)
        return run
    def test_first_complete_failure_is_retained(self):
        failed=self.fixture('first');success=self.fixture('later',True)
        chosen,values,status=select([(success,dict(started_utc='2')),(failed,dict(started_utc='1'))],self.entry)
        self.assertEqual(chosen,failed);self.assertFalse(values[0]['success']);self.assertEqual(status,'complete')
    def test_audit_gap_blocks_later_success(self):
        first=self.fixture('first');success=self.fixture('later',True);(first/'complete_action_audit.json').unlink()
        chosen,values,status=select([(first,dict(started_utc='1')),(success,dict(started_utc='2'))],self.entry)
        self.assertEqual(chosen,first);self.assertIsNone(values);self.assertEqual(status,'audit_pending')
    def test_stale_terminal_or_wrong_native_horizon_is_rejected(self):
        for file,key,value in (('rollout/result.json','success',True),('remote/sim/episode/summary.json','native_max_episode_steps',2)):
            with self.subTest(file=file):
                run=self.fixture(key);data=json.loads((run/file).read_text());data[key]=value;write(run/file,data)
                with self.assertRaises(AssertionError):eligible(run,self.entry)
    def test_partial_attempt_never_counts_as_complete(self):
        run=self.fixture('partial');result=json.loads((run/'rollout/result.json').read_text());result['complete']=False;write(run/'rollout/result.json',result)
        self.assertEqual(select([(run,dict(started_utc='1'))],self.entry),(None,None,'pending'))
    def test_paired_subset_has_an_independent_denominator(self):
        cases=[dict(case_id='a',paired_complete=True),dict(case_id='b',paired_complete=False)]
        episodes=[dict(case_id='a',method='gpt_only',success=False),dict(case_id='a',method='pi05_plus_gpt',success=True),dict(case_id='b',method='gpt_only',success=True)]
        value=summarize(cases,episodes)
        self.assertEqual(value['complete_method_runs'],3);self.assertEqual(value['completed_pairs'],1)
        self.assertEqual(value['methods']['gpt_only']['all_completed']['success_rate'],.5)
        self.assertEqual(value['methods']['gpt_only']['paired_completed']['success_rate'],0)


if __name__=='__main__':unittest.main()
