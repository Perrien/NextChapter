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

    def test_off_hours_only_skip_when_the_previous_weekday_slot_is_complete(self):
        for date in ('2026-11-16T17:14:00+00:00', '2026-11-15T18:00:00+00:00'):
            self.assertFalse(refresh_due('schedule', '2026-11-14T03:20:00Z', now(date))[0])
            self.assertTrue(refresh_due('schedule', '2026-11-13T20:20:00Z', now(date))[0])

    def test_a_timer_after_midnight_catches_up_the_missed_previous_evening(self):
        # Regression: the real 05:58 Central timer was incorrectly skipped.
        attempt = now('2026-11-17T11:58:00+00:00')
        self.assertTrue(refresh_due('schedule', '2026-11-17T02:58:02Z', attempt)[0])
        self.assertFalse(refresh_due('schedule', '2026-11-17T03:20:00Z', attempt)[0])
        saturday = now('2026-11-21T06:05:00+00:00')
        self.assertTrue(refresh_due('schedule', '2026-11-21T02:58:00Z', saturday)[0])
        self.assertFalse(refresh_due('schedule', '2026-11-21T03:20:00Z', saturday)[0])

    def test_extra_utc_offset_checks_skip_already_published_slots(self):
        # The unused CST/CDT hour must not cause a second provider download.
        self.assertFalse(refresh_due('schedule', '2026-11-17T03:20:00Z', now('2026-11-17T16:15:00+00:00'))[0])
        self.assertFalse(refresh_due('schedule', '2026-07-07T16:20:00Z', now('2026-07-07T17:15:00+00:00'))[0])

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
