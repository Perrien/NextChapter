#!/usr/bin/env python3
"""Fetch public ticker data only. Atomic output retains the previous good snapshot."""
import argparse
import calendar
import datetime as dt
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
UTC = dt.timezone.utc


def positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def fetch(symbol, period, interval):
    params = urllib.parse.urlencode({"range": period, "interval": interval, "events": "div,splits,capitalGains"})
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(symbol, safe="") + "?" + params
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=25) as response:
        data = json.load(response)
    result = data.get("chart", {}).get("result")
    if not result:
        raise ValueError(f"Yahoo returned no series: {data.get('chart', {}).get('error')!r}")
    return result[0]


def fetch_validated(symbol, period, interval, validator, fetcher=fetch, attempts=3):
    """Retry a failed request/validation, keeping ticker and request context."""
    for attempt in range(1, attempts + 1):
        try:
            result = fetcher(symbol, period, interval)
            if result.get("meta", {}).get("symbol", symbol) != symbol:
                raise ValueError(f"Requested {symbol}, received {result['meta'].get('symbol')!r}")
            return result, validator(result)
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError, TypeError) as error:
            detail = f"{symbol} [range={period}, interval={interval}, attempt={attempt}/{attempts}]: {type(error).__name__}: {error}"
            if attempt == attempts:
                raise ValueError(detail) from error
            print(f"Retrying price request: {detail}", file=sys.stderr, flush=True)
            time.sleep(2 ** (attempt - 1))


def daily_series(result, now, warnings=None):
    meta = result["meta"]
    if meta.get("currency") != "USD":
        raise ValueError(f"Only USD prices are supported; received {meta.get('currency')!r}")
    tz = ZoneInfo(meta["exchangeTimezoneName"])
    today = now.astimezone(tz).date().isoformat()
    session_end = meta.get("currentTradingPeriod", {}).get("regular", {}).get("end")
    quote = result["indicators"]["quote"][0]
    adjusted = result["indicators"].get("adjclose", [{}])[0].get("adjclose", [])
    closes = quote.get("close", [])
    timestamps = result.get("timestamp", [])
    rows = []
    for i, stamp in enumerate(timestamps):
        date = dt.datetime.fromtimestamp(stamp, tz).date().isoformat()
        # ETF daily endpoints can include a partial current-session bar. Keep
        # those quotes in intraday data, not in completed daily history.
        if date == today and session_end and now.timestamp() < session_end:
            continue
        close = closes[i] if i < len(closes) else None
        adj = adjusted[i] if i < len(adjusted) else None
        # Yahoo can append an explicit null placeholder after the market closes
        # while its daily feed is still incomplete. Only that final,
        # current-day row may be deferred; never conceal a historical gap,
        # a truncated response, or a zero/negative/non-finite price.
        pending_close = (date == today
                       and i == len(timestamps) - 1 and i < len(closes) and i < len(adjusted)
                       and (close is None or adj is None)
                       and (close is None or positive(close)) and (adj is None or positive(adj)))
        if pending_close:
            if warnings is not None:
                warnings.append(f"Yahoo's daily close for {date} is not available yet. Last published closes and available intraday quotes are used; any fund estimate is labeled.")
            print(f"Pending daily close on {date}: close={close!r}, adjusted_close={adj!r}; omitted unfinished current-day row.", flush=True)
            continue
        if not positive(close) or not positive(adj):
            raise ValueError(f"Invalid close/adjusted close on {date}: close={close!r}, adjusted_close={adj!r}, row={i}, timestamp={stamp!r}, type={meta.get('instrumentType')!r}, timezone={meta.get('exchangeTimezoneName')!r}, close_count={len(closes)}, adjusted_count={len(adjusted)}")
        rows.append({"date": date, "close": round(close, int(meta.get("priceHint", 2))), "adjusted_close": adj})
    if not rows or any(a["date"] >= b["date"] for a, b in zip(rows, rows[1:])):
        raise ValueError("Empty, duplicate, or unsorted daily history")
    return rows


