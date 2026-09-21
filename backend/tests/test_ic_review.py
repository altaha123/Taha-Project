"""
Investment Committee review — network-free regressions.

The tests that matter here are the identities. A risk budget that does not
reconcile to portfolio volatility, a portfolio multiple that a single
expensive holding can drag anywhere, or a pro-forma book whose weights do not
sum to 100 would all still render happily on the page and be wrong. Each of
those is pinned below, alongside the rule the whole report is built on: an
unavailable input produces an absent number and a stated reason, never a
default that becomes a conclusion.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ic_review
import portfolio

NOW = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
SCAN = {'scanned_at': '2026-09-10T09:00:00+00:00'}


def frame(seed=1, vol=.012, n=280, adjusted=True, end='2026-09-10'):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(.0004, vol, n)))
    df = pd.DataFrame({'Close': close}, index=pd.bdate_range(end=end, periods=n))
    if adjusted:
        df.attrs['adjustment'] = 'adjusted'
    return df


def holding(symbol, value, cost=None, score=65, sector='Energy', pe=None, pb=None):
    return dict(symbol=symbol, name=symbol, qty=10, price=value / 10, value=value,
                cost=cost, buy_price=(cost / 10 if cost else None), composite=score,
                sector=sector, technical=60, fundamental=62,
                price_as_of=NOW.isoformat(), price_source='Test fixture',
                valuation={'pe': pe, 'pb': pb, 'market_cap': 1e11},
                altaha_score_v4={'position': {'confidence': .8,
                                              'pillars': {'quality': score, 'momentum': 55}},
                                 'factor_ledger': []})


def review(rows, histories=None, benchmark=None, policy=None):
    report = portfolio.build_report(rows, SCAN, policy, now=NOW, histories=histories,
                                    benchmark_history=benchmark)
    return report, report['ic_review']


BOOK = [holding('AAA', 400000, 300000, 74, 'Financial Services', pe=22, pb=3.0),
        holding('BBB', 300000, 320000, 55, 'Financial Services', pe=48, pb=6.0),
        holding('CCC', 200000, 150000, 38, 'Information Technology', pe=-9, pb=2.0),
        holding('DDD', 100000, 90000, 66, 'Energy', pe=13, pb=1.2)]
HISTORIES = {'AAA': frame(1, .011), 'BBB': frame(2, .021),
             'CCC': frame(3, .030), 'DDD': frame(4, .009)}


class RiskBudget(unittest.TestCase):
    def test_contributions_reconcile_to_portfolio_volatility(self):
        """The identity the whole table rests on: Σ wᵢ·MCTRᵢ = σₚ."""
        _, ic = review(BOOK, HISTORIES)
        risk = ic['risk_budget']
        total = sum(h['contribution_pct'] for h in risk['holdings'])
        self.assertAlmostEqual(total, risk['volatility_pct'], places=1)
        self.assertAlmostEqual(sum(h['risk_share_pct'] for h in risk['holdings']), 100, places=1)

    def test_risk_share_differs_from_capital_share(self):
        """The point of the section: a volatile name carries more than its weight."""
        _, ic = review(BOOK, HISTORIES)
        by_symbol = {h['symbol']: h for h in ic['risk_budget']['holdings']}
        self.assertGreater(by_symbol['CCC']['risk_share_pct'], by_symbol['CCC']['weight_pct'])
        self.assertLess(by_symbol['DDD']['risk_share_pct'], by_symbol['DDD']['weight_pct'])
        self.assertAlmostEqual(by_symbol['CCC']['risk_vs_capital_pp'],
                               by_symbol['CCC']['risk_share_pct'] - by_symbol['CCC']['weight_pct'],
                               places=2)

    def test_diversification_ratio_is_at_least_one(self):
        _, ic = review(BOOK, HISTORIES)
        risk = ic['risk_budget']
        self.assertGreaterEqual(risk['diversification_ratio'], 1.0)
        self.assertGreaterEqual(risk['weighted_average_volatility_pct'], risk['volatility_pct'])

    def test_unadjusted_history_is_refused_not_mixed_in(self):
        """Dhan's adjustment status is unverified; those series stay out."""
        _, ic = review(BOOK, {k: frame(i, .01, adjusted=False) for i, k in enumerate(HISTORIES)})
        self.assertFalse(ic['risk_budget']['available'])
        self.assertIn('adjusted', ic['risk_budget']['reason'])
        self.assertEqual(ic['risk_budget']['holdings'], [])

    def test_short_history_states_the_sample_it_wanted(self):
        short = {k: frame(i, .01, n=40) for i, k in enumerate(HISTORIES)}
        _, ic = review(BOOK, short)
        self.assertFalse(ic['risk_budget']['available'])
        self.assertIn(str(ic_review.MIN_OBSERVATIONS), ic['risk_budget']['reason'])
        self.assertIn('AAA', ic['risk_budget']['reason'])

    def test_value_at_risk_reports_both_bases(self):
        _, ic = review(BOOK, HISTORIES)
        var = ic['risk_budget']['value_at_risk']['95']
        self.assertGreater(var['historical_pct'], 0)
        self.assertGreater(var['parametric_pct'], 0)
        # A month of the same volatility is √21 larger, not 21 times larger.
        self.assertAlmostEqual(var['monthly_parametric_pct'],
                               var['parametric_pct'] * np.sqrt(21), places=1)

    def test_coverage_is_disclosed_when_one_holding_has_no_history(self):
        partial = {k: v for k, v in HISTORIES.items() if k != 'AAA'}
        _, ic = review(BOOK, partial)
        risk = ic['risk_budget']
        self.assertTrue(risk['available'])
        self.assertNotIn('AAA', risk['symbols'])
        self.assertAlmostEqual(risk['coverage_pct'], 60.0, places=1)


