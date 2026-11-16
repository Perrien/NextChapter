import datetime as dt
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from refresh_due import refresh_due


def now(value):
    return dt.datetime.fromisoformat(value)


class ScheduledRefreshTests(unittest.TestCase):
    def test_manual_and_source_events_always_proceed(self):
        for event in ('workflow_dispatch', 'push'):
            self.assertTrue(refresh_due(event, '2026-11-16T18:00:00Z', now('2026-11-16T18:01:00+00:00'))[0])

    def test_no_refresh_before_first_slot_or_on_weekends(self):
        for date in ('2026-11-16T17:14:00+00:00', '2026-11-15T18:00:00+00:00'):
            self.assertFalse(refresh_due('schedule', None, now(date))[0])

    def test_catchup_runs_after_a_missed_slot_and_skips_a_successful_one(self):
        attempt = now('2026-11-16T17:45:00+00:00')  # 11:45 Central
        self.assertTrue(refresh_due('schedule', '2026-11-15T22:00:00Z', attempt)[0])
        self.assertFalse(refresh_due('schedule', '2026-11-16T17:16:00Z', attempt)[0])
        self.assertFalse(refresh_due('schedule', '2026-11-16T17:15:00Z', attempt)[0])

    def test_later_slots_and_daylight_saving_use_central_time(self):
        self.assertTrue(refresh_due('schedule', '2026-11-16T18:00:00Z', now('2026-11-16T20:15:00+00:00'))[0])
        self.assertFalse(refresh_due('schedule', '2026-11-16T20:20:00Z', now('2026-11-16T20:45:00+00:00'))[0])
        self.assertTrue(refresh_due('schedule', '2026-11-16T20:20:00Z', now('2026-11-17T03:45:00+00:00'))[0])
        self.assertTrue(refresh_due('schedule', '2026-07-06T15:00:00Z', now('2026-07-06T16:15:00+00:00'))[0])
        self.assertFalse(refresh_due('schedule', '2026-07-06T16:16:00Z', now('2026-07-06T16:45:00+00:00'))[0])

    def test_bad_or_future_timestamps_do_not_suppress_an_update(self):
        attempt = now('2026-11-16T17:45:00+00:00')
        for stamp in (None, '', 'not-a-time', '2026-11-16T17:15:00', '2026-11-17T17:15:00Z'):
            self.assertTrue(refresh_due('schedule', stamp, attempt)[0])


if __name__ == '__main__':
    unittest.main()
