"""
build_master.py -- Build the weekly master analytical dataset.

Observational unit: 1 row = 1 week ending Saturday, matching the week-ending
convention of the US Initial Claims series (ICSA). All daily commodity series
are aggregated to the same Sunday-Saturday weeks, monthly series are
forward-filled onto those weeks, and lagged / volatility / dummy / scaled
features are added. Output:

    data/processed/master_weekly.csv
    data/processed/data_dictionary.csv

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
SCALE_COLS = ["icsa", "log_icsa", "oil_mean", "gas_mean", "copper_mean", "iron_mean"]

COMMODITIES = {
    #  key      file            value col  unit            label
    "oil":    ("DCOILWTICO.csv", "value", "USD/barrel",   "WTI crude oil spot"),
    "gas":    ("DHHNGSP.csv",    "value", "USD/MMBtu",    "Henry Hub natural gas spot"),
    "copper": ("HG_F.csv",       "close", "USD/tonne",    "COMEX copper futures (HG=F)"),
    "iron":   ("TIO_F.csv",      "close", "USD/tonne",    "Iron ore 62% Fe futures (TIO=F)"),
}


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
        {key}_mean    mean of daily prices             (level feature)
        {key}_close   last daily price in the week
        {key}_n_days  number of trading days observed  (holiday weeks have fewer)
        {key}_vol_w   std of daily log returns inside the week  (within-week volatility)
        {key}_vol_4w  std of daily log returns over the trailing 20 trading days,
                      taken at the last day of the week (4-week rolling volatility)
    """
    # WTI printed a negative settlement on 2020-04-20 (-37.63 USD/bbl); the log
    # return is undefined there, so that single day is excluded from the
    # return-based volatility features only. Price levels keep the true value.
    logret = np.log(daily.where(daily > 0)).diff()
    vol20 = logret.rolling(20, min_periods=10).std()
    wk = pd.DataFrame({
        f"{key}_mean":   daily.resample("W-SAT").mean(),
        f"{key}_close":  daily.resample("W-SAT").last(),
        f"{key}_n_days": daily.resample("W-SAT").count(),
        f"{key}_vol_w":  logret.resample("W-SAT").std(),
        f"{key}_vol_4w": vol20.resample("W-SAT").last(),
    })
    # weeks with zero trading days (e.g. exchange closures) are genuinely missing
    wk.loc[wk[f"{key}_n_days"] == 0, :] = np.nan
    wk[f"{key}_n_days"] = wk[f"{key}_n_days"].fillna(0).astype(int)
    return wk


def add_commodity_features(wk: pd.DataFrame, key: str) -> pd.DataFrame:
    """Percentage change, log level and the 1..MAX_LAG lagged percentage changes."""
    mean = wk[f"{key}_mean"]
    pct = mean.pct_change() * 100                                    # % change of weekly mean
    new = {f"{key}_log_mean": np.log(mean.where(mean > 0)), f"{key}_pct_1w": pct}
    for k in range(1, MAX_LAG + 1):
        new[f"{key}_pct_lag{k}"] = pct.shift(k)
    return pd.concat([wk, pd.DataFrame(new, index=wk.index)], axis=1)


# ----------------------------------------------------------------------------- master
def build_master() -> pd.DataFrame:
    icsa = load_icsa()
    master = icsa.to_frame()
    master["log_icsa"] = np.log(master["icsa"])
    master["icsa_pct_chg_1w"] = master["icsa"].pct_change() * 100
    spike_cut = master["icsa_pct_chg_1w"].quantile(0.90)
    master["icsa_spike"] = (master["icsa_pct_chg_1w"] >= spike_cut).astype(int)

    for key in COMMODITIES:
        wk = weekly_from_daily(load_daily(key), key)
        wk = add_commodity_features(wk, key)
        master = master.join(wk, how="left")            # ICSA weeks define the sample

    # --- controls and dummy indicators -------------------------------------------------
    usrec = load_usrec()
    month_start = master.index.to_period("M").to_timestamp()
    master["usrec"] = usrec.reindex(month_start).ffill().to_numpy().astype(int)
    q = master.index.quarter
    for i in (2, 3, 4):
        master[f"q{i}"] = (q == i).astype(int)           # Q1 is the reference category
    master["covid_period"] = ((master.index >= COVID[0]) & (master.index <= COVID[1])).astype(int)
    master["copper_avail"] = master["copper_mean"].notna().astype(int)
    master["iron_avail"] = master["iron_mean"].notna().astype(int)

    # --- scaled copies of the key continuous variables ---------------------------------
    # Full-sample statistics are used here for the EDA; for modelling the scaler must be
    # fitted on the training window only (documented in the report).
    scaled = {}
    for col in SCALE_COLS:
        x = master[col]
        scaled[f"{col}_z"] = (x - x.mean()) / x.std(ddof=1)
        scaled[f"{col}_mm"] = (x - x.min()) / (x.max() - x.min())
    master = pd.concat([master, pd.DataFrame(scaled, index=master.index)], axis=1)

    master.index.name = "week_ending"
    master.attrs["spike_cut_pct"] = float(spike_cut)
    return master


