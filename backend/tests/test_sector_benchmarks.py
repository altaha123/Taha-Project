"""Offline financial-data contract tests; also runnable without pytest."""
import datetime as dt
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sector_benchmarks as B

SNAPSHOT = {"timestamp": "23-Sep-2026 15:30:00", "data": [
    {"index": "NIFTY 50", "last": 102, "previousClose": 100},
    {"index": "NIFTY IT", "last": 105, "previousClose": 100},
    {"index": "NIFTY BANK", "last": 100, "previousClose": 100},
    {"index": "NIFTY METAL", "last": 98, "previousClose": 100},
    {"index": "NIFTY FINANCIAL SERVICES", "last": 103, "previousClose": 100},
]}


def row(result, index):
    return next(r for r in result['rows'] if r['index'] == index)


class BenchmarksTest(unittest.TestCase):
    def setUp(self):
        B._cache.clear()
        B._archives.clear()

    def test_day_is_index_change_not_constituent_average(self):
        r = row(B.build(SNAPSHOT, '1D'), 'NIFTY IT')
        self.assertEqual(r['change_pct'], 5)
        self.assertEqual(r['relative_pp'], 3)
        self.assertNotIn('total', r)
        self.assertNotIn('stocks', r)

    def test_financial_services_is_not_bank_proxy(self):
        result = B.build(SNAPSHOT, '1D')
        self.assertEqual(row(result, 'NIFTY FINANCIAL SERVICES')['change_pct'], 3)
        self.assertEqual(row(result, 'NIFTY BANK')['change_pct'], 0)

    def test_zero_ranks_above_negative_and_missing_is_last(self):
        rows = B.build(SNAPSHOT, '1D')['rows']
        self.assertEqual([r['index'] for r in rows[:5]],
                         ['NIFTY IT', 'NIFTY FINANCIAL SERVICES', 'NIFTY BANK', 'NIFTY METAL', 'NIFTY AUTO'])
        self.assertIsNone(rows[-1]['change_pct'])

    def test_missing_never_becomes_zero(self):
        result = B.build({'data': [], 'timestamp': SNAPSHOT['timestamp']}, '1D')
        self.assertFalse(result['available'])
        self.assertTrue(all(r['change_pct'] is None for r in result['rows']))

    def test_invalid_levels_and_timestamp(self):
        for bad in (None, 0, -1, 'NaN', 'Infinity', '-'):
            snap = {**SNAPSHOT, 'data': [{'index': 'NIFTY IT', 'last': 105, 'previousClose': bad}]}
            self.assertIsNone(row(B.build(snap, '1D'), 'NIFTY IT')['change_pct'])
        self.assertFalse(B.build({**SNAPSHOT, 'timestamp': None}, '1D')['available'])

    def test_history_uses_index_closes_for_both_returns(self):
        baseline = dt.date(2026, 9, 16)
        result = B.build(SNAPSHOT, '1W', baseline, {'NIFTY IT': 100, 'NIFTY 50': 100})
        self.assertEqual(row(result, 'NIFTY IT')['relative_pp'], 3)
        self.assertIsNone(row(result, 'NIFTY BANK')['change_pct'])
        self.assertEqual(result['baseline_date'], '2026-09-16')

    def test_no_day_fallback_for_missing_week_or_month_history(self):
        for window in ('1W', '1M'):
            self.assertFalse(B.build(SNAPSHOT, window)['available'])

    def test_archive_rejects_wrong_date_invalid_closes_and_html(self):
        text = ('Index Name,Index Date,Closing Index Value\n'
                'Nifty IT,16-09-2026,"1,000.25"\n'
                'Nifty Bank,15-09-2026,300\n'
                'Nifty Metal,16-09-2026,NaN\n'
                'Nifty Pharma,16-09-2026,0\n'
                'Nifty Healthcare,16-09-2026,800\n')
        self.assertEqual(B.parse_archive(text, dt.date(2026, 9, 16)),
                         {'NIFTY IT': 1000.25, 'NIFTY HEALTHCARE INDEX': 800})
        self.assertEqual(B.parse_archive('<html>Access denied</html>', dt.date(2026, 9, 16)), {})

    def test_holiday_uses_last_available_prior_close_and_caches_it(self):
        text = b'Index Name,Index Date,Closing Index Value\nNifty IT,18-09-2026,100\n'
        missing = HTTPError('url', 404, 'missing', {}, None)
        with patch.object(B, 'urlopen', side_effect=[missing, missing, io.BytesIO(text)]) as get:
            day, rows = B.archive_on_or_before(dt.date(2026, 9, 20))
            self.assertEqual(day, dt.date(2026, 9, 18))
            self.assertEqual(rows['NIFTY IT'], 100)
            self.assertEqual(get.call_count, 3)
        with patch.object(B, 'urlopen') as get:
            B.archive_on_or_before(dt.date(2026, 9, 18))
            get.assert_not_called()

    def test_transport_failure_does_not_hammer_archive(self):
        with patch.object(B, 'urlopen', side_effect=TimeoutError) as get:
            self.assertEqual(B.archive_on_or_before(dt.date(2026, 9, 20)), (None, {}))
            self.assertEqual(get.call_count, 1)

    def test_exchange_timestamp_preserved_and_snapshot_shared(self):
        with patch.object(B.nse_http, 'get_json', return_value=SNAPSHOT) as get, \
             patch.object(B, 'archive_on_or_before', return_value=(dt.date(2026, 9, 16), {'NIFTY IT': 100})) as archive:
            first = B.overview('1D')
            B.overview('1D')
            B.overview('1W')
            get.assert_called_once()
            archive.assert_called_once_with(dt.date(2026, 9, 16))
            self.assertEqual(first['as_of'], SNAPSHOT['timestamp'])

    def test_30d_target_is_based_on_exchange_date_not_server_clock(self):
        with patch.object(B.nse_http, 'get_json', return_value=SNAPSHOT), \
             patch.object(B, 'archive_on_or_before', return_value=(None, {})) as archive:
            B.overview('1M')
            archive.assert_called_once_with(dt.date(2026, 8, 24))

    def test_failed_refresh_marks_cached_snapshot_stale(self):
        good = B.build(SNAPSHOT, '1D')
        B._cache['1D'] = (-999999, good)
        with patch.object(B.nse_http, 'get_json', return_value=None):
            result = B.overview('1D')
        self.assertTrue(result['stale'])
        self.assertEqual(result['as_of'], SNAPSHOT['timestamp'])
        self.assertEqual(row(result, 'NIFTY IT')['change_pct'], 5)

    def test_cold_exchange_failure_is_cached_unavailable(self):
        with patch.object(B.nse_http, 'get_json', return_value=None) as get:
            self.assertFalse(B.overview()['available'])
            B.overview()
            get.assert_called_once()


if __name__ == '__main__':
    unittest.main()
