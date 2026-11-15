#!/usr/bin/env python3
"""Package the static site from a locally encrypted personal page."""
import argparse
import csv
import json
import hashlib
import datetime as dt
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def read_holdings(path, definitions):
    known = {fund["ticker"] for fund in definitions}
    result, seen, owner = [], set(), None
    with path.open(newline="") as stream:
        for row in csv.reader(stream):
            if not row or not row[0].strip():
                continue
            if len(row) < 2 or not row[1].strip():
                owner = row[0].strip()
                if owner not in ("Kim", "Ashley"):
                    raise ValueError("Unexpected owner in CSV")
                continue
            ticker = row[0].strip().upper()
            quantity = float(row[1])
            if owner is None or ticker not in known or not 0 < quantity < float("inf") or (owner, ticker) in seen:
                raise ValueError(f"Invalid or duplicate holding: {ticker}")
            seen.add((owner, ticker))
            result.append({"owner": owner, "ticker": ticker, "shares": quantity})
    if {row["ticker"] for row in result} != known:
        raise ValueError("CSV and verified fund list differ; update classifications before building")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup-preview", action="store_true", help="Show a setup reminder when access has not been configured")
    args = parser.parse_args()
    market = json.loads((ROOT / "data/market.json").read_text())
    protected = ROOT / 'protected/index.html'
    if protected.exists():
        manifest = json.loads((ROOT / 'protected/manifest.json').read_text())
        expected = hashlib.sha256((ROOT / 'src/index.html').read_bytes() + (ROOT / 'src/login.html').read_bytes()).hexdigest()
        if manifest.get('template_hash') != expected:
            raise ValueError('Page templates changed. Run npm run setup:access to protect the updated page.')
        index = protected.read_text()
        if '"staticryptEncryptedMsgUniqueVariableName":' not in index or 'id="private-holdings"' in index:
            raise ValueError('The protected page is missing or contains plaintext holdings')
        fingerprint = ROOT / '.local/protected-holdings.sha256'
        portfolio = ROOT.parent / 'Portfolio.csv'
        if fingerprint.exists() and portfolio.exists() and fingerprint.read_text().strip() != hashlib.sha256(portfolio.read_bytes()).hexdigest():
            raise ValueError('Holdings changed. Run npm run setup:access to re-encrypt the updated CSV.')
    elif args.setup_preview:
        index = subprocess.check_output(['node', '--input-type=module', '-e', "import {loginPage} from './scripts/protect.mjs'; process.stdout.write(loginPage());"], cwd=ROOT, text=True)
    else:
        raise ValueError('Shared access is not configured. Run npm run setup:access in your terminal.')
    local = ROOT / '.local'
    local.mkdir(exist_ok=True)
    output = ROOT / "dist"
    # Build an allowlisted new tree; an old plaintext holdings file must not survive.
    with tempfile.TemporaryDirectory(prefix='build-', dir=local) as scratch:
        stage = Path(scratch) / 'site'
        stage.mkdir()
        (stage / 'index.html').write_text(index)
        for name in ("styles.css", "app.mjs", "portfolio.mjs", "icons.mjs"):
            shutil.copyfile(ROOT / "src" / name, stage / name)
        data = stage / 'data'
        data.mkdir()
        shutil.copyfile(ROOT / 'data/market.json', data / 'market.json')
        shutil.copyfile(ROOT / 'config/funds.json', data / 'funds.json')
        run_id = os.environ.get('GITHUB_RUN_ID')
        repository = os.environ.get('GITHUB_REPOSITORY', 'Perrien/NextChapter')
        publication = {'schema_version': 1, 'built_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'source_fetched_at': market.get('fetched_at'), 'market_sha256': hashlib.sha256((data / 'market.json').read_bytes()).hexdigest(), 'workflow_url': 'https://github.com/Perrien/NextChapter/actions/workflows/publish.yml', 'run_url': f'https://github.com/{repository}/actions/runs/{run_id}' if run_id else None}
        (data / 'publication.json').write_text(json.dumps(publication, separators=(',', ':')) + '\n')
        (stage / '.nojekyll').touch()
        if output.exists():
            output.rename(Path(scratch) / 'previous-site')
        stage.rename(output)
    print(f"Built static site with saved prices through {market['common_close_date']} in {output}")
    print('Encrypted shared access is ready.' if protected.exists() else 'Setup preview only. Choose a passphrase with npm run setup:access.')
    print('Static output is ready for the configured GitHub Pages workflow.')


if __name__ == "__main__":
    main()
