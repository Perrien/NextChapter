#!/usr/bin/env python3
"""Wait for this run's uploaded Pages artifact to become visible in GitHub."""
import json
import os
import sys
import time
import urllib.error
import urllib.request


def wait_for_artifact(fetch_artifacts, artifact_id, attempts=6, delay=5, pause=time.sleep):
    for attempt in range(1, attempts + 1):
        try:
            artifacts = fetch_artifacts()['artifacts']
            match = next((item for item in artifacts if str(item['id']) == str(artifact_id)), None)
            if match:
                if match['name'] != 'github-pages' or match.get('expired') or match.get('size_in_bytes', 0) <= 0:
                    raise ValueError(f'Uploaded artifact {artifact_id} is not a usable github-pages artifact')
                print(f'Pages artifact {artifact_id} is available ({match["size_in_bytes"]} bytes), check {attempt}/{attempts}.', flush=True)
                return match
            reason = f'uploaded artifact {artifact_id} is not listed yet'
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            # Authentication/configuration errors need intervention, not waiting.
            if isinstance(error, urllib.error.HTTPError):
                error.close()
                if error.code not in (404, 408, 429) and error.code < 500:
                    raise
            reason = f'{type(error).__name__}: {error}'
        if attempt == attempts:
            raise RuntimeError(f'Pages artifact readiness failed after {attempts} checks: {reason}')
        print(f'Waiting for Pages artifact, check {attempt}/{attempts}: {reason}; retrying in {delay}s.', flush=True)
        pause(delay)


def main():
    repository = os.environ['GITHUB_REPOSITORY']
    run_id = os.environ['GITHUB_RUN_ID']
    artifact_id = os.environ['PAGES_ARTIFACT_ID']
    if not run_id.isdigit() or not artifact_id.isdigit():
        raise ValueError('GitHub run ID and uploaded Pages artifact ID must be numeric')
    endpoint = f'{os.environ.get("GITHUB_API_URL", "https://api.github.com")}/repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100'

    def fetch_artifacts():
        request = urllib.request.Request(endpoint, headers={
            'Authorization': f'Bearer {os.environ["GH_TOKEN"]}',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'NextChapter-Pages-readiness',
            'Cache-Control': 'no-cache',
        })
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)

    wait_for_artifact(fetch_artifacts, artifact_id)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f'Pages artifact check failed: {error}', file=sys.stderr)
        raise SystemExit(1)
