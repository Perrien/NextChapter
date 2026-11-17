import test from 'node:test';
import assert from 'node:assert/strict';
import { preparePortfolio, comparePeriod, summarize, durationMonths, outlookAgeSubtitle, healthcareMonthsRemaining, milestone, yearBefore, baselineTarget } from '../src/portfolio.mjs';

const definition = { ticker: 'FUND', name: 'Test fund', group: 'domestic', type: 'MUTUALFUND', proxy: 'ETF', proxy_match: 'close' };
const bars = (first = 9, end = 10) => [
  { date: '2025-11-13', close: first, adjusted_close: first },
  { date: '2026-11-06', close: 9.5, adjusted_close: 9.5 },
  { date: '2026-11-12', close: 9.8, adjusted_close: 9.8 },
  { date: '2026-11-13', close: end, adjusted_close: end }
];
function fixture({ quote = null, fundBars = bars(), proxyBars = bars(90, 100), events = {} } = {}) {
  return { schema_version: 1, fetched_at: '2026-11-15T18:00:00Z', warnings: [], series: {
    FUND: { currency: 'USD', type: 'MUTUALFUND', timezone: 'America/New_York', daily: fundBars, intraday: [], events: {} },
    ETF: { currency: 'USD', type: 'ETF', timezone: 'America/New_York', daily: proxyBars, intraday: quote ? [{ timestamp: Date.parse(quote.when) / 1000, date: quote.date, close: quote.price }] : [], events }
  } };
}
const positions = [{ ticker: 'FUND', owner: 'Kim', shares: 100 }];
const sunday = Date.parse('2026-11-15T18:00:00Z');
const monday = Date.parse('2026-11-16T18:00:00Z');

