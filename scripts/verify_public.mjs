// Runner-safe validation: no private CSV, holdings, passphrase, or unlock key.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { preparePortfolio, comparePeriod } from '../src/portfolio.mjs';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const artifact = process.argv.includes('--artifact');
const base = artifact ? path.join(root, 'dist') : root;
const json = name => JSON.parse(fs.readFileSync(path.join(base, name), 'utf8'));
const market = json('data/market.json');
const funds = json(artifact ? 'data/funds.json' : 'config/funds.json').funds;
// One synthetic share of every verified security tests common history, never real totals.
const positions = funds.map(fund => ({ ticker: fund.ticker, owner: 'Kim', shares: 1 }));
const basket = preparePortfolio(market, positions, funds);
for (const period of ['today', 'week', 'month', 'year']) {
  const view = comparePeriod(basket, period);
  assert.ok(Number.isFinite(view.value) && Number.isFinite(view.rate));
  assert.ok(view.history.length > 0);
}
const protectedPath = artifact ? 'index.html' : 'protected/index.html';
const page = fs.readFileSync(path.join(base, protectedPath), 'utf8');
assert.ok(page.includes('"staticryptEncryptedMsgUniqueVariableName":'), 'Encrypted personal page is required');
assert.ok(!page.includes('id="private-holdings"'), 'Personal HTML must remain encrypted');
assert.ok(!page.includes('"shares":'), 'Plaintext shares must not be served');
if (!artifact) {
  const manifest = json('protected/manifest.json');
  const hash = createHash('sha256').update(fs.readFileSync(path.join(root, 'src/index.html'))).update(fs.readFileSync(path.join(root, 'src/login.html'))).digest('hex');
  assert.equal(manifest.template_hash, hash, 'Protect changed HTML templates locally before publishing');
} else {
  function files(directory, prefix = '') {
    return fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
      const name = prefix + entry.name;
      assert.ok(!entry.isSymbolicLink(), 'Publication must not contain symlinks');
      return entry.isDirectory() ? files(path.join(directory, entry.name), name + '/') : [name];
    });
  }
  assert.deepEqual(files(base).sort(), ['.nojekyll', 'app.mjs', 'data/funds.json', 'data/market.json', 'data/publication.json', 'icons.mjs', 'index.html', 'portfolio.mjs', 'styles.css'].sort(), 'Only allowlisted static assets can be published');
  const publication = json('data/publication.json');
  assert.equal(publication.market_sha256, createHash('sha256').update(fs.readFileSync(path.join(base, 'data/market.json'))).digest('hex'));
  for (const name of files(base)) assert.ok(!fs.readFileSync(path.join(base, name), 'utf8').includes('"shares":'), `${name} contains plaintext shares`);
}
console.log(`Public ${artifact ? 'artifact' : 'snapshot'} validated: all ${funds.length} securities, four comparison periods, encrypted personal page${artifact ? ', allowlisted files' : ''}.`);