def intraday_series(result):
    meta = result["meta"]
    if meta.get("currency") != "USD" or meta.get("dataGranularity") != "5m":
        raise ValueError(f"Expected USD five-minute quotes; currency={meta.get('currency')!r}, interval={meta.get('dataGranularity')!r}")
    tz = ZoneInfo(meta["exchangeTimezoneName"])
    closes = result["indicators"]["quote"][0].get("close", [])
    rows = []
    for i, stamp in enumerate(result.get("timestamp", [])):
        if i < len(closes) and positive(closes[i]):
            date = dt.datetime.fromtimestamp(stamp, tz).date().isoformat()
            rows.append({"timestamp": stamp, "date": date, "close": closes[i]})
    if not rows or any(a['timestamp'] >= b['timestamp'] for a, b in zip(rows, rows[1:])):
        raise ValueError("Empty, duplicate, or unsorted usable intraday quotes")
    return rows


def merge_daily(old, new):
    """Rebase saved history after payouts/splits using overlapping observations.

    Non-uniform historical corrections require a complete history reload.
    """
    old_by_date = {row["date"]: row for row in old}
    overlap = [row for row in new if row["date"] in old_by_date]
    if not overlap:
        raise ValueError("No overlap; full history is required")
    first = overlap[0]
    old_first = old_by_date[first["date"]]
    adj_factor = first["adjusted_close"] / old_first["adjusted_close"]
    close_factor = first["close"] / old_first["close"]
    for row in overlap:
        previous = old_by_date[row["date"]]
        if not math.isclose(row["adjusted_close"] / previous["adjusted_close"], adj_factor, rel_tol=2e-5):
            raise ValueError("Non-uniform adjusted-price revision; full history is required")
        if not math.isclose(row["close"] / previous["close"], close_factor, rel_tol=2e-5):
            raise ValueError("Non-uniform close-price revision; full history is required")
    before = [{**row, "close": row["close"] * close_factor, "adjusted_close": row["adjusted_close"] * adj_factor} for row in old if row["date"] < new[0]["date"]]
    return before + new


def normalize_events(events, timezone):
    tz = ZoneInfo(timezone)
    output = {}
    for kind, items in events.items():
        output[kind] = {key: {**value, "date": dt.datetime.fromtimestamp(value["date"], tz).date().isoformat()} for key, value in items.items()}
    return output


