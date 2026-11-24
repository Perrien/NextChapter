import contextlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
import urllib.error
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import wait_for_pages_artifact as pages


def artifact(**changes):
    return {'id': 42, 'name': 'github-pages', 'expired': False, 'size_in_bytes': 1234, **changes}


class PagesArtifactTests(unittest.TestCase):
    def test_waits_for_the_exact_uploaded_id_not_an_older_artifact(self):
        fetch = Mock(side_effect=[{'artifacts': [artifact(id=41)]}, {'artifacts': []}, {'artifacts': [artifact()]}])
        pause = Mock()
        with contextlib.redirect_stdout(io.StringIO()):
            result = pages.wait_for_artifact(fetch, '42', pause=pause)
        self.assertEqual(result['id'], 42)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual([call.args for call in pause.call_args_list], [(5,), (5,)])

    def test_transient_api_and_json_errors_are_retried(self):
        errors = [urllib.error.HTTPError('https://api.github.com', 503, 'Unavailable', {}, None),
                  urllib.error.URLError('Temporary connection failure'),
                  json.JSONDecodeError('Incomplete JSON', '', 0)]
        for error in errors:
            fetch = Mock(side_effect=[error, {'artifacts': [artifact()]}])
            pause = Mock()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(pages.wait_for_artifact(fetch, 42, pause=pause)['id'], 42)
            self.assertEqual(fetch.call_count, 2)
            pause.assert_called_once_with(5)

    def test_missing_artifact_stops_after_the_bounded_number_of_checks(self):
        fetch, pause = Mock(return_value={'artifacts': []}), Mock()
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, 'after 3 checks.*42.*not listed'):
            pages.wait_for_artifact(fetch, 42, attempts=3, pause=pause)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(pause.call_count, 2)

    def test_permission_errors_fail_immediately(self):
        error = urllib.error.HTTPError('https://api.github.com', 403, 'Forbidden', {}, None)
        fetch, pause = Mock(side_effect=error), Mock()
        with self.assertRaises(urllib.error.HTTPError):
            pages.wait_for_artifact(fetch, 42, pause=pause)
        fetch.assert_called_once()
        pause.assert_not_called()

    def test_expired_empty_or_wrongly_named_artifacts_are_rejected(self):
        for changes in ({'expired': True}, {'size_in_bytes': 0}, {'name': 'other-build'}):
            fetch, pause = Mock(return_value={'artifacts': [artifact(**changes)]}), Mock()
            with self.assertRaisesRegex(ValueError, 'not a usable github-pages artifact'):
                pages.wait_for_artifact(fetch, 42, pause=pause)
            fetch.assert_called_once()
            pause.assert_not_called()

    def test_runner_request_is_scoped_to_the_run_and_does_not_log_the_token(self):
        response = Mock()
        response.__enter__ = Mock(return_value=io.StringIO(json.dumps({'artifacts': [artifact()]})))
        response.__exit__ = Mock(return_value=False)
        environment = {'GITHUB_REPOSITORY': 'Perrien/NextChapter', 'GITHUB_RUN_ID': '123', 'PAGES_ARTIFACT_ID': '42', 'GH_TOKEN': 'test-only-token', 'GITHUB_API_URL': 'https://api.github.com'}
        output = io.StringIO()
        with patch.dict(os.environ, environment, clear=True), patch.object(pages.urllib.request, 'urlopen', return_value=response) as request, contextlib.redirect_stdout(output):
            self.assertEqual(pages.main(), 0)
        sent = request.call_args.args[0]
        self.assertEqual(sent.full_url, 'https://api.github.com/repos/Perrien/NextChapter/actions/runs/123/artifacts?per_page=100')
        self.assertEqual(sent.get_header('Authorization'), 'Bearer test-only-token')
        self.assertNotIn('test-only-token', output.getvalue())


if __name__ == '__main__':
    unittest.main()
