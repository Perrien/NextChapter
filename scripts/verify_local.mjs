import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { preparePortfolio, comparePeriod, summarize, durationMonths, milestone } from '../src/portfolio.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = name => JSON.parse(fs.readFileSync(path.join(root, name), 'utf8'));
const market = read('data/market.json');
const funds = read('config/funds.json').funds;
const positions = JSON.parse(execFileSync('python3', ['-c', "import json; from build import ROOT, read_holdings; print(json.dumps(read_holdings(ROOT.parent / 'Portfolio.csv', json.loads((ROOT / 'config/funds.json').read_text())['funds'])))"], { cwd: path.join(root, 'scripts'), encoding: 'utf8' }));
const portfolio = preparePortfolio(market, positions, funds);
const periods = {};
for (const period of ['today', 'week', 'month', 'year']) {
  const view = comparePeriod(portfolio, period);
  const owners = ['Kim', 'Ashley'].map(owner => summarize(view.rows.filter(row => row.owner === owner)));
  const sectors = ['domestic', 'international', 'bonds'].map(group => summarize(view.rows.filter(row => row.group === group)));
  for (const parts of [owners, sectors]) {
    assert.ok(Math.abs(parts.reduce((sum, row) => sum + row.value, 0) - view.value) < 0.02, 'Valuation reconciliation');
    assert.ok(Math.abs(parts.reduce((sum, row) => sum + row.delta, 0) - view.delta) < 0.02, 'Growth reconciliation');
  }
  assert.ok(Math.abs(view.history.at(-1).value - view.value) < 0.01, 'History ends at current value');
  assert.ok(Math.abs(view.history[0].value - view.baseline) < 0.01, 'History begins at comparison value');
  assert.ok(view.rows.every(row => Number.isFinite(row.value) && row.value > 0));
  periods[period] = { baseline_date: view.baselineDate, end_date: view.endDate, change: view.delta, return: view.rate, observations: view.history.length, owner_values: owners.map((row, i) => ({ owner: ['Kim', 'Ashley'][i], value: row.value })) };
}
// Display totals are rounded to cents; the projection rate retains full precision.
const yearView = comparePeriod(portfolio, 'year');
assert.ok(Math.abs(yearView.value - yearView.baseline * (1 + portfolio.annualRate)) < 0.01, 'Annual projection baseline agrees with completed-year view to a cent');
const report = { checked_at: new Date().toISOString(), source_fetched_at: market.fetched_at, source_close_date: portfolio.commonDate, holdings: positions.length, total: portfolio.total, annual_return: portfolio.annualRate, annual_start: portfolio.annualDate, estimated_holdings: portfolio.rows.filter(row => row.estimated).length, outlook_at_10000_monthly: durationMonths(portfolio.total, 10000, portfolio.annualRate), milestone: milestone(portfolio.total, portfolio.annualRate), periods };
fs.mkdirSync(path.join(root, '.local'), { recursive: true });
fs.writeFileSync(path.join(root, '.local/verification.json'), JSON.stringify(report, null, 2) + '\n');
console.log(`All ${positions.length} holdings reconcile across owners, sectors, four comparison periods, and history.`);
console.log(`Latest published value: ${portfolio.total.toFixed(2)} USD; closes through ${portfolio.commonDate}.`);
console.log('Detailed report saved locally in ignored .local/verification.json.');
