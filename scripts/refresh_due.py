#!/usr/bin/env python3
"""Decide whether a scheduled attempt still needs to refresh its Central-time slot."""
import datetime as dt
import json
import os
import urllib.request
import urllib.error
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo('America/Chicago')
SLOTS = ((11, 15), (14, 15), (21, 15))
PUBLICATION_URL = 'https://perrien.github.io/NextChapter/data/publication.json'


def refresh_due(event, fetched_at, now=None):
    if event != 'schedule':
        return True, 'Manual requests and source pushes always proceed.'
    now = now or dt.datetime.now(dt.timezone.utc)
    local = now.astimezone(CENTRAL)
    if local.weekday() >= 5:
        return False, 'No scheduled refresh is due on the weekend.'
    due = [local.replace(hour=hour, minute=minute, second=0, microsecond=0) for hour, minute in SLOTS]
    due = [slot for slot in due if slot <= local]
    if not due:
        return False, 'The first refresh slot has not arrived yet.'
    slot = max(due)
    try:
        fetched = dt.datetime.fromisoformat(fetched_at.replace('Z', '+00:00'))
        if fetched.tzinfo is None or fetched > now + dt.timedelta(minutes=5):
            raise ValueError('Invalid snapshot timestamp')
    except (AttributeError, TypeError, ValueError):
        return True, 'The published snapshot timestamp is missing or invalid; attempt a refresh.'
    if fetched >= slot:
        return False, f'The {slot:%H:%M} Central slot already has a successfully published snapshot.'
    return True, f'The {slot:%H:%M} Central slot needs a fresh snapshot.'


def main():
    event = os.environ.get('GITHUB_EVENT_NAME', 'workflow_dispatch')
    fetched = None
    if event == 'schedule':
        try:
            # A data commit alone is not proof of publication: a deployment can
            # fail afterward. Only skip after checking the live site's metadata.
            url = PUBLICATION_URL + '?check=' + str(int(dt.datetime.now(dt.timezone.utc).timestamp()))
            request = urllib.request.Request(url, headers={'Cache-Control': 'no-cache', 'User-Agent': 'NextChapter-refresh-check'})
            with urllib.request.urlopen(request, timeout=15) as response:
                fetched = json.load(response).get('source_fetched_at')
        except (OSError, ValueError, urllib.error.URLError):
            print('Could not verify the published snapshot; allow a refresh if a slot is due.')
    should_run, reason = refresh_due(event, fetched)
    print(reason)
    output = os.environ.get('GITHUB_OUTPUT')
    if output:
        with open(output, 'a') as stream:
            stream.write(f'should_run={str(should_run).lower()}\n')


if __name__ == '__main__':
    main()
