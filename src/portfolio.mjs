// Shared, dependency-free calculation model. Current values use actual prices.
// Growth history is total-return-normalized to current holdings, not a record
// of historical account balances. Distributions are assumed reinvested.
export function positive(value) { return typeof value === 'number' && Number.isFinite(value) && value > 0; }
const cents = value => Math.round(value * 100) / 100;
export function dateInZone(now, zone = 'America/New_York') {
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-US', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(now)).map(x => [x.type, x.value]));
  return `${p.year}-${p.month}-${p.day}`;
}
export function addDays(date, days) { const d = new Date(`${date}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + days); return d.toISOString().slice(0, 10); }
export function yearBefore(date) {
  const [year, month, day] = date.split('-').map(Number);
  const last = new Date(Date.UTC(year - 1, month, 0)).getUTCDate();
  return `${year - 1}-${String(month).padStart(2, '0')}-${String(Math.min(day, last)).padStart(2, '0')}`;
}
export function latestOnOrBefore(rows, date) {
  let lo = 0, hi = rows.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (rows[mid].date <= date) lo = mid + 1; else hi = mid; }
  return lo ? rows[lo - 1] : null;
}
function requireBar(rows, date, ticker) {
  const row = latestOnOrBefore(rows, date);
  if (!row || row.date !== date) throw new Error(`${ticker}: missing price on ${date}`);
  return row;
}
function businessDays(start, end) {
  let count = 0;
  for (let day = addDays(start, 1); day <= end; day = addDays(day, 1)) {
    const weekday = new Date(`${day}T12:00:00Z`).getUTCDay();
    if (weekday !== 0 && weekday !== 6) count++;
  }
  return count;
}
export function validateMarket(market, funds) {
  if (market?.schema_version !== 1 || !Number.isFinite(Date.parse(market.fetched_at))) throw new Error('Invalid market snapshot');
  const symbols = new Set(funds.flatMap(f => [f.ticker, f.proxy]));
  for (const symbol of symbols) {
    const series = market.series?.[symbol];
    if (!series || series.currency !== 'USD' || !Array.isArray(series.daily) || !series.daily.length) throw new Error(`${symbol}: missing USD history`);
    let previous = '';
    for (const row of series.daily) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(row.date) || row.date <= previous || !positive(row.close) || !positive(row.adjusted_close)) throw new Error(`${symbol}: invalid daily history`);
      previous = row.date;
    }
    let previousStamp = 0;
    for (const row of series.intraday || []) {
      if (!positive(row.close) || !positive(row.timestamp) || row.timestamp <= previousStamp || row.date !== dateInZone(row.timestamp * 1000, series.timezone || 'America/New_York')) throw new Error(`${symbol}: invalid intraday history`);
      previousStamp = row.timestamp;
    }
  }
}
function payoutsBetween(series, start, end) {
  return ['dividends', 'capitalGains'].flatMap(kind => Object.values(series.events?.[kind] || {})).filter(e => e.date > start && e.date <= end && positive(e.amount)).reduce((sum, e) => sum + e.amount, 0);
}
export function preparePortfolio(market, positions, funds, now = Date.now()) {
  validateMarket(market, funds);
  if (!positions?.length) throw new Error('No holdings were loaded');
  const definitions = new Map(funds.map(f => [f.ticker, f]));
  const identifiers = new Set();
  const warnings = [...(market.warnings || [])];
  const calendarDate = dateInZone(now);
  const rows = positions.map(position => {
    const definition = definitions.get(position.ticker);
    const id = `${position.owner}:${position.ticker}`;
    if (!definition || !['Kim', 'Ashley'].includes(position.owner) || !positive(position.shares) || identifiers.has(id)) throw new Error(`Invalid holding: ${id}`);
    identifiers.add(id);
    const series = market.series[position.ticker];
    const nav = series.daily.at(-1);
    if (nav.date > calendarDate) throw new Error(`${position.ticker}: price date is in the future`);
    const proxy = market.series[definition.proxy];
    const quote = proxy.intraday?.at(-1);
    let price = nav.close, growthFactor = 1, priceDate = nav.date, quoteTimestamp = null, estimated = false, intraday = false;
    if (quote && quote.date > nav.date && quote.date <= calendarDate) {
      const anchor = latestOnOrBefore(proxy.daily, nav.date);
      const lastComplete = latestOnOrBefore(proxy.daily, quote.date);
      if (anchor?.date === nav.date && lastComplete && businessDays(nav.date, quote.date) <= 2) {
        growthFactor = lastComplete.adjusted_close / anchor.adjusted_close;
        if (quote.date > lastComplete.date) growthFactor *= (quote.close + payoutsBetween(proxy, lastComplete.date, quote.date)) / lastComplete.close;
        if (definition.proxy_match === 'direct') price = quote.close;
        else price = nav.close * growthFactor - payoutsBetween(series, nav.date, quote.date);
        if (!positive(price) || !positive(growthFactor)) throw new Error(`${position.ticker}: invalid estimate`);
        priceDate = quote.date;
        quoteTimestamp = quote.timestamp;
        estimated = definition.type === 'MUTUALFUND';
        intraday = true;
      } else warnings.push(`${position.ticker}: no aligned recent proxy anchor; using its published ${nav.date} price.`);
    }
    return { ...definition, ...position, nav, series, price, value: position.shares * price, growthFactor, adjustedCurrent: nav.adjusted_close * growthFactor, priceDate, quoteTimestamp, estimated, intraday };
  });
  let common = new Set(rows[0].series.daily.map(b => b.date));
  for (const row of rows.slice(1)) { const dates = new Set(row.series.daily.map(b => b.date)); common = new Set([...common].filter(date => dates.has(date))); }
  const commonDates = [...common].sort();
  if (!commonDates.length) throw new Error('No shared price dates across the holdings');
  const commonDate = commonDates.at(-1);
  const asOf = rows.reduce((date, row) => row.priceDate > date ? row.priceDate : date, '');
  const yearTarget = yearBefore(commonDate);
  const annualDate = commonDates.filter(date => date <= yearTarget).at(-1);
  if (!annualDate || businessDays(annualDate, yearTarget) > 5) throw new Error('A complete year of comparable prices is required');
  let annualEnd = 0, annualStart = 0;
  for (const row of rows) {
    const end = requireBar(row.series.daily, commonDate, row.ticker);
    const start = requireBar(row.series.daily, annualDate, row.ticker);
    const value = row.shares * end.close;
    annualEnd += value;
    annualStart += value * start.adjusted_close / end.adjusted_close;
  }
  if (businessDays(commonDate, calendarDate) > 2) warnings.push(`Published history is older than two weekdays (${commonDate}). Check for a newer snapshot.`);
  if (new Date(now) - new Date(market.fetched_at) > 72 * 3600000) warnings.push('This saved snapshot is more than three days old.');
  return { rows, market, funds, commonDates, commonDate, asOf, calendarDate, annualDate, annualRate: annualEnd / annualStart - 1, warnings, total: cents(rows.reduce((sum, row) => sum + row.value, 0)) };
}
export function baselineTarget(portfolio, period) {
  if (period === 'today') return addDays(portfolio.asOf, -1);
  if (period === 'year') return yearBefore(portfolio.asOf);
  const reference = portfolio.calendarDate;
  if (period === 'month') return addDays(`${reference.slice(0, 7)}-01`, -1);
  if (period === 'week') { const day = new Date(`${reference}T12:00:00Z`).getUTCDay(); return addDays(reference, -((day + 6) % 7) - 1); }
  throw new Error(`Unknown comparison period: ${period}`);
}
export function summarize(rows) {
  const value = cents(rows.reduce((sum, row) => sum + row.value, 0));
  const baseline = rows.reduce((sum, row) => sum + row.baseline, 0);
  return { value, baseline, delta: value - baseline, rate: baseline > 0 ? value / baseline - 1 : 0 };
}
export function comparePeriod(portfolio, period) {
  const target = baselineTarget(portfolio, period);
  const baselineDate = portfolio.commonDates.filter(date => date <= target).at(-1);
  if (!baselineDate) throw new Error(`No history is available for ${period}`);
  const rows = portfolio.rows.map(row => {
    const bar = requireBar(row.series.daily, baselineDate, row.ticker);
    const baseline = row.value * bar.adjusted_close / row.adjustedCurrent;
    return { ...row, baseline, delta: row.value - baseline, rate: row.value / baseline - 1 };
  });
  const dates = portfolio.commonDates.filter(date => date >= baselineDate);
  const history = dates.map(date => ({ date, value: portfolio.rows.reduce((sum, row) => sum + row.value * requireBar(row.series.daily, date, row.ticker).adjusted_close / row.adjustedCurrent, 0), estimated: false }));
  const summary = summarize(rows);
  if (history.at(-1).date < portfolio.asOf || cents(history.at(-1).value) !== summary.value) history.push({ date: portfolio.asOf, value: summary.value, estimated: true });
  else history.at(-1).value = summary.value;
  const pending = (period === 'week' || period === 'month') && baselineDate === portfolio.asOf;
  return { ...summary, rows, history, baselineDate, endDate: portfolio.asOf, pending };
}
export const OUTLOOK_ANNUAL_INFLATION = 0.025;
export function healthcareMonthsRemaining(now = Date.now(), birthYear = 1975) {
  const [year, month] = dateInZone(now, 'America/Chicago').split('-').map(Number);
  // Like the age subtitle, use calendar years rather than unknown birthdays.
  return Math.max(0, (birthYear + 65 - year) * 12 - (month - 1));
}
export function durationMonths(balance, spending, annualRate, annualInflation = OUTLOOK_ANNUAL_INFLATION, horizon = 600, { healthcare = 0, healthcareMonths = 0, taxRate = 0 } = {}) {
  if (!Number.isFinite(balance) || balance < 0 || !positive(spending) || !Number.isFinite(annualRate) || annualRate <= -1 || !Number.isFinite(annualInflation) || annualInflation < 0 || !Number.isInteger(horizon) || horizon < 1 || !Number.isFinite(healthcare) || healthcare < 0 || !Number.isInteger(healthcareMonths) || healthcareMonths < 0 || !Number.isFinite(taxRate) || taxRate < 0 || taxRate >= 1) return null;
  // Work in starting-month dollars. Dividing growth by monthly inflation is
  // equivalent to raising nominal spending by (1 + annualInflation)^(1/12)
  // after each withdrawal; it also keeps equal growth/inflation rates exact.
  const monthlyRealGrowth = Math.exp((Math.log1p(annualRate) - Math.log1p(annualInflation)) / 12);
  let months = 0;
  while (months < horizon) {
    // Gross up the full cost so the after-tax withdrawal covers both expenses.
    const withdrawal = (spending + (months < healthcareMonths ? healthcare : 0)) / (1 - taxRate);
    if (balance < withdrawal) break;
    balance = (balance - withdrawal) * monthlyRealGrowth;
    months++;
  }
  return { months, capped: months === horizon };
}
export function outlookAgeSubtitle(result, now = Date.now(), birthYear = 1975) {
  if (!result) return 'Choose a monthly amount';
  const [year, month] = dateInZone(now, 'America/Chicago').split('-').map(Number);
  const endYear = year + Math.floor((month - 1 + result.months) / 12);
  const age = endYear - birthYear;
  return `${result.capped ? 'Beyond age' : 'To about age'} ${age}`;
}
export function milestone(balance, annualRate, step = 100000) {
  if (!positive(balance) || !positive(step)) throw new Error('Invalid milestone value');
  const lower = Math.floor(balance / step) * step;
  const target = lower + step;
  const months = annualRate > 0 ? Math.log(target / balance) / (Math.log1p(annualRate) / 12) : null;
  return { lower, target, gap: target - balance, progress: (balance - lower) / step * 100, months: months !== null && months <= 12 ? Math.ceil(months) : null };
}