def build_snapshot(funds, previous, fetcher=fetch, now=None, full=False, delay=0.2):
    now = now or dt.datetime.now(UTC)
    symbols = sorted({f["ticker"] for f in funds} | {f["proxy"] for f in funds})
    proxies = sorted({f["proxy"] for f in funds})
    series = {}
    warnings = []
    pending_notices = {}

    def read_daily(symbol, period, latest_saved=None):
        def validate(result):
            notes = []
            rows = daily_series(result, now, notes)
            if period == "2y" and len(rows) < 260:
                raise ValueError(f"Insufficient trailing-year history: {len(rows)} observations")
            if latest_saved and rows[-1]['date'] < latest_saved:
                raise ValueError(f"Yahoo history regressed to {rows[-1]['date']}; saved history already reaches {latest_saved}")
            return rows, notes
        result, (rows, notes) = fetch_validated(symbol, period, "1d", validate, fetcher)
        return result, rows, notes

    for symbol in symbols:
        saved = previous.get("series", {}).get(symbol)
        complete = full or saved is None
        period = "2y" if complete else "1mo"
        print(f"Fetching daily {symbol} [range={period}, interval=1d]", flush=True)
        latest_saved = saved['daily'][-1]['date'] if saved else None
        result, rows, notes = read_daily(symbol, period, latest_saved)
        if not complete:
            try:
                precision = int(result["meta"].get("priceHint", 2))
                old_rows = [{**row, "close": round(row["close"], precision)} for row in saved["daily"]]
                rows = merge_daily(old_rows, rows)
            except ValueError as error:
                print(f"Daily {symbol}: reloading full history after {error}", flush=True)
                result, rows, notes = read_daily(symbol, "2y", latest_saved)
                complete = True
        if len(rows) < 260:
            raise ValueError(f"{symbol}: insufficient history for the trailing-year calculation")
        meta = result["meta"]
        events = normalize_events(result.get("events", {}), meta["exchangeTimezoneName"])
        if saved and not complete:
            for kind, items in saved.get("events", {}).items():
                events[kind] = {**items, **events.get(kind, {})}
        series[symbol] = {"name": meta.get("longName") or meta.get("shortName") or symbol, "type": meta.get("instrumentType"), "currency": meta["currency"], "price_decimals": int(meta.get("priceHint", 2)), "timezone": meta["exchangeTimezoneName"], "daily": rows, "events": events, "intraday": []}
        for note in notes:
            pending_notices.setdefault(note, []).append(symbol)
        print(f"Daily {symbol}: {len(rows)} observations, through {rows[-1]['date']}", flush=True)
        if delay:
            time.sleep(delay)
    warnings.extend(f"{', '.join(symbols)}: {note}" for note, symbols in pending_notices.items())
    for symbol in proxies:
        _, rows = fetch_validated(symbol, "5d", "5m", intraday_series, fetcher)
        series[symbol]["intraday"] = rows
        gaps = sum(b["timestamp"] - a["timestamp"] > 300 for a, b in zip(rows, rows[1:]) if a["date"] == b["date"])
        if gaps:
            warnings.append(f"{symbol}: {gaps} gaps in five-minute history; only observed quotes are used.")
        print(f"Quotes {symbol}: {len(rows)} observations", flush=True)
        if delay:
            time.sleep(delay)
    types = {f["ticker"]: f["type"] for f in funds}
    for ticker, expected in types.items():
        if series[ticker]["type"] != expected:
            raise ValueError(f"{ticker}: expected {expected}, received {series[ticker]['type']}")
    common = set.intersection(*[{b["date"] for b in series[f["ticker"]]["daily"]} for f in funds])
    if not common:
        raise ValueError("The holdings have no common daily observation")
    common_date = max(common)
    endpoint = dt.date.fromisoformat(common_date)
    year_before = endpoint.replace(year=endpoint.year - 1, day=min(endpoint.day, calendar.monthrange(endpoint.year - 1, endpoint.month)[1]))
    if min(common) > year_before.isoformat():
        raise ValueError("Common history does not cover a full year")
    return {"schema_version": 1, "provider": "Yahoo Finance", "fetched_at": now.isoformat(), "common_close_date": common_date, "warnings": warnings, "series": series}


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, separators=(",", ":"), allow_nan=False) + "\n")
    temporary.replace(path)


def report_refresh(snapshot, previous, error=None):
    """Put actionable public-data details in the Actions summary and annotations."""
    def annotation(level, message):
        if os.environ.get("GITHUB_ACTIONS") == "true":
            escaped = str(message).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
            print(f"::{level}::{escaped}", flush=True)

    lines = ["## Price refresh", ""]
    if error is not None:
        detail = f"{type(error).__name__}: {error}"
        annotation("error", f"Price update failed; previous snapshot retained. {detail}")
        lines += ["**Failed — previous snapshot retained.**", "", "```text", detail.replace('`', "'"), "```"]
    else:
        lines += [f"**Saved a validated snapshot through {snapshot['common_close_date']}.**", "", f"Fetched at: {snapshot['fetched_at']}"]
        for warning in snapshot.get("warnings", []):
            lines.append(f"- {warning}")
            if "gaps in five-minute" not in warning:
                annotation("warning", warning)
    lines += ["", f"Previous common close: {previous.get('common_close_date', 'none')}", f"Previous fetch: {previous.get('fetched_at', 'none')}", "", "Incomplete current-day daily closes are flagged; invalid historical prices still block publication.", ""]
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        try:
            with Path(path).open('a') as summary:
                summary.write('\n'.join(lines))
        except OSError as report_error:
            print(f"Could not write Actions summary: {report_error}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="Reload two years instead of updating/rebasing recent observations")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "market.json")
    args = parser.parse_args()
    previous = {}
    try:
        funds = json.loads((ROOT / "config" / "funds.json").read_text())["funds"]
        previous = json.loads(args.output.read_text()) if args.output.exists() else {}
        snapshot = build_snapshot(funds, previous, full=args.full)
        atomic_write(args.output, snapshot)
    except Exception as error:
        print(f"Update failed; previous snapshot retained: {error}", file=sys.stderr)
        traceback.print_exc()
        report_refresh(None, previous, error)
        return 1
    report_refresh(snapshot, previous)
    print(f"Saved complete snapshot through {snapshot['common_close_date']} to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
