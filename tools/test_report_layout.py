"""Presentation must preserve incomplete results and separate cohort denominators."""
import json
from pathlib import Path
import tempfile
import unittest
from report_layout import chart,decorate_board


class ReportLayoutTests(unittest.TestCase):
    def test_unknown_metric_is_not_drawn_as_a_zero_score(self):
        output=chart('score','complete native results',[('pending',None,'n=0','direct')],'score')
        self.assertIn('尚无完整成绩',output)
        self.assertIn('<b>—</b>',output)
        self.assertNotIn('width:',output)

    def test_out_of_range_chart_values_are_rejected(self):
        for value in [-1,101]:
            with self.assertRaises(AssertionError):chart('score','',[('case',value,'','direct')],'score')

    def test_home_uses_selected_panel_without_combining_original_cohort(self):
        def data(count,pairs):
            methods={m:{'all_completed':{'successes':wins,'evaluated':50,'success_rate':wins/50,'mean_score':score}}
                     for m,wins,score in [('gpt_only',13,.395),('pi05_plus_gpt',21,.548)]}
            return {'snapshot':'2026-10-10T11:11:00Z','summary':{'complete_method_runs':count,'completed_pairs':pairs,'methods':methods}}
        original=data(99,49);selected=data(100,50);lab=data(100,50)
        # Match the legacy template's attribute order, which differs from the
        # generated method sections and must not prevent archive wrapping.
        document='<html data-theme="dark"><head></head><body><header class="topbar"></header><main><section class="hero" id="overview"></section><nav class="section-nav"></nav><!-- GPT_PROGRESS_START --><section></section><!-- GPT_PROGRESS_END --><section id="results" class="report-section">legacy-results</section><section id="reading" class="report-section"></section><section id="downloads" class="downloads panel"></section></main></body></html>'
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);(out/'data').mkdir()
            for name,value in [('gpt-methods-valid-progress.json',selected),('robolab-methods-progress.json',lab)]:
                (out/'data'/name).write_text(json.dumps(value))
            before={p.name:p.read_bytes() for p in (out/'data').iterdir()}
            output=decorate_board(document,out,original)
            self.assertIn('200 个完整回合',output)
            self.assertIn('100 个配对案例',output)
            self.assertIn('原面板 99 / 100 条',output)
            self.assertIn('两个面板不能相加作为独立样本',output)
            self.assertIn('<details class="auxiliary-archive">',output)
            self.assertIn('legacy-results</section></details>',output)
            self.assertIn('id="reference-links"',output)
            self.assertIn('datetime="2026-10-10T11:11:00Z"',output)
            self.assertIn('完整可计分主方法回合：99 / 100',output)
            self.assertEqual(output,decorate_board(output,out,original))
            self.assertEqual(before,{p.name:p.read_bytes() for p in (out/'data').iterdir()})


if __name__=='__main__':unittest.main()
