"""
build_master.py -- Build the weekly master analytical dataset.

Observational unit: 1 row = 1 week ending Saturday, matching the week-ending
convention of the US Initial Claims series (ICSA). All daily commodity series
are aggregated to the same Sunday-Saturday weeks, the monthly recession flag is
forward-filled onto those weeks, and the features named in the project proposal
are added: base weekly price, weekly percentage price shock and 4-week
volatility per commodity. Output:

    data/processed/master_weekly.csv       (17 columns + week_ending index)
    data/processed/data_dictionary.csv

Lagged shocks ({c}_pct_lag1..16, the proposal's exploratory lag window) are NOT
stored; call add_lags(master) at analysis / model time to create them.

The functions here are imported by the notebook so every number in the
report is produced by exactly the same code path.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"

LB_PER_TONNE = 2204.62          # COMEX copper is quoted in USD per pound
MAX_LAG = 16                    # exploratory lag window from the proposal
COVID = ("2020-03-01", "2020-12-31")

COMMODITIES = {
    #  key      file            value col  unit            label
    "oil":    ("DCOILWTICO.csv", "value", "USD/barrel",   "WTI crude oil spot"),
    "gas":    ("DHHNGSP.csv",    "value", "USD/MMBtu",    "Henry Hub natural gas spot"),
    "copper": ("HG_F.csv",       "close", "USD/tonne",    "COMEX copper futures (HG=F)"),
    "iron":   ("TIO_F.csv",      "close", "USD/tonne",    "Iron ore 62% Fe futures (TIO=F)"),
}

COLUMN_ORDER = (["icsa", "log_icsa", "icsa_pct_chg_1w"]
                + [f"{k}_{f}" for k in COMMODITIES for f in ("mean", "pct_1w", "vol_4w")]
                + ["usrec", "covid_period"])


# ----------------------------------------------------------------------------- loaders
def load_daily(key: str) -> pd.Series:
    """Daily price series for one commodity, NaN rows (FRED '.' holidays) dropped."""
    fname, col, _, _ = COMMODITIES[key]
    df = pd.read_csv(RAW / fname, parse_dates=["date"])
    s = df.set_index("date")[col].astype(float).dropna().sort_index()
    if key == "copper":
        s = s * LB_PER_TONNE               # USD/lb -> USD/tonne, comparable with FRED PCOPPUSDM
    return s.rename(key)


def load_icsa() -> pd.Series:
    df = pd.read_csv(RAW / "ICSA.csv", parse_dates=["date"])
    s = df.set_index("date")["value"].astype(float).sort_index().rename("icsa")
    assert (s.index.dayofweek == 5).all(), "ICSA dates are expected to be Saturdays"
    return s


def load_usrec() -> pd.Series:
    df = pd.read_csv(RAW / "USREC.csv", parse_dates=["date"])
    return df.set_index("date")["value"].astype(int).sort_index().rename("usrec")


# ----------------------------------------------------------------------------- aggregation
def weekly_from_daily(daily: pd.Series, key: str) -> pd.DataFrame:
    """Collapse a daily price series to Sunday-Saturday weeks (label = Saturday).

    Returns, per week:
        {key}_mean    mean of daily prices in the week      (base weekly price)
        {key}_vol_4w  std of daily log returns over the trailing 20 trading days,
                      taken at the last day of the week      (4-week rolling volatility)
    Weeks with no trading day at all (exchange closures) are set to NaN.
    """
    # WTI printed a negative settlement on 2020-04-20 (-37.63 USD/bbl); the log
    # return is undefined there, so that single day is excluded from the
    # return-based volatility feature only. Price levels keep the true value.
    logret = np.log(daily.where(daily > 0)).diff()
    vol20 = logret.rolling(20, min_periods=10).std()
    wk = pd.DataFrame({
        f"{key}_mean":   daily.resample("W-SAT").mean(),
        f"{key}_vol_4w": vol20.resample("W-SAT").last(),
    })
    n_days = daily.resample("W-SAT").count()
    wk.loc[n_days == 0, :] = np.nan
    return wk


def add_commodity_features(wk: pd.DataFrame, key: str) -> pd.DataFrame:
    """Weekly percentage price shock: % change of the weekly mean price."""
    wk[f"{key}_pct_1w"] = wk[f"{key}_mean"].pct_change() * 100
    return wk


def add_lags(df: pd.DataFrame, max_lag: int = MAX_LAG, keys=tuple(COMMODITIES)) -> pd.DataFrame:
    """Return a copy of df with {key}_pct_lag1..max_lag added for each commodity.

    {key}_pct_lagk at week t is the percentage price shock that happened k weeks
    earlier. Created on demand so the stored master stays narrow; the modelling
    stage keeps only the strongest lags per commodity, as the proposal states.
    """
    lags = {f"{k}_pct_lag{j}": df[f"{k}_pct_1w"].shift(j) for k in keys for j in range(1, max_lag + 1)}
    return pd.concat([df, pd.DataFrame(lags, index=df.index)], axis=1)


# ----------------------------------------------------------------------------- master
def build_master() -> pd.DataFrame:
    icsa = load_icsa()
    master = icsa.to_frame()
    master["log_icsa"] = np.log(master["icsa"])
    master["icsa_pct_chg_1w"] = master["icsa"].pct_change() * 100

    for key in COMMODITIES:
        wk = add_commodity_features(weekly_from_daily(load_daily(key), key), key)
        master = master.join(wk, how="left")            # ICSA weeks define the sample

    # --- controls (dummy indicators) ---------------------------------------------------
    usrec = load_usrec()
    month_start = master.index.to_period("M").to_timestamp()
    master["usrec"] = usrec.reindex(month_start).ffill().to_numpy().astype(int)
    master["covid_period"] = ((master.index >= COVID[0]) & (master.index <= COVID[1])).astype(int)

    master = master[COLUMN_ORDER]
    master.index.name = "week_ending"
    return master


def spike_threshold(master: pd.DataFrame) -> float:
    """90th percentile of the weekly % change in claims -- the cut used to define a 'claims spike' in the EDA."""
    return float(master["icsa_pct_chg_1w"].quantile(0.90))


# ----------------------------------------------------------------------------- dictionary
def data_dictionary(master: pd.DataFrame) -> pd.DataFrame:
    rows = [
        ("week_ending", "Saturday that ends the Sun-Sat week (ICSA reference week)", "date", "FRED ICSA", "key"),
        ("icsa", "Initial unemployment insurance claims, seasonally adjusted", "persons/week", "FRED ICSA", "target"),
        ("log_icsa", "Natural log of icsa (variance-stabilising transform)", "log(persons)", "derived", "target (model scale)"),
        ("icsa_pct_chg_1w", "Week-over-week % change in icsa", "%", "derived", "target (change)"),
    ]
    for key, (_, _, unit, label) in COMMODITIES.items():
        rows += [
            (f"{key}_mean", f"{label}: mean of daily prices in the week (base weekly price)", unit, "FRED/Yahoo", "predictor (level)"),
            (f"{key}_pct_1w", f"{label}: week-over-week % change of weekly mean (price shock)", "%", "derived", "predictor (shock)"),
            (f"{key}_vol_4w", f"{label}: std of daily log returns over trailing 20 trading days", "log-return sd", "derived", "predictor (volatility)"),
        ]
    rows += [
        ("usrec", "NBER recession month indicator, forward-filled to weeks", "0/1", "FRED USREC", "control (dummy)"),
        ("covid_period", "1 for weeks Mar-Dec 2020", "0/1", "derived", "control (dummy)"),
        (f"{{c}}_pct_lag1..{MAX_LAG}", "NOT stored: created by add_lags(); {c}_pct_1w shifted k weeks back", "%", "derived", "predictor (lagged shock)"),
    ]
    return pd.DataFrame(rows, columns=["column", "description", "unit", "source", "role"])


def main() -> None:
    PROC.mkdir(parents=True, exist_ok=True)
    master = build_master()

    # --- sanity checks -----------------------------------------------------------------
    assert master.index.is_monotonic_increasing and master.index.is_unique
    assert master.index.min() == pd.Timestamp("1998-01-03")
    assert master.shape[1] == 17, master.shape
    assert master["icsa"].notna().all(), "target must never be missing"
    assert master.loc[:"2000-08-26", "copper_mean"].isna().all()
    assert master.loc["2000-09-09":, "copper_mean"].notna().all()
    assert master.loc[:"2010-10-09", "iron_mean"].isna().all()
    assert master.loc["2010-10-23":, "iron_mean"].notna().mean() > 0.99

    master.to_csv(PROC / "master_weekly.csv", float_format="%.6f")
    data_dictionary(master).to_csv(PROC / "data_dictionary.csv", index=False)
    print(f"master: {master.shape[0]} weeks x {master.shape[1]} columns, "
          f"{master.index.min().date()} -> {master.index.max().date()}")
    print(f"with lags on demand: {add_lags(master).shape[1]} columns")
    print(master.isna().sum().loc[["oil_mean", "gas_mean", "copper_mean", "iron_mean"]].to_string())


if __name__ == "__main__":
    main()
