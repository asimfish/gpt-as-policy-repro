"""Denominator, alignment and public-data drift oracles for blog comparison."""
import json,shutil,tempfile,unittest
from pathlib import Path
from blog_comparison import budget_observation,compare_cases,indexed,metrics,task_comparison,verify_public,recovered_summary


def row(case='shared',success=False,score=None):
    return dict(case_id=case,method='gpt_only',task='task',success=success,score=score,
                steps=10,chunks=2,corrected_steps=0,tokens=None,seeds={'layout_id':0},evidence='data/evidence.json')

class BlogComparisonTest(unittest.TestCase):
    def test_native_completion_coverage_does_not_impute_unknown_or_adjudicated_score(self):
        a=dict(row(success=True,score=1),native_complete=True)
        b=dict(row(),native_complete=False)
        result=metrics([a,b]);self.assertEqual(result['native_complete'],1)
        self.assertEqual(result['adjudicated_failures'],1);self.assertEqual(result['score_samples'],1)
        self.assertIsNone(metrics([row()])['native_complete'])
        self.assertIsNone(metrics([a,row()])['adjudicated_failures'])

    def test_recovered_summary_rejects_false_match_claim(self):
        docs=Path(__file__).resolve().parents[1]/'docs'
        value=json.loads((docs/'data/blog-comparison.json').read_text())
        recovery=value.get('original_record_recovery')
        if recovery is None:self.skipTest('Recovery page not built yet')
        rows=recovery['configuration_comparison']['robodojo']['cases']
        recovered_summary(rows)
        rows[0]['recorded_field_matches']['states']=not rows[0]['recorded_field_matches']['states']
        with self.assertRaises(AssertionError):recovered_summary(rows)

    def test_missing_scores_keep_success_denominator_and_are_not_zero_imputed(self):
        result=metrics([row(success=True,score=1),row(score=None)])
        self.assertEqual(result['episodes'],2);self.assertEqual(result['success_rate'],.5)
        self.assertEqual(result['score_samples'],1);self.assertEqual(result['mean_score'],1)
        self.assertIsNone(result['tokens']);self.assertEqual(result['token_samples'],0)

    def test_unknown_tokens_stay_unknown_and_cached_input_is_not_added_twice(self):
        a=row();a['tokens']=dict(totalTokens=100,inputTokens=90,cachedInputTokens=80,
             cacheWriteInputTokens=0,outputTokens=10,reasoningOutputTokens=5)
        result=metrics([a,row()]);self.assertEqual(result['tokens']['totalTokens'],100)
        self.assertEqual(result['token_samples'],1)

    def test_correction_fraction_uses_executed_control_steps(self):
        a=row();a.update(steps=100,chunks=7,corrected_steps=15)
        self.assertEqual(metrics([a])['correction_fraction'],.15)
        a['corrected_steps']=101
        with self.assertRaises(AssertionError):metrics([a])

    def test_replacement_stays_outside_common_case_denominator(self):
        old=[row(),row('layout4')];new=[row(success=True),row('layout5')]
        value=compare_cases(old,new)
        self.assertEqual(value['common_method_runs'],1)
        self.assertEqual(value['methods']['gpt_only']['changed_success_outcomes'],1)
        self.assertEqual(value['original_only'],[dict(case_id='layout4',method='gpt_only')])
        self.assertEqual(value['reproduction_only'],[dict(case_id='layout5',method='gpt_only')])

    def test_duplicate_or_different_seed_identity_is_rejected(self):
        with self.assertRaises(AssertionError):indexed([row(),row()])
        other=row();other['seeds']['layout_id']=1
        with self.assertRaises(AssertionError):compare_cases([row()],[other])

    def test_equal_total_successes_do_not_erase_task_differences(self):
        old=[row('a',True),row('b',False)];new=[row('a',False),row('b',True)]
        for rows in (old,new):
            rows[0]['task']='A';rows[1]['task']='B'
            rows.extend([dict(rows[0],method='pi05_plus_gpt'),dict(rows[1],method='pi05_plus_gpt')])
        compared=task_comparison(old,new)
        a=next(t for t in compared if t['task']=='A' and t['method']=='gpt_only')
        self.assertEqual(a['original']['successes'],1);self.assertEqual(a['reproduction']['successes'],0)
        self.assertEqual(sum(r['success'] for r in old),sum(r['success'] for r in new))

    def test_task_denominator_and_boolean_counter_corruption_rejected(self):
        with self.assertRaises(AssertionError):task_comparison([row()],[])
        a=row();a['steps']=True
        with self.assertRaises(AssertionError):metrics([a])

    def test_budget_prefix_keeps_unfinished_unknown_and_includes_boundary(self):
        records=[dict(row(success=True),decision_events=180),dict(row(),decision_events=170),
                 dict(row(success=True),decision_events=181),dict(row(),decision_events=600)]
        observed=budget_observation(records,180)
        self.assertEqual(observed['success_already_observed'],1)
        self.assertEqual(observed['native_failure_already_observed'],1)
        self.assertEqual(observed['still_unfinished_in_recorded_prefix'],2)
        self.assertEqual(budget_observation(records,500)['still_unfinished_in_recorded_prefix'],1)

    def test_board_rerender_keeps_one_comparison_panel(self):
        from render_gpt_progress import render
        docs=Path(__file__).resolve().parents[1]/'docs'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'data').mkdir()
            for name in ['index.html','scenes.html','data/gpt-methods-progress.json',
                         'data/gpt-methods-valid-progress.json','data/blog-comparison.json']:
                shutil.copyfile(docs/name,root/name)
            render(root);render(root)
            for name in ['index.html','scenes.html','gpt-methods.html']:
                self.assertEqual((root/name).read_text().count('id="blog-comparison-summary"'),1)

    def test_real_public_comparison_rejects_changed_native_outcome(self):
        docs=Path(__file__).resolve().parents[1]/'docs'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'data').mkdir()
            for name in ['data/blog-comparison.json','data/gpt-methods-valid-progress.json',
                         'data/robolab-methods-progress.json','data/reproduction-completion.json',
                         'blog-comparison.html','scenes.html']:
                shutil.copyfile(docs/name,root/name)
            verify_public(root)
            path=root/'data/blog-comparison.json';value=json.loads(path.read_text())
            value['reproduction_episodes'][0]['success']=not value['reproduction_episodes'][0]['success']
            path.write_text(json.dumps(value))
            with self.assertRaises(AssertionError):verify_public(root)

    def test_lab_task_outcome_drift_is_rejected(self):
        docs=Path(__file__).resolve().parents[1]/'docs'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'data').mkdir()
            for name in ['data/blog-comparison.json','data/gpt-methods-valid-progress.json',
                         'data/robolab-methods-progress.json','data/reproduction-completion.json',
                         'blog-comparison.html','scenes.html']:
                shutil.copyfile(docs/name,root/name)
            path=root/'data/blog-comparison.json';value=json.loads(path.read_text())
            value['robolab']['tasks'][0]['reproduction_successes']=0
            path.write_text(json.dumps(value))
            with self.assertRaises(AssertionError):verify_public(root)

if __name__=='__main__':unittest.main()
