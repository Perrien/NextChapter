import { preparePortfolio, comparePeriod, summarize, durationMonths, milestone, dateInZone } from './portfolio.mjs';
import { icon } from './icons.mjs';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const money = value => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value);
const signedMoney = value => `${value < -0.005 ? '−' : '+'}${money(Math.abs(value))}`;
const percent = value => `${value < -0.0000001 ? '−' : '+'}${Math.abs(value * 100).toFixed(2)}%`;
const dateLabel = (date, year = false) => new Date(`${date}T12:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', ...(year ? { year: 'numeric' } : {}), timeZone: 'UTC' });
const escape = value => String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const groups = { domestic: 'Domestic', international: 'International', bonds: 'Bonds' };
const periodLabels = { today: 'latest trading day', week: 'this week', month: 'this month', year: 'over the past year' };
const periodNames = { today: 'Latest trading day', week: 'This week', month: 'This month', year: 'Past year' };
const state = { period: 'month', season: 'auto', owner: 'Joint' };
let portfolio = null, view = null, loading = false, publication = null, lastRefresh = 0;
$$('[data-icon]').forEach(element => { element.innerHTML = icon(element.dataset.icon); });

// These controls are generic app code, so connecting publication does not require
// decrypting or re-protecting the household's existing personal page.
const workflowUrl = 'https://github.com/Perrien/NextChapter/actions/workflows/publish.yml';
const localPreview = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
$('.preview-label strong').textContent = localPreview ? 'Local preview' : 'Saved prices';
$('.site-footer > span:last-child').textContent = localPreview ? 'Local preview · Encrypted shared access' : 'Updated a few times each weekday.';
$('.data-tools-panel > div > p').textContent = 'Prices refresh a few times each weekday. Request a fresh look whenever you need one.';
$('.data-tools dl > div:last-child dd').textContent = '11:15 AM, 2:15 PM & 9:15 PM CT · weekdays';
const updateLink = document.createElement('a');
updateLink.id = 'update-prices-link';
updateLink.className = 'update-prices-button';
updateLink.href = workflowUrl;
updateLink.target = '_blank'; updateLink.rel = 'noopener noreferrer';
updateLink.innerHTML = `Update prices now ${icon('external-link')}`;
$('.data-tools-action').prepend(updateLink);
$('#reload-data-button').className = 'saved-prices-button';
$('.data-tools-explanation').textContent = 'Opens GitHub. Choose “Run workflow” to download and publish a fresh snapshot, then reload saved prices here.';
const publicationRow = document.createElement('div');
publicationRow.innerHTML = '<dt>Site snapshot published</dt><dd id="publication-date">—</dd>';
$('.data-tools dl').append(publicationRow);

function season() {
  if (state.season !== 'auto') return state.season;
  const month = Number(dateInZone(Date.now(), 'America/Chicago').slice(5, 7));
  return month >= 3 && month <= 5 ? 'spring' : month >= 6 && month <= 8 ? 'summer' : month >= 9 && month <= 11 ? 'autumn' : 'winter';
}
function condition(rate) {
  const [moderate, severe] = { today: [0.003, 0.014], week: [0.008, 0.035], month: [0.012, 0.055], year: [0.04, 0.15] }[state.period];
  return rate > moderate ? 'sunny' : rate >= -moderate ? 'cloudy' : rate > -severe ? 'rainy' : 'storm';
}
function weatherMeta(kind) {
  const winter = season() === 'winter';
  return kind === 'sunny' ? { label: 'Clear skies', icon: 'sun' } : kind === 'cloudy' ? { label: 'A quiet spell', icon: 'sun-cloud' } : kind === 'rainy' ? { label: winter ? 'A few flurries' : 'A little drizzle', icon: winter ? 'snow' : 'rain' } : { label: winter ? 'An icy spell' : 'Stormy skies', icon: winter ? 'snow' : 'storm' };
}
function setDelta(element, value, suffix = '') {
  element.textContent = `${signedMoney(value)}${suffix}`;
  element.classList.toggle('negative', value < -0.005);
}
function showBanner(message = '', error = false) {
  const banner = $('#data-banner');
  banner.textContent = message;
  banner.hidden = !message;
  banner.classList.toggle('is-error', error);
}
function renderHero() {
  const kind = condition(view.rate);
  const selectedSeason = season();
  document.body.dataset.season = selectedSeason;
  document.body.dataset.condition = kind;
  $('#household-value').textContent = money(view.value);
  const estimates = portfolio.rows.filter(row => row.estimated).length;
  const intraday = portfolio.rows.some(row => row.intraday);
  $('#value-caption').textContent = estimates ? 'Estimated value now' : intraday ? 'Latest market value' : 'Value at latest published prices';
  $('#household-change').textContent = signedMoney(view.delta);
  $('#household-percent').textContent = percent(view.rate);
  $('#hero-period').textContent = periodLabels[state.period];
  $('#hero-arrow').innerHTML = icon(view.delta < 0 ? 'arrow-down-right' : 'arrow-up-right');
  const headlines = {
    sunny: { spring: 'A little spring sunshine.', summer: 'Hello, sunshine.', autumn: 'Golden skies.', winter: 'Bright winter skies.' },
    cloudy: { spring: 'A quiet spring day.', summer: 'A little cloud cover.', autumn: 'A quiet autumn spell.', winter: 'Still winter skies.' },
    rainy: { spring: 'A few passing showers.', summer: 'A little summer rain.', autumn: 'A blustery spell.', winter: 'A little frost.' },
    storm: { spring: 'A spring storm.', summer: 'Thunder rolling through.', autumn: 'A stormy autumn spell.', winter: 'An icy spell.' }
  };
  const noun = { today: 'day', week: 'week', month: 'month', year: 'year' }[state.period];
  const messages = { sunny: `A bright ${noun}. Look what you’re building.`, cloudy: `A quieter ${noun}. The whole picture is right here.`, rainy: `A softer ${noun}. A little perspective helps.`, storm: `A rougher ${noun}. Take a breath and look at the whole picture.` };
  $('#weather-description').textContent = headlines[kind][selectedSeason];
  $('#weather-message').textContent = view.pending ? `Awaiting the first new quotes for ${periodLabels[state.period]}.` : messages[kind];
  $('#season-signature').textContent = `THE ${selectedSeason.toUpperCase()} EDITION`;
  $('#section-period').textContent = `${periodNames[state.period]} at a glance`;
  $('#hero-source').textContent = `${estimates ? `${estimates} fund estimates` : 'Published prices'} · ${dateLabel(portfolio.asOf, true)} · Change includes payouts`;
  $$('[data-period]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.period === state.period)));
}
function renderCards() {
  for (const group of Object.keys(groups)) {
    const summary = summarize(view.rows.filter(row => row.group === group));
    const weather = weatherMeta(condition(summary.rate));
    $(`[data-group-value="${group}"]`).textContent = money(summary.value);
    setDelta($(`[data-group-change="${group}"]`), summary.delta, ` ${periodLabels[state.period]}`);
    const badge = $(`[data-group-return="${group}"]`);
    badge.textContent = percent(summary.rate);
    badge.classList.toggle('negative', summary.delta < 0);
    $(`[data-group-condition="${group}"]`).textContent = weather.label;
    const glyph = $(`[data-group-icon="${group}"]`);
    glyph.innerHTML = icon(weather.icon);
    glyph.classList.toggle('is-wet', summary.delta < 0);
  }
  renderOwner();
}
function renderOwner() {
  if (!view) return;
  const rows = state.owner === 'Joint' ? view.rows : view.rows.filter(row => row.owner === state.owner);
  const summary = summarize(rows);
  const weather = weatherMeta(condition(summary.rate));
  $('#owner-title').textContent = state.owner === 'Joint' ? 'Joint portfolio' : `${state.owner}’s portfolio`;
  $('#owner-avatar').textContent = state.owner === 'Joint' ? 'K+A' : state.owner[0];
  $('#owner-avatar').classList.toggle('ashley-avatar', state.owner === 'Ashley');
  $('#owner-value').textContent = money(summary.value);
  $('#owner-value-caption').textContent = rows.some(row => row.estimated) ? 'Estimated portfolio value' : rows.some(row => row.intraday) ? 'Latest market value' : 'Value at published prices';
  setDelta($('#owner-change'), summary.delta);
  $('#owner-return').textContent = `${percent(summary.rate)} ${periodLabels[state.period]}`;
  $('#owner-weather-icon').innerHTML = icon(weather.icon);
  $('#owner-condition').textContent = weather.label;
  $('#owner-count').textContent = `${rows.length} holdings${state.owner === 'Joint' ? ' · Kim & Ashley' : ''}`;
  $('#owner-message').textContent = summary.rate > 0.001 ? 'A little more room to dream.' : summary.rate < -0.001 ? 'A little perspective for the journey.' : 'Taking the quieter road.';
  $$('[data-owner]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.owner === state.owner)));
}
function renderMilestone() {
  const result = milestone(portfolio.total, portfolio.annualRate);
  $('#milestone-target').textContent = money(result.target);
  $('#milestone-gap').textContent = money(result.gap);
  $('#milestone-start').textContent = money(result.lower);
  $('#milestone-end').textContent = money(result.target);
  $('#milestone-fill').style.width = `${result.progress}%`;
  $('#milestone-marker').style.left = `${result.progress}%`;
  $('#milestone-track').setAttribute('aria-valuenow', result.progress.toFixed(2));
  $('#milestone-track').setAttribute('aria-label', `Progress from ${money(result.lower)} to ${money(result.target)}`);
  $('#milestone-pace').textContent = result.months ? `Around ${result.months} ${result.months === 1 ? 'month' : 'months'} at the past year’s pace` : `${money(result.gap)} to your next milestone`;
}
function renderOutlook() {
  if (!portfolio) return;
  const input = $('#monthly-spending');
  const result = input.validity.valid && input.value !== '' ? durationMonths(portfolio.total, Number(input.value), portfolio.annualRate) : null;
  const host = $('#outlook-duration');
  if (!result) host.textContent = 'Set spending';
  else if (result.capped) host.textContent = '50+ years';
  else if (!result.months) host.textContent = 'Under a month';
  else {
    const years = Math.floor(result.months / 12), months = result.months % 12;
    host.innerHTML = years ? `${years} ${years === 1 ? 'year' : 'years'}${months ? ` <small>${months} mo.</small>` : ''}` : `${months} months`;
  }
  host.setAttribute('aria-label', !result ? 'Enter a positive spending amount' : result.capped ? 'At least 50 years under this constant-growth assumption' : `Approximately ${result.months} months under this assumption`);
  $('#annual-growth').innerHTML = `${percent(portfolio.annualRate)} <small>/ year</small>`;
}
function splitLayout(rows, x, y, width, height) {
  if (rows.length === 1) return [{ row: rows[0], x, y, width, height }];
  const value = rows.reduce((sum, row) => sum + row.value, 0);
  let part = 0, index = 1, best = Infinity;
  for (let i = 1; i < rows.length; i++) { part += rows[i - 1].value; const distance = Math.abs(value / 2 - part); if (distance < best) { index = i; best = distance; } }
  const before = rows.slice(0, index), after = rows.slice(index), fraction = before.reduce((sum, row) => sum + row.value, 0) / value;
  return width >= height ? [...splitLayout(before, x, y, width * fraction, height), ...splitLayout(after, x + width * fraction, y, width * (1 - fraction), height)] : [...splitLayout(before, x, y, width, height * fraction), ...splitLayout(after, x, y + height * fraction, width, height * (1 - fraction))];
}
function renderTreemap() {
  if (!view) return;
  const host = $('#treemap'), width = host.clientWidth, height = host.clientHeight;
  if (!width || !height) return;
  const sorted = [...view.rows].sort((a, b) => b.value - a.value);
  const small = sorted.filter(row => row.value < portfolio.total * 0.02);
  const tiles = sorted.filter(row => row.value >= portfolio.total * 0.02);
  if (small.length) tiles.push({ ticker: 'other', name: `${small.length} smaller holdings`, short_name: 'Smaller patches', ...summarize(small), children: small });
  tiles.sort((a, b) => b.value - a.value);
  const focused = host.contains(document.activeElement) ? document.activeElement.dataset.ticker : null;
  host.replaceChildren();
  splitLayout(tiles, 0, 0, width, height).forEach(tile => {
    const row = tile.row, button = document.createElement('button');
    button.type = 'button';
    button.dataset.ticker = row.ticker;
    button.className = `holding-tile${row.delta < 0 ? ' tile-negative' : ''}${tile.width < 105 || tile.height < 95 ? ' tile-compact' : ''}${tile.width < 65 || tile.height < 48 ? ' tile-small' : ''}${tile.width < 38 ? ' tile-tiny' : ''}`;
    button.style.cssText = `left:${tile.x / width * 100}%;top:${tile.y / height * 100}%;width:${tile.width / width * 100}%;height:${tile.height / height * 100}%;`;
    button.setAttribute('aria-label', `${row.name}, ${money(row.value)}, ${percent(row.rate)} ${periodLabels[state.period]}. Open details.`);
    button.title = `${row.ticker === 'other' ? row.name : row.ticker}: ${money(row.value)} · ${percent(row.rate)}`;
    button.innerHTML = `<span><span class="tile-ticker">${row.ticker === 'other' ? `+ ${small.length} more` : escape(row.ticker)}</span><span class="tile-name">${escape(row.short_name)}</span></span><span class="tile-return">${percent(row.rate)}</span>`;
    button.addEventListener('click', () => openHolding(row));
    host.append(button);
  });
  if (focused) $(`[data-ticker="${CSS.escape(focused)}"]`, host)?.focus();
}
function renderHistory() {
  if (!view) return;
  setDelta($('#history-delta'), view.delta);
  $('#history-subtitle').textContent = `Growth from ${dateLabel(view.baselineDate, true)}`;
  const host = $('#history-chart'), width = host.clientWidth, height = host.clientHeight;
  if (!width || !height) return;
  const data = view.history;
  const low = Math.min(...data.map(x => x.value)), high = Math.max(...data.map(x => x.value));
  const padding = Math.max((high - low) * 0.15, portfolio.total * 0.0002);
  const minimum = low - padding, maximum = high + padding;
  const firstTime = Date.parse(data[0].date), span = Math.max(Date.parse(data.at(-1).date) - firstTime, 86400000);
  const points = data.map(row => ({ ...row, x: 8 + (Date.parse(row.date) - firstTime) / span * (width - 16), y: 18 + (maximum - row.value) / (maximum - minimum) * (height - 37) }));
  if (points.length === 1) points[0].x = width / 2;
  const estimated = points.at(-1).estimated;
  const solid = estimated ? points.slice(0, -1) : points;
  const path = solid.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ');
  const allPath = points.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ');
  const last = points.at(-1), prior = points.at(-2) || last;
  const color = view.delta < 0 ? '#a17457' : '#829b75';
  const compact = value => new Intl.NumberFormat('en-US', { notation: 'compact', style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(value);
  host.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Growth of current holdings from ${dateLabel(view.baselineDate, true)} to ${dateLabel(view.endDate, true)}, scaled to current value. Includes reinvested payouts."><defs><linearGradient id="history-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="${color}" stop-opacity=".2"/><stop offset="100%" stop-color="${color}" stop-opacity="0"/></linearGradient></defs><text x="8" y="11" class="chart-axis-label">${compact(high)}</text><path d="M8 ${height - 2}H${width - 8}" fill="none" stroke="#e5e9df"/><path d="${allPath} L${last.x},${height} L${points[0].x},${height}Z" fill="url(#history-fill)"/><path d="${path}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>${estimated ? `<path d="M${prior.x},${prior.y}L${last.x},${last.y}" fill="none" stroke="${color}" stroke-width="2" stroke-dasharray="3 4"/>` : ''}${points.map((p, i) => `<circle cx="${p.x}" cy="${p.y}" r="${i === points.length - 1 ? 3.5 : 2}" fill="${color}"><title>${dateLabel(p.date, true)}: ${money(p.value)}${p.estimated ? ' (estimate)' : ''}</title></circle>`).join('')}</svg>`;
  $('#history-start').textContent = dateLabel(view.baselineDate);
  $('#history-end').textContent = dateLabel(view.endDate);
  $('#history-price-note').textContent = estimated ? 'Dashed segment = current estimate.' : 'Published prices. Not actual past account balances.';
}
function openHolding(row) {
  const dialog = $('#holding-dialog'), grouped = row.ticker === 'other';
  $('#holding-ticker').textContent = grouped ? 'THE SMALLER PATCHES' : row.ticker;
  $('#holding-name').textContent = row.name;
  $('#holding-value').textContent = money(row.value);
  setDelta($('#holding-change'), row.delta);
  $('#holding-change').textContent += ` · ${percent(row.rate)} ${periodLabels[state.period]} · includes payouts`;
  $('#holding-owner').textContent = grouped ? 'Kim & Ashley' : row.owner;
  $('#holding-shares').previousElementSibling.textContent = grouped ? 'Holdings' : 'Shares';
  $('#holding-shares').textContent = grouped ? String(row.children.length) : row.shares.toLocaleString('en-US', { maximumFractionDigits: 6 });
  $('#holding-price').parentElement.hidden = grouped;
  $('#holding-price').textContent = grouped ? '' : row.price.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: row.estimated ? 4 : 2 });
  $('#holding-group').textContent = grouped ? 'Mixed' : groups[row.group];
  $('#holding-price-note').textContent = grouped ? 'Select a holding for its individual price and source.' : `${row.estimated ? `Estimated from ${row.proxy} (${row.proxy_match} match)` : row.intraday ? 'Market quote' : 'Published closing price'} · ${dateLabel(row.priceDate, true)}. ${row.estimated ? row.proxy_note : ''}`;
  $('#holding-source').hidden = grouped;
  if (!grouped) $('#holding-source').href = row.source;
  const list = $('#small-holdings-list');
  list.replaceChildren();
  if (grouped) for (const child of row.children) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'small-holding-button';
    button.innerHTML = `<span>${escape(child.ticker)}</span><span>${money(child.value)}</span>`;
    button.addEventListener('click', () => openHolding(child));
    list.append(button);
  }
  if (!dialog.open) dialog.showModal();
}
function render() {
  if (!portfolio) return;
  view = comparePeriod(portfolio, state.period);
  renderHero(); renderCards(); renderMilestone(); renderOutlook(); renderTreemap(); renderHistory();
  $('#snapshot-status').textContent = `Yahoo prices through ${dateLabel(portfolio.asOf, true)}`;
  $('#close-date').textContent = dateLabel(portfolio.commonDate, true);
  $('#download-date').textContent = new Date(portfolio.market.fetched_at).toLocaleString('en-US', { timeZone: 'America/Chicago', dateStyle: 'medium', timeStyle: 'short' }) + ' CT';
  $('#publication-date').textContent = publication?.source_fetched_at === portfolio.market.fetched_at && Number.isFinite(Date.parse(publication.built_at)) ? new Date(publication.built_at).toLocaleString('en-US', { timeZone: 'America/Chicago', dateStyle: 'medium', timeStyle: 'short' }) + ' CT' : '—';
  $('#annual-period-note').textContent = `The projection growth assumption uses ${dateLabel(portfolio.annualDate, true)} through ${dateLabel(portfolio.commonDate, true)}. All calculations assume today's holdings; they exclude deposits and withdrawals from past performance.`;
  $('#period-announcement').textContent = `${periodNames[state.period]} change: ${signedMoney(view.delta)}, ${percent(view.rate)}.`;
}
async function readJson(path) {
  const response = await fetch(new URL(path, import.meta.url), { cache: 'no-store' });
  if (!response.ok) throw new Error(`Could not load ${path} (${response.status})`);
  return response.json();
}
async function loadSaved() {
  if (loading) return;
  loading = true;
  $('#reload-data-button').disabled = true;
  try {
    const [market, definitions, nextPublication] = await Promise.all([readJson('./data/market.json'), readJson('./data/funds.json'), readJson('./data/publication.json').catch(() => null)]);
    const personal = JSON.parse($('#private-holdings').textContent);
    const next = preparePortfolio(market, personal.positions, definitions.funds);
    const nextView = comparePeriod(next, state.period);
    // Validate before replacing the currently displayed good snapshot.
    if (!Number.isFinite(nextView.value)) throw new Error('Invalid portfolio value');
    portfolio = next;
    publication = nextPublication;
    lastRefresh = Date.now();
    render();
    const important = next.warnings.filter(text => !text.includes('gaps in five-minute'));
    showBanner(important.join(' '));
    $('#manual-update-status').textContent = `Saved prices loaded. Source closes through ${dateLabel(next.commonDate, true)}.`;
  } catch (error) {
    console.error('Saved price snapshot could not be loaded:', error);
    showBanner(portfolio ? "Couldn't load a newer snapshot. Keeping the last successfully loaded prices. Please try again later." : 'Prices could not be loaded. Please try reloading the saved prices.', true);
    $('#manual-update-status').textContent = portfolio ? 'Previous prices retained.' : 'No valid snapshot is available.';
  } finally {
    loading = false;
    $('#reload-data-button').disabled = false;
    $$('[data-period], [data-owner], #monthly-spending').forEach(element => { element.disabled = !portfolio; });
  }
}
$$('[data-period]').forEach(button => button.addEventListener('click', () => { state.period = button.dataset.period; render(); }));
$$('[data-owner]').forEach(button => button.addEventListener('click', () => { state.owner = button.dataset.owner; renderOwner(); }));
$('#season').addEventListener('change', event => { state.season = event.target.value; render(); });
$('#monthly-spending').addEventListener('input', renderOutlook);
$('#reload-data-button').addEventListener('click', loadSaved);
$('#data-info-button').addEventListener('click', () => $('#data-dialog').showModal());
$('#lock-button').addEventListener('click', () => {
  // Navigate to the encrypted document; a fragment-only change would leave it open.
  const target = new URL(location.href);
  target.hash = '';
  target.search = '?staticrypt_logout';
  location.replace(target.href);
});
window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
$$('[data-close-dialog]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
$$('[data-period], [data-owner], #monthly-spending').forEach(element => { element.disabled = true; });
await loadSaved();
// Check saved site files while visible; these never contact the price provider
// or start an Actions run.
setInterval(() => { if (!document.hidden) loadSaved(); }, 5 * 60 * 1000);
document.addEventListener('visibilitychange', () => { if (!document.hidden && Date.now() - lastRefresh > 60000) loadSaved(); });
let resizeFrame;
if ('ResizeObserver' in window) {
  const observer = new ResizeObserver(() => { cancelAnimationFrame(resizeFrame); resizeFrame = requestAnimationFrame(() => { renderTreemap(); renderHistory(); }); });
  observer.observe($('#treemap'));
  observer.observe($('#history-chart'));
} else window.addEventListener('resize', () => { renderTreemap(); renderHistory(); });
