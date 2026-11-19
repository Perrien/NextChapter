import contextlib
import copy
import datetime as dt
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import update_data
from build import read_holdings


class DataRefreshTests(unittest.TestCase):
    def fund_response(self, close=None, adjusted=None):
        stamps = [dt.datetime(2026, 11, day, 14, 30, tzinfo=dt.timezone.utc).timestamp() for day in (17, 18)]
        return {'meta': {'symbol': 'FSMDX', 'currency': 'USD', 'exchangeTimezoneName': 'America/New_York', 'instrumentType': 'MUTUALFUND', 'priceHint': 2}, 'timestamp': stamps, 'indicators': {'quote': [{'close': [41.56, close]}], 'adjclose': [{'adjclose': [41.56, adjusted]}]}}

    def test_pending_current_day_close_is_omitted_with_a_warning(self):
        now = dt.datetime(2026, 11, 18, 23, tzinfo=dt.timezone.utc)
        for instrument_type in ['MUTUALFUND', 'ETF', 'EQUITY']:
            for close, adjusted in [(None, None), (42.0, None), (None, 42.0)]:
                warnings = []
                response = self.fund_response(close, adjusted)
                response['meta']['instrumentType'] = instrument_type
                with contextlib.redirect_stdout(io.StringIO()):
                    rows = update_data.daily_series(response, now, warnings)
                self.assertEqual([row['date'] for row in rows], ['2026-11-17'])
                self.assertIn('2026-11-18', warnings[0])
                self.assertIn('Last published closes', warnings[0])

    def test_only_explicit_missing_current_day_prices_can_be_deferred(self):
        now = dt.datetime(2026, 11, 18, 23, tzinfo=dt.timezone.utc)
        bad_responses = []
        old_gap = self.fund_response(42, 42)
        old_gap['indicators']['quote'][0]['close'][0] = None
        bad_responses.append(old_gap)
        for close in [0, -1, float('nan'), float('inf')]:
            bad_responses.append(self.fund_response(close, None))
            bad_responses.append(self.fund_response(None, close))
        truncated = self.fund_response()
        truncated['indicators']['adjclose'][0]['adjclose'].pop()
        bad_responses.append(truncated)
        for response in bad_responses:
            with self.assertRaisesRegex(ValueError, r'Invalid close/adjusted close.*close=.*adjusted_close='):
                update_data.daily_series(response, now)
        with self.assertRaisesRegex(ValueError, '2026-11-18'):
            update_data.daily_series(self.fund_response(), now + dt.timedelta(days=1))

    def test_bad_price_retries_and_final_error_identifies_the_request_and_values(self):
        now = dt.datetime(2026, 11, 19, 23, tzinfo=dt.timezone.utc)
        with patch.object(update_data.time, 'sleep') as sleep, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(ValueError, r'FSMDX \[range=1mo, interval=1d, attempt=3/3\].*2026-11-18: close=None, adjusted_close=None'):
                calls = []
                def fetcher(*args):
                    calls.append(args)
                    return self.fund_response()
                update_data.fetch_validated('FSMDX', '1mo', '1d', lambda r: update_data.daily_series(r, now), fetcher)
            self.assertEqual(len(calls), 3)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

    def test_transient_network_failure_recovers_on_retry(self):
        good = self.fund_response(42, 42)
        with patch.object(update_data.time, 'sleep'), contextlib.redirect_stderr(io.StringIO()):
            from unittest.mock import Mock
            fetcher = Mock(side_effect=[urllib.error.URLError('temporary failure'), good])
            result, parsed = update_data.fetch_validated('FSMDX', '1mo', '1d', lambda r: r['meta']['symbol'], fetcher)
        self.assertIs(result, good)
        self.assertEqual(parsed, 'FSMDX')
        self.assertEqual(fetcher.call_count, 2)

    def test_complete_snapshot_can_use_last_fund_nav_and_new_proxy_quotes(self):
        now = dt.datetime(2026, 11, 18, 23, tzinfo=dt.timezone.utc)
        funds = [{'ticker': 'FSMDX', 'proxy': 'IWR', 'type': 'MUTUALFUND'}]
        def fetcher(symbol, period, interval):
            result = self.fund_response()
            result['meta'].update(symbol=symbol, instrumentType='ETF' if symbol == 'IWR' else 'MUTUALFUND', dataGranularity=interval)
            if interval == '5m':
                result['timestamp'] = [dt.datetime(2026, 11, 18, 20, tzinfo=dt.timezone.utc).timestamp()]
                result['indicators'] = {'quote': [{'close': [120]}]}
            else:
                days = [dt.date(2025, 1, 1) + dt.timedelta(days=i) for i in range((now.date() - dt.date(2025, 1, 1)).days + 1)]
                days = [day for day in days if day.weekday() < 5]
                result['timestamp'] = [dt.datetime.combine(day, dt.time(14, 30), dt.timezone.utc).timestamp() for day in days]
                closes = [100.0] * len(days)
                if symbol == 'FSMDX':
                    closes[-1] = None
                result['indicators'] = {'quote': [{'close': closes}], 'adjclose': [{'adjclose': closes.copy()}]}
            return result
        with contextlib.redirect_stdout(io.StringIO()):
            snapshot = update_data.build_snapshot(funds, {}, fetcher, now, delay=0)
        self.assertEqual(snapshot['common_close_date'], '2026-11-17')
        self.assertEqual(snapshot['series']['IWR']['daily'][-1]['date'], '2026-11-18')
        self.assertEqual(snapshot['series']['IWR']['intraday'][-1]['date'], '2026-11-18')
        self.assertTrue(snapshot['warnings'][0].startswith('FSMDX:'))
        # A null placeholder must never erase a close that was already saved.
        previous = copy.deepcopy(snapshot)
        previous['series']['FSMDX']['daily'].append({'date': '2026-11-18', 'close': 100, 'adjusted_close': 100})
        with patch.object(update_data.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(ValueError, r'FSMDX.*regressed.*2026-11-17.*2026-11-18'):
                update_data.build_snapshot(funds, previous, fetcher, now, delay=0)

    def test_actions_summary_and_annotations_include_actionable_failure_details(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'summary.md'
            error = ValueError('FSMDX [range=1mo, interval=1d, attempt=3/3]: 2026-11-18 close=None adjusted_close=None\n::fake::100%')
            output = io.StringIO()
            with patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': str(path), 'GITHUB_ACTIONS': 'true'}), contextlib.redirect_stdout(output):
                update_data.report_refresh(None, {'common_close_date': '2026-11-17', 'fetched_at': 'prior fetch'}, error)
            summary = path.read_text()
            for text in ['FSMDX', '2026-11-18', 'close=None', 'adjusted_close=None', 'previous snapshot retained', 'prior fetch']:
                self.assertIn(text, summary)
            self.assertIn('%0A::fake::100%25', output.getvalue())
            self.assertEqual(len(output.getvalue().splitlines()), 1)

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
            with patch.object(sys, 'argv', ['update_data.py', '--output', str(path)]), patch.object(update_data, 'build_snapshot', side_effect=RuntimeError('Provider unavailable')), patch.object(update_data, 'report_refresh'), contextlib.redirect_stderr(io.StringIO()):
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