def spike_threshold(master: pd.DataFrame) -> float:
    """90th percentile of weekly % change in claims -- the cut used for icsa_spike."""
    return float(master["icsa_pct_chg_1w"].quantile(0.90))


# ----------------------------------------------------------------------------- dictionary
def data_dictionary(master: pd.DataFrame) -> pd.DataFrame:
    rows = [
        ("week_ending", "Saturday that ends the Sun-Sat week (ICSA reference week)", "date", "FRED ICSA", "key"),
        ("icsa", "Initial unemployment insurance claims, seasonally adjusted", "persons/week", "FRED ICSA", "target"),
        ("log_icsa", "Natural log of icsa (variance-stabilising transform)", "log(persons)", "derived", "target"),
        ("icsa_pct_chg_1w", "Week-over-week % change in icsa", "%", "derived", "target"),
        ("icsa_spike", "1 if icsa_pct_chg_1w is in the top decile of the sample", "0/1", "derived", "target (binary)"),
    ]
    for key, (_, _, unit, label) in COMMODITIES.items():
        rows += [
            (f"{key}_mean", f"{label}: mean of daily prices in the week", unit, "FRED/Yahoo", "predictor (level)"),
            (f"{key}_close", f"{label}: last daily price in the week", unit, "FRED/Yahoo", "predictor (level)"),
            (f"{key}_n_days", f"{label}: trading days observed in the week", "days", "derived", "quality flag"),
            (f"{key}_vol_w", f"{label}: std of daily log returns within the week", "log-return sd", "derived", "predictor (volatility)"),
            (f"{key}_vol_4w", f"{label}: std of daily log returns over trailing 20 trading days", "log-return sd", "derived", "predictor (volatility)"),
            (f"{key}_log_mean", f"log({key}_mean)", f"log({unit})", "derived", "predictor (level)"),
            (f"{key}_pct_1w", f"{label}: week-over-week % change of weekly mean", "%", "derived", "predictor (shock)"),
            (f"{key}_pct_lag1..{MAX_LAG}", f"{key}_pct_1w shifted k weeks back (k=1..{MAX_LAG})", "%", "derived", "predictor (lagged shock)"),
        ]
    rows += [
        ("usrec", "NBER recession month indicator, forward-filled to weeks", "0/1", "FRED USREC", "control (dummy)"),
        ("q2, q3, q4", "Calendar-quarter dummies (Q1 reference)", "0/1", "derived", "control (dummy)"),
        ("covid_period", "1 for weeks Mar-Dec 2020", "0/1", "derived", "control (dummy)"),
        ("copper_avail", "1 if copper futures data exist that week (from 2000-09)", "0/1", "derived", "availability flag"),
        ("iron_avail", "1 if iron ore futures data exist that week (from 2010-10)", "0/1", "derived", "availability flag"),
        ("*_z", "z-score standardised copy (full-sample mean/sd)", "sd units", "derived", "scaled"),
        ("*_mm", "min-max scaled copy to [0, 1] (full-sample min/max)", "unitless", "derived", "scaled"),
    ]
    return pd.DataFrame(rows, columns=["column", "description", "unit", "source", "role"])


def main() -> None:
    PROC.mkdir(parents=True, exist_ok=True)
    master = build_master()

    # --- sanity checks -----------------------------------------------------------------
    assert master.index.is_monotonic_increasing and master.index.is_unique
    assert master.index.min() == pd.Timestamp("1998-01-03")
    assert master["icsa"].notna().all(), "target must never be missing"
    assert master.loc[:"2000-08-26", "copper_mean"].isna().all()
    assert master.loc["2000-09-09":, "copper_mean"].notna().all()
    assert master.loc[:"2010-10-09", "iron_mean"].isna().all()
    assert master.loc["2010-10-23":, "iron_mean"].notna().mean() > 0.99

    master.to_csv(PROC / "master_weekly.csv", float_format="%.6f")
    data_dictionary(master).to_csv(PROC / "data_dictionary.csv", index=False)
    print(f"master: {master.shape[0]} weeks x {master.shape[1]} columns, "
          f"{master.index.min().date()} -> {master.index.max().date()}")
    print(f"spike threshold (90th pct of weekly % change): {spike_threshold(master):.2f}%")
    print(master.isna().mean().mul(100).round(1).loc[
        ["oil_mean", "gas_mean", "copper_mean", "iron_mean", "usrec"]].to_string())


if __name__ == "__main__":
    main()
