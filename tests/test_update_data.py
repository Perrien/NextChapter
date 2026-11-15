import contextlib
import datetime as dt
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import update_data
from build import read_holdings


class DataRefreshTests(unittest.TestCase):
    def test_open_session_bar_is_not_accepted_as_a_published_daily_close(self):
        now = dt.datetime(2026, 11, 16, 17, tzinfo=dt.timezone.utc)
        for instrument_type in ('ETF', 'MUTUALFUND'):
            response = {'meta': {'currency': 'USD', 'exchangeTimezoneName': 'America/New_York', 'instrumentType': instrument_type, 'currentTradingPeriod': {'regular': {'end': dt.datetime(2026, 11, 16, 21, tzinfo=dt.timezone.utc).timestamp()}}}, 'timestamp': [dt.datetime(2026, 11, 13, 15, tzinfo=dt.timezone.utc).timestamp(), dt.datetime(2026, 11, 16, 15, tzinfo=dt.timezone.utc).timestamp()], 'indicators': {'quote': [{'close': [100, 110]}], 'adjclose': [{'adjclose': [100, 110]}]}}
            self.assertEqual([r['date'] for r in update_data.daily_series(response, now)], ['2026-11-13'])

    def test_official_close_uses_reported_precision_without_rounding_adjusted_returns(self):
        response = {'meta': {'currency': 'USD', 'exchangeTimezoneName': 'America/New_York', 'instrumentType': 'MUTUALFUND', 'priceHint': 2}, 'timestamp': [1794603600], 'indicators': {'quote': [{'close': [356.2699890136719]}], 'adjclose': [{'adjclose': [354.123456]}]}}
        rows = update_data.daily_series(response, dt.datetime(2026, 11, 15, tzinfo=dt.timezone.utc))
        self.assertEqual(rows[0]['close'], 356.27)
        self.assertEqual(rows[0]['adjusted_close'], 354.123456)

    def test_distribution_rebases_older_adjusted_closes(self):
        old = [{'date': '2026-10-01', 'close': 100, 'adjusted_close': 98}, {'date': '2026-11-01', 'close': 110, 'adjusted_close': 107.8}]
        new = [{'date': '2026-11-01', 'close': 110, 'adjusted_close': 105.6}, {'date': '2026-11-02', 'close': 108, 'adjusted_close': 108}]
        merged = update_data.merge_daily(old, new)
        self.assertAlmostEqual(merged[0]['adjusted_close'], 96)
        self.assertEqual(merged[0]['close'], 100)

    def test_split_rebases_old_closes_and_adjusted_closes(self):
        old = [{'date': '2026-10-01', 'close': 100, 'adjusted_close': 100}, {'date': '2026-11-01', 'close': 120, 'adjusted_close': 120}]
        new = [{'date': '2026-11-01', 'close': 30, 'adjusted_close': 30}, {'date': '2026-11-02', 'close': 31, 'adjusted_close': 31}]
        self.assertEqual(update_data.merge_daily(old, new)[0]['close'], 25)

    def test_nonuniform_revision_requires_full_reload(self):
        old = [{'date': '2026-11-01', 'close': 100, 'adjusted_close': 100}, {'date': '2026-11-02', 'close': 100, 'adjusted_close': 100}]
        new = [{'date': '2026-11-01', 'close': 100, 'adjusted_close': 90}, {'date': '2026-11-02', 'close': 100, 'adjusted_close': 95}]
        with self.assertRaises(ValueError):
            update_data.merge_daily(old, new)

    def test_failed_refresh_keeps_previous_snapshot_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'market.json'
            previous = '{"schema_version":1,"series":{},"marker":"last good"}\n'
            path.write_text(previous)
            with patch.object(sys, 'argv', ['update_data.py', '--output', str(path)]), patch.object(update_data, 'build_snapshot', side_effect=RuntimeError('Provider unavailable')), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(update_data.main(), 1)
            self.assertEqual(path.read_text(), previous)

    def test_partial_csv_is_rejected_instead_of_silently_omitting_a_holding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'holdings.csv'
            path.write_text('Kim,\nTEST,2.5\n')
            self.assertEqual(read_holdings(path, [{'ticker': 'TEST'}])[0]['shares'], 2.5)
            with self.assertRaises(ValueError):
                read_holdings(path, [{'ticker': 'TEST'}, {'ticker': 'MISSING'}])


if __name__ == '__main__':
    unittest.main()