class Benchmark(unittest.TestCase):
    def test_beta_of_the_index_against_itself_is_one(self):
        """A single holding that is the index must return beta 1, R² 1."""
        index = frame(11, .01)
        rows = [holding('AAA', 500000, sector='Energy'), holding('BBB', 500000, sector='Energy')]
        _, ic = review(rows, {'AAA': index, 'BBB': index}, benchmark=index)
        bench = ic['risk_budget']['benchmark']
        self.assertAlmostEqual(bench['beta'], 1.0, places=2)
        self.assertAlmostEqual(bench['r_squared'], 1.0, places=2)
        self.assertAlmostEqual(bench['tracking_error_pct'], 0.0, places=2)

    def test_named_from_the_series_not_from_the_sector_proxy(self):
        index = frame(11, .01)
        index.attrs['name'] = 'Nifty 50'
        _, ic = review(BOOK, HISTORIES, benchmark=index)
        self.assertEqual(ic['risk_budget']['benchmark']['name'], 'Nifty 50')

    def test_missing_benchmark_removes_only_the_benchmark_section(self):
        _, ic = review(BOOK, HISTORIES)
        self.assertNotIn('benchmark', ic['risk_budget'])
        self.assertTrue(ic['risk_budget']['available'])
        self.assertTrue(any(s['id'] == 'risk' for s in ic['sections']))
        self.assertFalse(any(s['id'] == 'sensitivity' for s in ic['sections']))


class Valuation(unittest.TestCase):
    def test_aggregate_multiple_is_harmonic_not_arithmetic(self):
        """Half at 10×, half at 50× is 16.7× of earnings, not 30×."""
        rows = [holding('AAA', 500000, pe=10), holding('BBB', 500000, pe=50)]
        _, ic = review(rows)
        self.assertAlmostEqual(ic['valuation']['portfolio_pe'], 16.67, places=1)

    def test_loss_making_holdings_are_excluded_and_counted(self):
        _, ic = review(BOOK)
        val = ic['valuation']
        self.assertEqual([n['symbol'] for n in val['loss_making']], ['CCC'])
        self.assertAlmostEqual(val['loss_making_weight_pct'], 20.0, places=1)
        self.assertAlmostEqual(val['portfolio_pe_coverage_pct'], 80.0, places=1)

    def test_missing_multiples_are_named_not_assumed(self):
        rows = [holding('AAA', 500000, pe=20), holding('BBB', 500000)]
        _, ic = review(rows)
        self.assertEqual(ic['valuation']['unpriced_multiple_symbols'], ['BBB'])
        self.assertAlmostEqual(ic['valuation']['portfolio_pe'], 20.0, places=2)
        self.assertAlmostEqual(ic['valuation']['portfolio_pe_coverage_pct'], 50.0, places=1)

    def test_earnings_yield_is_the_reciprocal_of_the_multiple(self):
        _, ic = review(BOOK)
        val = ic['valuation']
        self.assertAlmostEqual(val['earnings_yield_pct'], 100 / val['portfolio_pe'], places=1)


class CapitalPlan(unittest.TestCase):
    def test_proforma_weights_sum_to_one_hundred(self):
        _, ic = review(BOOK, HISTORIES)
        plan = ic['capital_plan']
        self.assertTrue(plan['gaps'])
        self.assertAlmostEqual(sum(p['weight_pct'] for p in plan['proforma']), 100, places=0)

    def test_released_capital_matches_the_per_position_arithmetic(self):
        report, ic = review(BOOK, HISTORIES)
        gaps = [b for b in report['breaches']
                if b['rule'] == 'max_stock_pct' and b.get('arithmetic')]
        self.assertAlmostEqual(ic['capital_plan']['released_value'],
                               sum(b['arithmetic']['value'] for b in gaps), places=0)

    def test_a_compliant_book_reports_no_gap_arithmetic(self):
        rows = [holding(chr(65 + i) * 3, 100000, score=65) for i in range(10)]
        _, ic = review(rows)
        self.assertEqual(ic['capital_plan']['gaps'], [])
        self.assertEqual(ic['capital_plan']['released_pct'], 0.0)


