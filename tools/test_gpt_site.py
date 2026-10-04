"""Regression oracles for score eligibility, paired denominators, and rerenders."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

import publish_gpt_progress as publisher

from build_gpt_site import check_episode, digest, first_complete, summarize, write, robolab_status
from render_gpt_progress import render
from publish_gpt_progress import check_worktree


class EligibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name) / 'gpt_only'
        self.identity = dict(panel_id='p', panel_sha256='a'*64, case_id='task__standard__g0__l0',
                             task='task', runtime_task='task', variant='standard', eval_seed=0,
                             layout_id=0, reset_seed=0, simulator_initial_seed=0,
                             policy_rng_seed=0, layout_sha256='b'*64)
        self.result = dict(complete=True, success=False, terminated=False, truncated=True,
                           step_id=3, decisions=1, evaluation_case=self.identity)
        self.outcome = dict(complete=True, valid_for_success_rate=True, native_success=False,
                            native_control_steps=3, native_score=0.25, evaluation_case=self.identity)
        write(self.run / 'rollout/result.json', self.result)
        write(self.run / 'sim/evaluation_outcome.json', self.outcome)
        write(self.run / 'rollout/run.json', dict(model='gpt-6-astra'))
        write(self.run / 'rollout/codex_workspace/worker.json', dict(model='gpt-6-astra'))
        self.proof = dict(verified=True, complete_episode=True, scope='complete_native_episode',
                          model='gpt-6-astra', reasoning_effort='xhigh', pi05_inference_calls=0,
                          native_actions=3, decisions=1, max_absolute_action_error=0,
                          files_sha256={name: digest(self.run / name) for name in
                                        ('rollout/result.json', 'sim/evaluation_outcome.json',
                                         'rollout/run.json', 'rollout/codex_workspace/worker.json')})
        write(self.run / 'complete_action_audit.json', self.proof)

    def test_complete_native_failure_is_eligible(self):
        result, outcome, _ = check_episode(self.run, self.identity)
        self.assertFalse(result['success'])
        self.assertEqual(outcome['native_score'], 0.25)

    def test_prefix_audit_is_not_complete_evidence(self):
        self.proof['complete_episode'] = False
        write(self.run / 'complete_action_audit.json', self.proof)
        with self.assertRaises(AssertionError):
            check_episode(self.run, self.identity)

    def test_changed_native_success_rejected_even_if_counters_match(self):
        self.result['success'] = True
        write(self.run / 'rollout/result.json', self.result)
        with self.assertRaises(AssertionError):
            check_episode(self.run, self.identity)

    def test_changed_model_input_rejected(self):
        write(self.run / 'rollout/codex_workspace/worker.json', dict(model='other'))
        with self.assertRaises(AssertionError):
            check_episode(self.run, self.identity)

    def test_wrong_frozen_layout_rejected(self):
        expected = dict(self.identity, layout_sha256='c'*64)
        with self.assertRaises(AssertionError):
            check_episode(self.run, expected)

    def test_incomplete_run_never_counted_as_task_failure(self):
        self.result['complete'] = False
        write(self.run / 'rollout/result.json', self.result)
        with self.assertRaises(AssertionError):
            check_episode(self.run, self.identity)

    def test_audit_missing_terminal_input_binding_rejected(self):
        del self.proof['files_sha256']['rollout/result.json']
        write(self.run / 'complete_action_audit.json', self.proof)
        with self.assertRaises(AssertionError):
            check_episode(self.run, self.identity)


class SelectionTests(unittest.TestCase):
    def test_first_valid_failure_preserved_over_later_success(self):
        early = ({'started_utc': '2026-01-01', 'run_id': 'early', 'eligible': True}, None, {'success': False})
        late = ({'started_utc': '2026-01-02', 'run_id': 'late', 'eligible': True}, None, {'success': True})
        self.assertEqual(first_complete([late, early]), early)

    def test_missing_first_audit_blocks_cherry_picking_later_run(self):
        early = ({'started_utc': '2026-01-01', 'run_id': 'early', 'eligible': False}, None, None)
        late = ({'started_utc': '2026-01-02', 'run_id': 'late', 'eligible': True}, None, {'success': True})
        self.assertIsNone(first_complete([late, early]))

    def test_all_completed_and_paired_denominators_differ(self):
        cases = [dict(case_id='a'), dict(case_id='b')]
        episodes = [dict(case_id='a', method='gpt_only', success=False, score=0.0),
                    dict(case_id='a', method='pi05_plus_gpt', success=True, score=1.0),
                    dict(case_id='b', method='gpt_only', success=True, score=1.0)]
        summary = summarize(cases, episodes)
        self.assertEqual(summary['completed_pairs'], 1)
        self.assertEqual(summary['complete_method_runs'], 3)
        self.assertEqual(summary['methods']['gpt_only']['all_completed']['success_rate'], .5)
        self.assertEqual(summary['methods']['gpt_only']['paired_completed']['success_rate'], 0.0)


class RenderTests(unittest.TestCase):
    def test_rerender_is_idempotent_and_old_zero_is_removed(self):
        data = dict(schema='gpt_policy_progress.v2', snapshot='2026-01-01T00:00:00Z',
                    cases=[], episodes=[], attempts=[], interruptions=dict(by_reason={}))
        data['summary'] = summarize([], [])
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            for name in ('index.html', 'scenes.html'):
                (out / name).write_text('<html><head></head><body>完整可计分主方法回合：0<!-- GPT_PROGRESS_START --><!-- GPT_PROGRESS_END --></body></html>')
            write(out / 'data/gpt-methods-progress.json', data)
            render(out)
            first = [(out / name).read_bytes() for name in ('index.html', 'scenes.html', 'gpt-methods.html')]
            render(out)
            self.assertEqual(first, [(out / name).read_bytes() for name in ('index.html', 'scenes.html', 'gpt-methods.html')])
            self.assertEqual(first[0], first[1])


class SupplementaryStatusTests(unittest.TestCase):
    def test_robolab_partial_progress_stays_unscored_and_private_inputs_do_not_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            workspace = source/'private-workspace'
            tasks = ['BlocksInBinTask'] + ['task'+str(i) for i in range(9)]
            write(source/'fixtures/robolab_two_methods_frozen.json',
                  dict(cases=50, entries=[dict(task=t,seed=s,method=m) for t in tasks
                       for s in range(5) for m in ('gpt_only','pi05_plus_gpt')]))
            write(source/'robolab_gpt_active.json', dict(status='controller_running',
                  task='BlocksInBinTask', seed=0, method='pi05_plus_gpt',
                  local_workspace=str(workspace), remote_output='/private/remote',
                  secret='must-not-export'))
            write(workspace/'rollout/progress.json', dict(step_id=30))
            exported = robolab_status(source)
            self.assertFalse(exported['results_eligible'])
            self.assertEqual(exported['observed_control_steps'], 30)
            self.assertNotIn('complete_method_runs', exported)
            self.assertNotIn('private', publisher.json.dumps(exported))
            self.assertNotIn('secret', exported)


class PublicationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        for args in (('init', '-q', '-b', 'docs/site'),
                     ('remote', 'add', 'origin', 'https://github.com/asimfish/gpt-as-policy-repro.git')):
            subprocess.run(['git', '-C', str(self.repo), *args], check=True, capture_output=True)

    def test_unrelated_source_work_prevents_publication(self):
        (self.repo / 'user.py').write_text('user work\n')
        with self.assertRaisesRegex(AssertionError, 'unrelated'):
            check_worktree(self.repo)

    def test_user_staged_work_is_preserved(self):
        (self.repo / 'user.py').write_text('user work\n')
        subprocess.run(['git', '-C', str(self.repo), 'add', 'user.py'], check=True)
        with self.assertRaisesRegex(AssertionError, 'staging'):
            check_worktree(self.repo)
        self.assertEqual(subprocess.check_output(['git', '-C', str(self.repo), 'diff', '--cached', '--name-only']).decode().strip(), 'user.py')

    def test_owned_generated_output_can_be_retried(self):
        (self.repo / 'docs').mkdir()
        (self.repo / 'docs/gpt-methods.html').write_text('generated output\n')
        check_worktree(self.repo)

    def staged_pulse(self):
        publisher.git(self.repo,'config','user.name','Report test')
        publisher.git(self.repo,'config','user.email','report-test@example.invalid')
        (self.repo/'docs').mkdir()
        (self.repo/'docs/scenes.html').write_text('previous report')
        publisher.git(self.repo,'add','--','docs/scenes.html')
        publisher.git(self.repo,'commit','-m','[report/test]: create previous report')
        (self.repo/'docs/scenes.html').write_text('next report')
        publisher.git(self.repo,'add','--','docs/scenes.html')
        publisher.record_transaction(self.repo,self.repo,['docs/scenes.html'],'[report/build]: retry report')

    def test_interrupted_owned_staging_resumes_without_rebuilding_or_erasing_it(self):
        self.staged_pulse()
        publisher.resume_transaction(self.repo,self.repo)
        self.assertEqual(publisher.git(self.repo,'show','HEAD:docs/scenes.html'),'next report')
        self.assertEqual(publisher.git(self.repo,'diff','--cached','--name-only'),'')
        self.assertFalse((self.repo/'report_publication_transaction.json').exists())

    def test_concurrent_user_staging_blocks_transaction_recovery(self):
        self.staged_pulse()
        (self.repo/'user.py').write_text('preserved user work')
        publisher.git(self.repo,'add','--','user.py')
        with self.assertRaisesRegex(AssertionError,'staging'):
            publisher.resume_transaction(self.repo,self.repo)
        self.assertIn('user.py',publisher.git(self.repo,'diff','--cached','--name-only'))

    def test_publication_waits_for_deployment_instead_of_abandoning_proof(self):
        write(self.repo / 'docs/data/gpt-methods-progress.json', dict(episodes=[], summary=dict(complete_method_runs=0)))
        with patch.object(publisher, 'check_worktree'), patch.object(publisher.subprocess, 'run'), \
             patch.object(publisher, 'git', return_value=''), patch.object(publisher, 'credential_env', return_value={}), \
             patch.object(publisher, 'verify_online', side_effect=[AssertionError('Pages not ready'), None]) as verify, \
             patch('time.sleep'):
            publisher.publish(self.repo, self.repo, self.repo, 'http://example.invalid')
        self.assertEqual(verify.call_count, 2, 'A delayed deployment must be verified before this publication cycle ends')

    def test_deployment_timeout_preserves_last_verified_proof(self):
        previous = dict(commit='previous', status='published_and_http_verified')
        write(self.repo/'online_publication.json', previous)
        with patch.object(publisher, 'verify_online', side_effect=OSError('offline')), \
             patch.object(publisher, 'git', return_value='next'), \
             patch.object(publisher.time, 'monotonic', side_effect=[0, 1]):
            self.assertFalse(publisher.await_online(self.repo, self.repo, timeout=0))
        self.assertEqual(publisher.json.loads((self.repo/'online_publication.json').read_text()), previous)
        self.assertEqual(publisher.json.loads((self.repo/'online_publication_pending.json').read_text())['commit'], 'next')

    def test_online_proof_uses_committed_data_not_mutable_worktree(self):
        committed = {'scenes.html': b'page', 'gpt-methods.html': b'methods',
                     'assets/gpt.js': b'js', 'assets/gpt.css': b'css',
                     'data/gpt-methods-progress.json': b'{"summary":{"complete_method_runs":1},"snapshot":"committed"}',
                     'data/robolab-gpt-prefix-audit.json': b'prefix',
                     'data/infrastructure-bundle.json': b'{"archive":"downloads/infrastructure_bundle_20261002.tar.gz"}',
                     'downloads/infrastructure_bundle_20261002.tar.gz': b'verified archive'}
        write(self.repo/'docs/data/gpt-methods-progress.json', dict(summary=dict(complete_method_runs=99), snapshot='uncommitted'))
        class Response:
            status = 200
            def __init__(self, value): self.value = value
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return self.value
        with patch.object(publisher, 'git', side_effect=lambda repo,*args,**kw: '\n'.join('docs/'+name for name in ('data/robolab-gpt-prefix-audit.json','data/infrastructure-bundle.json')) if args[0]=='ls-tree' else 'a'*40), \
             patch.object(publisher.subprocess, 'check_output', side_effect=lambda args, **kw: committed[args[-1].split(':docs/',1)[1]]), \
             patch.object(publisher.urllib.request, 'urlopen', side_effect=lambda req, **kw: Response(committed[urlsplit(req.full_url).path.split('/gpt-as-policy-repro/',1)[1]])):
            publisher.verify_online(self.repo, self.repo)
        proof = publisher.json.loads((self.repo/'online_publication.json').read_text())
        self.assertEqual(proof['gpt_summary']['complete_method_runs'], 1)
        self.assertEqual(proof['snapshot'], 'committed')
        self.assertEqual({row['file'] for row in proof['files']},set(committed))
        self.assertTrue(all(row['matches'] for row in proof['files']))


if __name__ == '__main__':
    unittest.main()
