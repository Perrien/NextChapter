import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build
import setup_access


class AccessBuildTests(unittest.TestCase):
    def prepare(self, root):
        for directory in ('src', 'config', 'data', 'protected', 'dist/data'):
            (root / directory).mkdir(parents=True)
        for filename in ('index.html', 'login.html', 'styles.css', 'app.mjs', 'portfolio.mjs', 'icons.mjs'):
            (root / 'src' / filename).write_text('generic source')
        digest = hashlib.sha256(b'generic sourcegeneric source').hexdigest()
        (root / 'protected/manifest.json').write_text(json.dumps({'template_hash': digest}))
        (root / 'protected/index.html').write_text('const config = {"staticryptEncryptedMsgUniqueVariableName":"ciphertext"};')
        (root / 'data/market.json').write_text('{"common_close_date":"2026-11-13"}')
        (root / 'config/funds.json').write_text('{"funds":[]}')
        (root / 'dist/data/holdings.json').write_text('{"shares":1234567}')

    def test_build_removes_legacy_plaintext_and_needs_no_csv_or_passphrase(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prepare(root)
            with patch.object(build, 'ROOT', root), patch.object(sys, 'argv', ['build.py']), contextlib.redirect_stdout(io.StringIO()):
                build.main()
            self.assertFalse((root / 'dist/data/holdings.json').exists())
            actual = {str(p.relative_to(root / 'dist')) for p in (root / 'dist').rglob('*') if p.is_file()}
            self.assertEqual(actual, {'index.html', 'styles.css', 'app.mjs', 'portfolio.mjs', 'icons.mjs', 'data/market.json', 'data/funds.json', 'data/publication.json', '.nojekyll'})
            self.assertTrue(all('1234567' not in p.read_text() for p in (root / 'dist').rglob('*') if p.is_file()))

    def test_changed_template_and_plaintext_protected_page_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prepare(root)
            with patch.object(build, 'ROOT', root), patch.object(sys, 'argv', ['build.py']):
                (root / 'src/index.html').write_text('changed')
                with self.assertRaisesRegex(ValueError, 'templates changed'):
                    build.main()
                (root / 'src/index.html').write_text('generic source')
                (root / 'protected/index.html').write_text('"staticryptEncryptedMsgUniqueVariableName": "fake" <script id="private-holdings">plaintext</script>')
                with self.assertRaisesRegex(ValueError, 'plaintext holdings'):
                    build.main()

    def test_missing_protected_page_cannot_be_built_accidentally(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prepare(root)
            (root / 'protected/index.html').unlink()
            with patch.object(build, 'ROOT', root), patch.object(sys, 'argv', ['build.py']):
                with self.assertRaisesRegex(ValueError, 'not configured'):
                    build.main()

    def test_local_csv_change_requires_reencryption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'next-chapter'
            self.prepare(root)
            (root / '.local').mkdir()
            csv_path = root.parent / 'Portfolio.csv'
            csv_path.write_text('original holdings')
            (root / '.local/protected-holdings.sha256').write_text(hashlib.sha256(csv_path.read_bytes()).hexdigest())
            csv_path.write_text('updated holdings')
            with patch.object(build, 'ROOT', root), patch.object(sys, 'argv', ['build.py']):
                with self.assertRaisesRegex(ValueError, 'Holdings changed'):
                    build.main()

    def test_secret_setup_requires_an_interactive_terminal(self):
        with patch.object(sys.stdin, 'isatty', return_value=False), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(setup_access.main(), 1)


if __name__ == '__main__':
    unittest.main()