test('published fund NAV is not moved again by its same-day ETF return', () => {
  const data = fixture({ quote: { when: '2026-11-13T21:00:00Z', date: '2026-11-13', price: 110 } });
  const p = preparePortfolio(data, positions, [definition], sunday);
  assert.equal(p.total, 1000);
  assert.equal(p.rows[0].estimated, false);
  assert.equal(comparePeriod(p, 'today').baselineDate, '2026-11-12');
});
test('a new trading-day proxy estimates a mutual fund and does not redefine the past-year baseline', () => {
  const data = fixture({ quote: { when: '2026-11-16T16:00:00Z', date: '2026-11-16', price: 110 } });
  const p = preparePortfolio(data, positions, [definition], monday);
  assert.ok(Math.abs(p.total - 1100) < 1e-8);
  assert.equal(p.rows[0].estimated, true);
  assert.equal(p.rows[0].priceDate, '2026-11-16');
  assert.ok(Math.abs(comparePeriod(p, 'today').delta - 100) < 1e-8);
  assert.ok(Math.abs(p.annualRate - (10 / 9 - 1)) < 1e-8);
  assert.equal(comparePeriod(p, 'today').history.at(-1).estimated, true);
});
test('rounding a published holding value to cents does not create an estimated history point', () => {
  const data = fixture();
  data.series.FUND.daily.at(-1).close = 10.005;
  const p = preparePortfolio(data, [{ ticker: 'FUND', owner: 'Kim', shares: 1 }], [definition], sunday);
  const view = comparePeriod(p, 'month');
  assert.equal(view.value, 10.01);
  assert.equal(view.history.at(-1).value, view.value);
  assert.equal(view.history.at(-1).estimated, false);
  assert.equal(view.history.filter(point => point.date === p.asOf).length, 1);
});
test('a missing matching proxy anchor falls back to the official fund price', () => {
  const data = fixture({ quote: { when: '2026-11-16T16:00:00Z', date: '2026-11-16', price: 110 }, proxyBars: bars(90, 100).slice(0, -1) });
  const p = preparePortfolio(data, positions, [definition], monday);
  assert.equal(p.total, 1000);
  assert.equal(p.rows[0].estimated, false);
  assert.ok(p.warnings.some(x => x.includes('no aligned')));
});
test('a payout price drop with unchanged total return does not appear as an investment loss', () => {
  const data = fixture({ fundBars: [
    { date: '2025-11-13', close: 100, adjusted_close: 90 },
    { date: '2026-11-12', close: 100, adjusted_close: 90 },
    { date: '2026-11-13', close: 90, adjusted_close: 90 }
  ] });
  const p = preparePortfolio(data, [{ ticker: 'FUND', owner: 'Kim', shares: 1 }], [definition], sunday);
  const view = comparePeriod(p, 'today');
  assert.equal(p.total, 90); // Actual current value, not an adjusted-close valuation.
  assert.equal(view.delta, 0);
  assert.equal(view.history[0].value, 90); // Growth-normalized, explicitly not historical cash balance.
});
test('direct ETF intraday payout handling preserves total return while showing its actual market price', () => {
  const direct = { ...definition, ticker: 'ETF', type: 'ETF', proxy_match: 'direct' };
  const data = fixture({ proxyBars: [
    { date: '2025-11-13', close: 100, adjusted_close: 100 },
    { date: '2026-11-13', close: 100, adjusted_close: 100 }
  ], quote: { when: '2026-11-16T16:00:00Z', date: '2026-11-16', price: 90 }, events: { dividends: { example: { date: '2026-11-16', amount: 10 } } } });
  const p = preparePortfolio(data, [{ ticker: 'ETF', owner: 'Ashley', shares: 1 }], [direct], monday);
  assert.equal(p.total, 90);
  assert.equal(p.rows[0].estimated, false);
  assert.equal(comparePeriod(p, 'today').delta, 0);
});
test('owner subsets and sector summaries reconcile without double-counting', () => {
  const p = preparePortfolio(fixture(), [...positions, { ticker: 'FUND', owner: 'Ashley', shares: 25 }], [definition], sunday);
  const v = comparePeriod(p, 'year');
  const kim = summarize(v.rows.filter(x => x.owner === 'Kim'));
  const ashley = summarize(v.rows.filter(x => x.owner === 'Ashley'));
  assert.equal(kim.value + ashley.value, v.value);
  assert.ok(Math.abs(kim.delta + ashley.delta - v.delta) < 1e-8);
  assert.ok(Math.abs(v.rate - p.annualRate) < 1e-8);
});
test('calendar week/month boundaries and leap anniversaries use the appropriate prior date', () => {
  const p = { asOf: '2026-11-13', calendarDate: '2026-11-15' };
  assert.equal(baselineTarget(p, 'week'), '2026-11-08');
  assert.equal(baselineTarget(p, 'month'), '2026-10-31');
  assert.equal(yearBefore('2024-02-29'), '2023-02-28');
  assert.equal(baselineTarget({ ...p, calendarDate: '2026-11-16' }, 'week'), '2026-11-15');
});
test('invalid or incomplete prices never produce a partial household total', () => {
  const data = fixture();
  data.series.FUND.daily.at(-1).close = null;
  assert.throws(() => preparePortfolio(data, positions, [definition], sunday), /invalid daily/);
  assert.throws(() => preparePortfolio(fixture(), [{ ...positions[0], shares: -10 }], [definition], sunday), /Invalid holding/);
});
test('spending model uses beginning-of-month withdrawals and matches the annuity formula', () => {
  assert.deepEqual(durationMonths(120000, 10000, 0, 0), { months: 12, capped: false });
  assert.equal(durationMonths(9999, 10000, 0).months, 0);
  assert.equal(durationMonths(100000, 0, 0.05), null);
  const balance = 1744322.32, rate = 0.058, spending = 10000;
  const monthly = Math.expm1(Math.log1p(rate) / 12);
  const analytic = -Math.log1p(-balance * monthly / (spending * (1 + monthly))) / Math.log1p(monthly);
  assert.equal(durationMonths(balance, spending, rate, 0).months, Math.floor(analytic));
  assert.equal(durationMonths(2000000, 5000, 0.06).capped, true);
  assert.ok(durationMonths(100000, 1000, -0.1).months < 100);
});
test('inflating spending matches a growing annuity and shortens the fixed-spending result', () => {
  const balance = 1500000, spending = 10000, growth = 0.058, inflation = 0.025;
  const discount = Math.pow((1 + inflation) / (1 + growth), 1 / 12);
  const analytic = Math.log1p(-balance * (1 - discount) / spending) / Math.log(discount);
  const result = durationMonths(balance, spending, growth);
  assert.equal(result.months, Math.floor(analytic));
  assert.deepEqual(result, durationMonths(balance, spending, growth, inflation));
  assert.ok(result.months < durationMonths(balance, spending, growth, 0).months);
});
test('inflation compounds monthly without changing the first withdrawal', () => {
  assert.equal(durationMonths(10000, 10000, 0).months, 1);
  assert.equal(durationMonths(120000, 10000, 0).months, 11);
  assert.equal(durationMonths(120000, 10000, 0.025, 0.025).months, 12);
  // Twelve nominal payments grow from 10,000 by the monthly equivalent of 2.5%.
  const monthlyInflation = Math.pow(1.025, 1 / 12);
  const payments = Array.from({ length: 12 }, (_, month) => 10000 * Math.pow(monthlyInflation, month));
  const budget = payments.reduce((sum, value) => sum + value, 0) + 0.01;
  assert.equal(durationMonths(budget, 10000, 0).months, 12);
});
test('spending outlook rejects invalid inflation and simulation horizons', () => {
  for (const invalid of [NaN, Infinity, -0.025]) assert.equal(durationMonths(100000, 1000, 0.05, invalid), null);
  assert.equal(durationMonths(100000, 1000, 0.05, 0.025, 0), null);
  assert.deepEqual(durationMonths(1000000, 1000, 0.05, 0.025, 12), { months: 12, capped: true });
});
test('effective tax grosses up withdrawals to leave enough for net spending', () => {
  const options = { taxRate: 0.1 };
  assert.deepEqual(durationMonths(120000, 9000, 0, 0, 600, options), { months: 12, capped: false });
  assert.equal(durationMonths(9999, 9000, 0, 0, 600, options).months, 0);
  assert.equal(durationMonths(120000, 9000, 0, 0).months, 13);
});
test('healthcare stops at the cutoff and zero healthcare preserves the old scenario', () => {
  // Two payments of (900 + 900) / .9, then ten of 900 / .9.
  const options = { healthcare: 900, healthcareMonths: 2, taxRate: 0.1 };
  assert.deepEqual(durationMonths(14000, 900, 0, 0, 600, options), { months: 12, capped: false });
  assert.equal(durationMonths(14000, 900, 0, 0, 600, { ...options, healthcareMonths: 0 }).months, 14);
  assert.deepEqual(durationMonths(1500000, 10000, 0.058, 0.025, 600, { healthcare: 0, healthcareMonths: 158 }), durationMonths(1500000, 10000, 0.058));
});
test('inflation, healthcare cutoff, and tax match nominal monthly cash flows', () => {
  const startingBalance = 500000, spending = 6000, healthcare = 1500, taxRate = 0.1, healthcareMonths = 24;
  const growth = Math.pow(1.058, 1 / 12), inflation = Math.pow(1.025, 1 / 12);
  let balance = startingBalance, months = 0;
  while (months < 600) {
    const cost = (spending + (months < healthcareMonths ? healthcare : 0)) * Math.pow(inflation, months) / (1 - taxRate);
    if (balance < cost) break;
    balance = (balance - cost) * growth;
    months++;
  }
  assert.deepEqual(durationMonths(startingBalance, spending, 0.058, 0.025, 600, { healthcare, healthcareMonths, taxRate }), { months, capped: false });
});
test('healthcare ends in the calendar year of age 65, using Central time', () => {
  assert.equal(healthcareMonthsRemaining(Date.parse('2026-11-17T18:00:00Z')), 158);
  assert.equal(healthcareMonthsRemaining(Date.parse('2040-01-01T05:59:59Z')), 1);
  assert.equal(healthcareMonthsRemaining(Date.parse('2040-01-01T06:00:00Z')), 0);
  assert.equal(healthcareMonthsRemaining(Date.parse('2045-07-01T18:00:00Z')), 0);
});
test('outlook rejects invalid tax and healthcare assumptions', () => {
  for (const taxRate of [-0.01, 1, NaN, Infinity]) assert.equal(durationMonths(100000, 1000, 0.05, 0.025, 600, { taxRate }), null);
  for (const healthcare of [-1, NaN, Infinity]) assert.equal(durationMonths(100000, 1000, 0.05, 0.025, 600, { healthcare }), null);
  for (const healthcareMonths of [-1, 1.5, NaN, Infinity]) assert.equal(durationMonths(100000, 1000, 0.05, 0.025, 600, { healthcareMonths }), null);
});
test('outlook ages use the projected year and preserve the cap and invalid-input wording', () => {
  const now = Date.parse('2026-11-15T18:00:00Z');
  assert.equal(outlookAgeSubtitle({ months: 420, capped: false }, now), 'To about age 86');
  assert.equal(outlookAgeSubtitle({ months: 600, capped: true }, now), 'Beyond age 101');
  assert.equal(outlookAgeSubtitle({ months: 6, capped: false }, now), 'To about age 52');
  assert.equal(outlookAgeSubtitle({ months: 0, capped: false }, now), 'To about age 51');
  assert.equal(outlookAgeSubtitle({ months: 600, capped: true }, Date.parse('2027-01-01T18:00:00Z')), 'Beyond age 102');
  assert.equal(outlookAgeSubtitle(null, now), 'Choose a monthly amount');
});
test('milestones do not invent a positive pace or show distant arrival dates', () => {
  assert.equal(milestone(1700001, 0).months, null);
  assert.equal(milestone(1700001, -0.1).months, null);
  assert.equal(milestone(1700001, 0.001).months, null);
  assert.equal(milestone(1800000, 0.06).target, 1900000);
});
