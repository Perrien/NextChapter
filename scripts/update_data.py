#!/usr/bin/env python3
"""Fetch public ticker data only. Atomic output retains the previous good snapshot."""
import argparse
import calendar
import datetime as dt
import json
import math
from pathlib import Path
import sys
import time
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
        raise ValueError(f"{symbol}: Yahoo returned no series")
    return result[0]


def daily_series(result, now):
    meta = result["meta"]
    if meta.get("currency") != "USD":
        raise ValueError("Only USD prices are supported")
    tz = ZoneInfo(meta["exchangeTimezoneName"])
    today = now.astimezone(tz).date().isoformat()
    session_end = meta.get("currentTradingPeriod", {}).get("regular", {}).get("end")
    quote = result["indicators"]["quote"][0]
    adjusted = result["indicators"].get("adjclose", [{}])[0].get("adjclose", [])
    rows = []
    for i, stamp in enumerate(result.get("timestamp", [])):
        date = dt.datetime.fromtimestamp(stamp, tz).date().isoformat()
        # ETF daily endpoints can include a partial current-session bar. Keep
        # those quotes in intraday data, not in completed daily history.
        if date == today and session_end and now.timestamp() < session_end:
            continue
        close = quote.get("close", [])[i]
        adj = adjusted[i] if i < len(adjusted) else None
        if not positive(close) or not positive(adj):
            raise ValueError(f"Invalid close/adjusted close on {date}")
        rows.append({"date": date, "close": round(close, int(meta.get("priceHint", 2))), "adjusted_close": adj})
    if not rows or any(a["date"] >= b["date"] for a, b in zip(rows, rows[1:])):
        raise ValueError("Empty, duplicate, or unsorted daily history")
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
    for symbol in symbols:
        saved = previous.get("series", {}).get(symbol)
        complete = full or saved is None
        result = fetcher(symbol, "2y" if complete else "1mo", "1d")
        rows = daily_series(result, now)
        if not complete:
            try:
                precision = int(result["meta"].get("priceHint", 2))
                old_rows = [{**row, "close": round(row["close"], precision)} for row in saved["daily"]]
                rows = merge_daily(old_rows, rows)
            except ValueError:
                result = fetcher(symbol, "2y", "1d")
                rows = daily_series(result, now)
                complete = True
        if len(rows) < 260:
            raise ValueError(f"{symbol}: insufficient history for the trailing-year calculation")
        meta = result["meta"]
        events = normalize_events(result.get("events", {}), meta["exchangeTimezoneName"])
        if saved and not complete:
            for kind, items in saved.get("events", {}).items():
                events[kind] = {**items, **events.get(kind, {})}
        series[symbol] = {"name": meta.get("longName") or meta.get("shortName") or symbol, "type": meta.get("instrumentType"), "currency": meta["currency"], "price_decimals": int(meta.get("priceHint", 2)), "timezone": meta["exchangeTimezoneName"], "daily": rows, "events": events, "intraday": []}
        print(f"Daily {symbol}: {len(rows)} observations, through {rows[-1]['date']}", flush=True)
        if delay:
            time.sleep(delay)
    warnings = []
    for symbol in proxies:
        result = fetcher(symbol, "5d", "5m")
        meta = result["meta"]
        tz = ZoneInfo(meta["exchangeTimezoneName"])
        if meta.get("dataGranularity") != "5m":
            raise ValueError(f"{symbol}: expected five-minute quotes")
        closes = result["indicators"]["quote"][0].get("close", [])
        rows = []
        for i, stamp in enumerate(result.get("timestamp", [])):
            if i >= len(closes) or not positive(closes[i]):
                continue
            date = dt.datetime.fromtimestamp(stamp, tz).date().isoformat()
            rows.append({"timestamp": stamp, "date": date, "close": closes[i]})
        if not rows:
            raise ValueError(f"{symbol}: no usable intraday quotes")
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="Reload two years instead of updating/rebasing recent observations")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "market.json")
    args = parser.parse_args()
    funds = json.loads((ROOT / "config" / "funds.json").read_text())["funds"]
    previous = json.loads(args.output.read_text()) if args.output.exists() else {}
    try:
        snapshot = build_snapshot(funds, previous, full=args.full)
        atomic_write(args.output, snapshot)
    except Exception as error:
        print(f"Update failed; previous snapshot retained: {error}", file=sys.stderr)
        return 1
    print(f"Saved complete snapshot through {snapshot['common_close_date']} to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