class Scorecard(unittest.TestCase):
    def test_unavailable_dimensions_are_omitted_not_imputed(self):
        rows = [holding('AAA', 500000, score=None), holding('BBB', 500000, score=None)]
        _, ic = review(rows)
        card = ic['scorecard']
        self.assertIsNone(next(d for d in card['dimensions'] if d['key'] == 'quality')['score'])
        self.assertLess(card['dimensions_scored'], card['dimensions_total'])

    def test_every_dimension_discloses_its_inputs_and_method(self):
        _, ic = review(BOOK, HISTORIES)
        for dim in ic['scorecard']['dimensions']:
            self.assertTrue(dim['method'])
            self.assertIsInstance(dim['inputs'], dict)

    def test_a_concentrated_book_scores_below_a_diversified_one(self):
        wide = [holding(chr(65 + i) * 3, 100000) for i in range(10)]
        narrow = [holding('AAA', 900000), holding('BBB', 100000)]
        _, wide_ic = review(wide)
        _, narrow_ic = review(narrow)
        construction = lambda ic: next(d for d in ic['scorecard']['dimensions']
                                       if d['key'] == 'construction')['score']
        self.assertGreater(construction(wide_ic), construction(narrow_ic))


class MemoAndAgenda(unittest.TestCase):
    def test_no_section_issues_an_instruction(self):
        """The platform is not registered to tell anyone to trade."""
        _, ic = review(BOOK, HISTORIES)
        prose = ' '.join(p for s in ic['sections'] for p in s['paragraphs']).lower()
        prose += ' ' + ' '.join(str(a['observation']) for a in ic['agenda']).lower()
        for verb in (' you should ', ' we recommend ', ' sell ', ' buy now', ' must exit'):
            self.assertNotIn(verb, prose)

    def test_every_rule_breach_reaches_the_agenda(self):
        report, ic = review(BOOK, HISTORIES)
        titles = {a['title'] for a in ic['agenda']}
        for breach in report['breaches']:
            self.assertIn(breach['title'], titles)

    def test_agenda_items_carry_a_question_and_are_ranked(self):
        _, ic = review(BOOK, HISTORIES)
        self.assertTrue(ic['agenda'])
        self.assertEqual([a['rank'] for a in ic['agenda']], list(range(1, len(ic['agenda']) + 1)))
        for item in ic['agenda']:
            self.assertTrue(item['question'].endswith('?'))
            self.assertTrue(item['observation'])

    def test_sections_are_present_and_each_names_its_evidence(self):
        _, ic = review(BOOK, HISTORIES)
        ids = [s['id'] for s in ic['sections']]
        for expected in ('standing', 'construction', 'risk', 'quality', 'limits'):
            self.assertIn(expected, ids)
        for section in ic['sections']:
            self.assertTrue(section['evidence'])
            self.assertTrue(section['verdict'])

    def test_prose_never_prints_a_fabricated_number_for_a_missing_input(self):
        rows = [holding('AAA', 500000, score=None), holding('BBB', 500000, score=None)]
        _, ic = review(rows)
        prose = ' '.join(p for s in ic['sections'] for p in s['paragraphs'])
        self.assertIn('unavailable', prose.lower())
        self.assertNotIn('None', prose)
        self.assertNotIn('nan/', prose.lower())


class Contract(unittest.TestCase):
    def test_report_is_json_serialisable_with_the_review_attached(self):
        report, _ = review(BOOK, HISTORIES, benchmark=frame(11, .01))
        json.dumps(report)

    def test_an_empty_book_says_so_instead_of_failing(self):
        report = portfolio.build_report([], SCAN, now=NOW)
        self.assertFalse(report['ic_review']['available'])
        self.assertIn('nothing to review', report['ic_review']['reason'])

    def test_a_single_holding_keeps_everything_except_the_risk_budget(self):
        _, ic = review([holding('AAA', 500000, pe=20)], {'AAA': frame(1)})
        self.assertTrue(ic['available'])
        self.assertFalse(ic['risk_budget']['available'])
        self.assertEqual(ic['valuation']['portfolio_pe'], 20.0)
        self.assertTrue(ic['sections'])

    def test_a_broken_review_never_costs_the_reader_the_measurement(self):
        original = ic_review.build
        ic_review.build = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom'))
        try:
            report = portfolio.build_report(BOOK, SCAN, now=NOW)
        finally:
            ic_review.build = original
        self.assertFalse(report['ic_review']['available'])
        self.assertIn('RuntimeError', report['ic_review']['reason'])
        self.assertTrue(report['holdings'])
        self.assertIsNotNone(report['weighted_score'])

    def test_the_framing_note_travels_with_the_payload(self):
        _, ic = review(BOOK, HISTORIES)
        self.assertIn('Nothing here is an instruction', ic['framing'])
        self.assertTrue(ic['unassessed'])


if __name__ == '__main__':
    unittest.main()
