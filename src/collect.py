"""
collect.py -- Raw data collection for the DSSG commodity -> jobless-claims project.

Pulls every raw series used in the project and caches it under data/raw/ as CSV,
together with a manifest.json that records, for each file: the source URL,
the UTC pull timestamp, the row count and the first/last observation dates.
The manifest is what the "Scraping / Collection Audit" section of the report
is built from, so nothing has to be typed by hand.

Sources
-------
FRED  (Federal Reserve Economic Data) -- keyless CSV endpoint
      https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES>
        ICSA         Initial Claims, weekly (week ending Saturday), persons, SA
        DCOILWTICO   WTI crude oil spot, daily, USD per barrel
        DHHNGSP      Henry Hub natural gas spot, daily, USD per MMBtu
        USREC        NBER recession indicator, monthly, 0/1   (control variable)
        PCOPPUSDM    Copper global price, monthly, USD per metric ton   (reference only)
        PIORECRUSDM  Iron ore global price, monthly, USD per metric ton (reference only)

Yahoo Finance via the `yfinance` package (fallback: Yahoo chart API with explicit
period1/period2 so that daily granularity is preserved over long ranges)
        HG=F   COMEX copper futures, continuous front month, USD per pound
        TIO=F  Iron ore 62% Fe CFR China (TSI) futures, USD per metric ton

Usage:  python src/collect.py            # pulls everything from START (1998-01-01)
        python src/collect.py --force    # re-download even if a cached file exists
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
START = "1998-01-01"

FRED_SERIES = {
    "ICSA":        "Initial Claims (weekly, SA, persons)",
    "DCOILWTICO":  "WTI crude oil spot (daily, USD/bbl)",
    "DHHNGSP":     "Henry Hub natural gas spot (daily, USD/MMBtu)",
    "USREC":       "NBER recession indicator (monthly, 0/1)",
    "PCOPPUSDM":   "Copper global price (monthly, USD/tonne) -- reference",
    "PIORECRUSDM": "Iron ore global price (monthly, USD/tonne) -- reference",
}
YF_TICKERS = {
    "HG=F":  "COMEX copper futures (daily, USD/lb)",
    "TIO=F": "Iron ore 62% Fe CFR China futures (daily, USD/tonne)",
}
UA = {"User-Agent": "Mozilla/5.0 (DSSG course project; data collection)"}


def fred_url(series: str) -> str:
    return f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"


def fetch_fred(series: str) -> pd.DataFrame:
    """Download one FRED series as a two-column frame: date, value.

    FRED writes '.' for days with no observation (holidays, market closures).
    Those are parsed to NaN here and dropped later during weekly aggregation.
    """
    # FRED answers the default python-requests agent instantly but stalls on
    # browser-style agents sent without full browser headers, so no UA here.
    r = requests.get(fred_url(series), timeout=60)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), na_values=["."])
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    return df[df["date"] >= START].reset_index(drop=True)


def fetch_yahoo_chart_api(ticker: str) -> pd.DataFrame:
    """Fallback: hit Yahoo's chart endpoint directly with explicit timestamps.

    Using range=max silently downgrades to monthly bars, so period1/period2 are
    passed explicitly to keep interval=1d honoured for the whole span.
    """
    p1 = int(dt.datetime.strptime(START, "%Y-%m-%d").timestamp())
    p2 = int(time.time())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={p1}&period2={p2}&interval=1d")
    r = requests.get(url, headers=UA, timeout=60)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame({
        "date": pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert(None).normalize(),
        "open": q["open"], "high": q["high"], "low": q["low"],
        "close": q["close"], "volume": q["volume"],
    })
    return df.dropna(subset=["close"]).reset_index(drop=True)


def fetch_yfinance(ticker: str) -> tuple[pd.DataFrame, str]:
    """Daily OHLCV via yfinance; falls back to the raw chart API if it fails/empties."""
    try:
        import yfinance as yf
        raw = yf.download(ticker, start=START, interval="1d", auto_adjust=False,
                          progress=False, threads=False)
        if raw is None or raw.empty:
            raise RuntimeError("yfinance returned an empty frame")
        if isinstance(raw.columns, pd.MultiIndex):          # yfinance >= 0.2.40 shape
            raw.columns = raw.columns.get_level_values(0)
        df = raw.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        df.index.name = "date"
        df = df.reset_index()
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
        df = df.dropna(subset=["close"]).reset_index(drop=True)
        return df, f"yfinance.download('{ticker}', start='{START}', interval='1d')"
    except Exception as e:                                   # noqa: BLE001
        print(f"  yfinance failed for {ticker} ({e}); using Yahoo chart API fallback")
        return fetch_yahoo_chart_api(ticker), (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
            f"?period1=<{START}>&period2=<now>&interval=1d")


def main(force: bool = False) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    manifest_path = RAW / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def record(name, df, source, desc, freq):
        manifest[name] = {
            "description": desc, "source": source, "frequency": freq,
            "pulled_at_utc": now, "rows": int(len(df)),
            "first_date": str(df["date"].min().date()),
            "last_date": str(df["date"].max().date()),
            "file": f"data/raw/{name}.csv",
        }

    for series, desc in FRED_SERIES.items():
        out = RAW / f"{series}.csv"
        if out.exists() and not force:
            print(f"cached  {series}")
            continue
        print(f"FRED    {series} ...", end=" ", flush=True)
        df = fetch_fred(series)
        df.to_csv(out, index=False)
        freq = {"ICSA": "weekly", "USREC": "monthly", "PCOPPUSDM": "monthly",
                "PIORECRUSDM": "monthly"}.get(series, "daily")
        record(series, df, fred_url(series), desc, freq)
        print(f"{len(df)} rows, {df['date'].min().date()} -> {df['date'].max().date()}")

    for ticker, desc in YF_TICKERS.items():
        name = ticker.replace("=", "_")
        out = RAW / f"{name}.csv"
        if out.exists() and not force:
            print(f"cached  {ticker}")
            continue
        print(f"Yahoo   {ticker} ...", end=" ", flush=True)
        df, source = fetch_yfinance(ticker)
        df.to_csv(out, index=False)
        record(name, df, source, desc, "daily")
        print(f"{len(df)} rows, {df['date'].min().date()} -> {df['date'].max().date()}")

    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\nmanifest written: {manifest_path} ({len(manifest)} files)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="re-download cached files")
    args = ap.parse_args()
    main(force=args.force)
