"""Regression oracles for score eligibility, paired denominators, and rerenders."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from build_gpt_site import check_episode, digest, first_complete, summarize, write
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


if __name__ == '__main__':
    unittest.main()
