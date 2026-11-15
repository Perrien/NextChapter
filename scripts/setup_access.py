#!/usr/bin/env python3
"""Choose shared access locally. Passphrase input is hidden and never saved."""
import getpass
import hashlib
import json
import subprocess
import sys
import warnings
from build import ROOT, read_holdings


def main():
    if not sys.stdin.isatty():
        print('Run npm run setup:access in your own terminal so passphrase entry stays hidden.', file=sys.stderr)
        return 1
    definitions = json.loads((ROOT / 'config/funds.json').read_text())['funds']
    portfolio_path = ROOT.parent / 'Portfolio.csv'
    source_bytes = portfolio_path.read_bytes()
    holdings = read_holdings(portfolio_path, definitions)
    print('Choose the shared passphrase for The Next Chapter. Use at least 6 characters.')
    print('It will not be displayed or saved. Keep it somewhere you can find it.')
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        try:
            passphrase = getpass.getpass('Shared passphrase: ')
            confirmation = getpass.getpass('Confirm passphrase: ')
        except (getpass.GetPassWarning, EOFError, KeyboardInterrupt):
            print('\nHidden entry unavailable or cancelled. No access change made.', file=sys.stderr)
            return 1
    if len(passphrase) < 6 or passphrase != confirmation:
        print('Passphrases must match and contain at least 6 characters. No access change made.', file=sys.stderr)
        return 1
    if portfolio_path.read_bytes() != source_bytes:
        print('The CSV changed during setup. Run setup again to protect the latest holdings.', file=sys.stderr)
        return 1
    result = subprocess.run(['node', str(ROOT / 'scripts/protect.mjs')], input=json.dumps({'positions': holdings, 'passphrase': passphrase}), text=True, cwd=ROOT)
    if result.returncode:
        return result.returncode
    (ROOT / '.local').mkdir(exist_ok=True)
    (ROOT / '.local/protected-holdings.sha256').write_text(hashlib.sha256(source_bytes).hexdigest())
    return subprocess.run([sys.executable, str(ROOT / 'scripts/build.py')], cwd=ROOT).returncode


if __name__ == '__main__':
    raise SystemExit(main())
