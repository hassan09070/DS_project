"""
make_notebook.py -- Generate Milestone02_Analysis.ipynb programmatically.

The notebook is assembled from (markdown, code) cells here so that the
narrative and code stay in one reviewable place; it is then executed with
`jupyter nbconvert --execute` so every output in the committed notebook is real.
"""
import nbformat as nbf
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
nb = nbf.v4.new_notebook()
cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s.strip("\n")))
code = lambda s: cells.append(nbf.v4.new_code_cell(s.strip("\n")))

# =============================================================================
md(r"""
# **Milestone 02: Data Preparation, EDA and Hypothesis Report**
## Commodity price shocks as an early-warning signal for US initial jobless claims

**Course:** Data Science for Social Good  
**Team:** Rana Mohammad Sarib Khan (rk09083, Social Development & Policy, CS minor) · Abdullah Ahmed (aa09303, Computer Engineering) · Hassan Shahzad (ms09070, Computer Science)  
**SDG:** 8 – Decent Work and Economic Growth, Target 8.5

This notebook is the executable companion to the Milestone 02 PDF (Draft Sections II and III of the manuscript).
Every table and figure in the PDF is produced here and written to `data/processed/tables/` and `figures/`.
The data pipeline lives in `src/collect.py` (raw pulls) and `src/build_master.py` (weekly master dataset) and is
imported below so the notebook and the scripts can never disagree.
""")

code(r"""
import sys, json, inspect, warnings
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns
from scipy import stats

warnings.filterwarnings("ignore", category=FutureWarning)
ROOT = Path.cwd() if (Path.cwd() / "src").exists() else Path.cwd().parent
sys.path.insert(0, str(ROOT / "src"))
from build_master import (build_master, data_dictionary, weekly_from_daily, add_commodity_features,
                          load_daily, load_icsa, COMMODITIES, MAX_LAG, COVID, spike_threshold)

TABLES = ROOT / "data" / "processed" / "tables"; TABLES.mkdir(parents=True, exist_ok=True)
FIGS = ROOT / "figures"; FIGS.mkdir(exist_ok=True)
pd.set_option("display.width", 160); pd.set_option("display.max_columns", 40); pd.set_option("display.precision", 3)

# --- plotting conventions used for every figure ---------------------------------------
# Fixed categorical hue per commodity (never re-assigned between figures); claims in near-black ink;
# recessions in neutral gray. Palette validated for colour-vision deficiency (adjacent-pair ΔE ≥ 8).
COLORS = {"oil": "#2a78d6", "gas": "#eb6834", "copper": "#1baf7a", "iron": "#eda100",
          "claims": "#0b0b0b", "rec": "#d9d8d3", "muted": "#52514e"}
LABELS = {"oil": "WTI crude oil", "gas": "Henry Hub natural gas", "copper": "Copper (COMEX)", "iron": "Iron ore 62% Fe"}
UNITS  = {k: v[2] for k, v in COMMODITIES.items()}
mpl.rcParams.update({"figure.dpi": 110, "savefig.dpi": 200, "font.size": 10, "axes.titlesize": 11,
                     "axes.titleweight": "semibold", "axes.labelsize": 10, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.grid": True, "grid.color": "#e6e5e1",
                     "grid.linewidth": 0.6, "axes.edgecolor": "#b5b4ae", "legend.frameon": False})
KEYS = list(COMMODITIES)
print("pandas", pd.__version__, "| project root:", ROOT)
""")

# =============================================================================
md(r"""
# **Section 1: Project Alignment & Master Dataset Inventory**

## 1.1 Team metadata and problem summary

| Member | ID | Disciplinary background |
|---|---|---|
| Rana Mohammad Sarib Khan | rk09083 | Social Development & Policy, CS minor |
| Abdullah Ahmed | aa09303 | Computer Engineering |
| Hassan Shahzad | ms09070 | Computer Science |

**Project title.** *Commodity Price Shocks as an Early-Warning Signal for US Initial Jobless Claims.*

**Primary social research question.** Do sudden changes (and volatility) in the prices of core energy
(crude oil, natural gas) and industrial-metal (copper, iron ore) commodities predict increases in US weekly
initial unemployment-insurance claims, and with what lag? An answer lets policymakers pre-position safety-net
resources before official labour statistics confirm a layoff wave (SDG 8.5, full and productive employment).

## 1.2 Master dataset overview
The master dataset is built by `src/build_master.py`. Running it here rebuilds it from the cached raw files.
""")

code(r"""
master = build_master()
master.to_csv(ROOT / "data" / "processed" / "master_weekly.csv", float_format="%.6f")
manifest = json.loads((ROOT / "data" / "raw" / "manifest.json").read_text())

overview = pd.DataFrame({
    "Item": ["Observations (rows)", "Variables (columns)", "Observational unit", "Time span",
             "Target variable", "Commodity predictors", "Controls / dummies", "Raw sources"],
    "Value": [f"{master.shape[0]:,} weeks", f"{master.shape[1]}",
              "1 row = 1 calendar week ending Saturday (the US Department of Labor's 'week ending' convention for initial claims)",
              f"{master.index.min().date()} to {master.index.max().date()}",
              "icsa (weekly initial claims, persons) and its derived log / % change / spike indicator",
              "4 commodities × (weekly mean, close, within-week and 4-week volatility, % change, 16 lagged % changes)",
              "NBER recession (usrec), quarter dummies, COVID period, data-availability flags",
              "FRED API (6 series), Yahoo Finance via yfinance (2 futures tickers)"]})
overview.to_csv(TABLES / "t01_master_overview.csv", index=False)
display(overview.style.hide(axis="index").set_properties(**{"text-align": "left"}))

sources = (pd.DataFrame(manifest).T
           .loc[:, ["description", "frequency", "rows", "first_date", "last_date", "source"]]
           .rename_axis("series").reset_index())
sources.to_csv(TABLES / "t02_sources.csv", index=False)
display(sources.drop(columns="source"))
""")

md(r"""
### Interpretation
The master table has **1,500 weekly observations and 115 variables**, covering every week from 3 January 1998 to
the latest published claims week. The unit of observation is the Department of Labor's reference week (Sunday to
Saturday), so the target is never resampled; every other series is brought *to* that grid. Eight raw files feed
the table: six FRED series (claims, two daily spot prices, the monthly NBER recession flag, and the two monthly
metal benchmarks kept for reference) and two daily futures series from Yahoo Finance for the metals, following the
Milestone 01 source-selection test. The 115 columns are dominated by the exploratory 16-week lag block
(4 commodities × 16 lags = 64 columns); the plan is to retain only the strongest lags per commodity for modelling.
""")

# =============================================================================
md(r"""
# **Section 2: Data Ingestion, Cleaning & Structural Readiness**

## 2.1 Scraping / collection audit
`src/collect.py` pulls every series programmatically and records provenance in `data/raw/manifest.json`.

* **FRED.** Each series is fetched from the keyless CSV endpoint
  `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES>`. FRED writes a `.` for days with no observation
  (holidays, market closures); these are parsed to `NaN` at load time. One practical finding: FRED stalls on
  browser-style `User-Agent` strings sent without full browser headers, so the request is made with the default
  `python-requests` agent.
* **Yahoo Finance.** `yfinance.download(ticker, start="1998-01-01", interval="1d")` for `HG=F` (COMEX copper,
  USD/lb) and `TIO=F` (iron ore 62% Fe CFR China, USD/tonne). A fallback hits the chart endpoint directly with explicit
  `period1`/`period2` timestamps, because `range=max` silently downgrades the response to monthly bars.
* **Coverage check.** Querying `TIO=F` for 2007–2010 returns `{"error": {"code": "Bad Request",
  "description": "Data doesn't exist for startDate = 1167591600, endDate = 1285873200"}}`: the contract was listed on
  14 October 2010, so iron ore is **structurally missing** before then. Likewise copper futures begin on 30 August
  2000. These gaps are kept as `NaN` rather than back-filled (see 2.3).
""")

code(r"""
# First rows of each raw file, exactly as cached -- the audit trail for the collection step
for name, meta in manifest.items():
    df = pd.read_csv(ROOT / meta["file"], nrows=2)
    print(f"{name:<12} {meta['frequency']:<8} {meta['rows']:>5} rows  {meta['first_date']} -> {meta['last_date']}   "
          f"pulled {meta['pulled_at_utc']}")
    print("   ", df.to_dict("records")[0])
""")

md(r"""
## 2.2 Data alignment and structural organisation
The raw files arrive at three frequencies (weekly, daily, monthly) and two different week conventions.
The reshaping below produces one modelling-ready table keyed on the claims reference week:

1. **Daily → weekly (down-sampling).** Each daily price series is grouped into Sunday–Saturday bins labelled by
   the Saturday (`resample("W-SAT")`). Per week we keep the *mean* price (level), the *last* price (close),
   the number of trading days observed, the standard deviation of daily log returns inside the week (within-week
   volatility), and a trailing 20-trading-day volatility sampled on the last day of the week.
2. **Monthly → weekly (up-sampling).** The NBER recession flag is forward-filled from the month start to every week
   in that month.
3. **Join.** All weekly frames are left-joined onto the claims index, so the claims weeks define the sample and
   no commodity week without a claims observation enters the table.
4. **Feature construction.** Week-over-week percentage change of the weekly mean, the natural log of the level,
   and lags 1–16 of the percentage change per commodity.

The functions that do this are printed below from `src/build_master.py`.
""")

code(r"""
print(inspect.getsource(weekly_from_daily))
print(inspect.getsource(add_commodity_features))
""")

code(r"""
# Worked example of the daily -> weekly collapse for one week, so the aggregation is auditable.
# The week ending 2020-04-25 contains the only negative WTI settlement in history (2020-04-20).
oil_daily = load_daily("oil")
example_week = oil_daily["2020-04-19":"2020-04-25"]
print("Daily WTI prices, week ending 2020-04-25 (USD/barrel):")
print(example_week.to_string())
print("\nWeekly row produced for that week:")
display(master.loc[["2020-04-25"], ["oil_mean", "oil_close", "oil_n_days", "oil_vol_w", "oil_vol_4w", "oil_pct_1w"]])

# Alignment check: every master index date is a Saturday and spacing is exactly 7 days
print("All Saturdays:", (master.index.dayofweek == 5).all(),
      "| unique 7-day spacing:", master.index.to_series().diff().dropna().unique())
""")

md(r"""
### Interpretation
The worked example shows the collapse from five trading days to a single row and makes the choice of
*mean* rather than *close* visible: the week of 25 April 2020 closes at 15.99 USD/bbl, but its mean is 3.32 USD/bbl
because of the −37.63 USD/bbl print on 20 April. The weekly mean is retained as the level feature because it is what a
business paying for inputs over the week actually faced; the close is kept as a secondary column. The log return
on the negative day is undefined, so that single observation is excluded from the return-based volatility
features only, never from the price level. The index passes both structural checks (all Saturdays, uniform 7-day spacing).
""")

md(r"""
## 2.3 Cleaning and missing-data strategy
""")

code(r"""
miss = pd.DataFrame({"missing_n": master.isna().sum(), "missing_pct": master.isna().mean() * 100})
miss["missing_pct"] = miss["missing_pct"].round(2)

# compact view: the lag block is summarised by its range instead of 64 separate rows
core = [c for c in master.columns if "_lag" not in c and not c.endswith(("_z", "_mm"))]
lag_summary = pd.DataFrame({k: miss.loc[[f"{k}_pct_lag{i}" for i in range(1, MAX_LAG + 1)], "missing_pct"].agg(["min", "max"])
                            for k in KEYS}).T.rename(columns={"min": "lag1 missing %", "max": f"lag{MAX_LAG} missing %"})
miss.to_csv(TABLES / "t03_missing_all_columns.csv")
display(miss.loc[core].T)
print("\nLag block, % missing from lag 1 to lag 16:")
display(lag_summary)

# where is the missingness in time?  share of weeks per year with a missing weekly mean
by_year = (master[[f"{k}_mean" for k in KEYS]].isna()
           .groupby(master.index.year).mean().mul(100).round(0).astype(int))
by_year.columns = KEYS
by_year.index.name = "year"
by_year.to_csv(TABLES / "t04_missing_by_year.csv")
display(by_year.T)
""")

md(r"""
### Missing-data findings and handling rationale

| Variable group | Missing | Mechanism | Decision |
|---|---|---|---|
| `icsa` and all target columns | 0 % (1 % for the first-difference, by construction) | — | Never imputed. |
| `oil_*` | 0.3 % (4 weeks in 1998–99) | Sparse early FRED daily coverage | Left `NaN`. |
| `gas_*` | 8.1 % (121 weeks, all before April 2007) | FRED's Henry Hub daily series is intermittent before 2007 (roughly one trading day in four is recorded) | Left `NaN`; documented as source sparsity. |
| `copper_*` | 9.3 % (all weeks before 2000-09-02) | **Structural:** COMEX copper futures history on Yahoo begins 30 Aug 2000 | Left `NaN`; `copper_avail` flag added. |
| `iron_*` | 44.5 % (all weeks before 2010-10-16) | **Structural:** TIO=F listed 14 Oct 2010; the API returns "Data doesn't exist" for earlier dates | Left `NaN`; `iron_avail` flag added. |
| `*_pct_lagk` | adds exactly *k* more weeks per lag | Shifting | Expected; disappears once lags are pruned. |
| `usrec`, dummies | 0 % | — | — |

**Why no imputation.** Mean/median imputation of a price level that did not exist would inject a constant into a
time series and destroy the very week-to-week variation the project studies; time-series interpolation across a
*ten-year* hole (iron ore) would be fabrication, not estimation. Back-filling iron ore from FRED's monthly benchmark
was considered and rejected on two grounds: (i) before 2010 iron ore was priced on *annual* contracts, so the FRED
series is a flat step function (36.63 USD/t for all of 2007) carrying no weekly information, and (ii) mixing two
sources in one column contradicts the single-source decision made in Milestone 01. The target is complete, so no
rows are dropped from the master table; instead, each model will use **listwise deletion on the columns it actually
uses**. A model with copper will therefore train on 2000–2026 (1,361 weeks) and a model with iron ore on 2010–2026
(833 weeks).

**Selection bias.** Listwise deletion is harmless only if missingness is unrelated to the outcome. Here it is
related to *time*, which is in turn related to the outcome: any specification that includes iron ore sees neither
the 2001 recession nor the 2008–09 financial crisis, the two largest claims episodes other than COVID-19. Such a
model would be estimated on a sample with a narrower range of labour-market stress and could understate effects
that only materialise in deep recessions. We flag this explicitly and plan to report metal-based models both with
and without iron ore. The pre-2007 gas sparsity has the opposite character: missing weeks are scattered across
ordinary years, so their omission is closer to random.
""")

md(r"""
## 2.4 Transformations and encoding
""")

code(r"""
# --- Feature rescaling: log transform for heavy right skew ---------------------------------
skew_tbl = pd.DataFrame({
    "variable": ["icsa"] + [f"{k}_mean" for k in KEYS],
    "skew (raw)": [stats.skew(master["icsa"])] + [stats.skew(master[f"{k}_mean"].dropna()) for k in KEYS],
    "skew (log)": [stats.skew(master["log_icsa"])] + [stats.skew(master[f"{k}_log_mean"].dropna()) for k in KEYS],
}).round(2)
skew_tbl.to_csv(TABLES / "t05_log_transform_skew.csv", index=False)
display(skew_tbl)
""")

md(r"""
### Interpretation: log transformation
Initial claims are extremely right-skewed (skewness 11.2): only 50 of 1,500 weeks exceed 700,000, but the
pandemic weeks reach 6.1 million. `log_icsa` reduces skewness to 2.3 and is the response scale we intend to model;
a one-unit change in log claims is a constant *percentage* change, which is also how policymakers talk about
layoff waves. Natural gas is the only commodity with material right skew (1.75, driven by the 2005 and 2022 spikes),
and the log reduces it to 0.55. Crude oil, copper and iron ore are already close to symmetric in levels (0.11,
0.01, 0.47) and the log *over*-corrects oil and copper into moderate left skew (−0.9, −1.1), so for those three the
raw level is the primary feature and the log copy is kept only for elasticity-style specifications.
""")

code(r"""
# --- Scaling: z-score standardisation and Min-Max normalisation -------------------------
scale_cols = ["icsa", "log_icsa", "oil_mean", "gas_mean", "copper_mean", "iron_mean"]
scale_demo = pd.concat({
    "raw":  master[scale_cols].describe().loc[["mean", "std", "min", "max"]],
    "z":    master[[c + "_z" for c in scale_cols]].set_axis(scale_cols, axis=1).describe().loc[["mean", "std", "min", "max"]],
    "minmax": master[[c + "_mm" for c in scale_cols]].set_axis(scale_cols, axis=1).describe().loc[["mean", "std", "min", "max"]],
}, axis=0).round(3)
scale_demo.to_csv(TABLES / "t06_scaling_summary.csv")
display(scale_demo)
""")

md(r"""
### Interpretation: scaling
Both scaled copies are stored alongside the raw columns (`*_z`, `*_mm`). Standardisation is the default for the
regression-type models planned (coefficients become comparable across commodities measured in dollars per barrel,
per MMBtu and per tonne). Min-Max copies are kept for tree-free neural baselines, which prefer bounded inputs.
Because the min, max, mean and standard deviation here are **full-sample** statistics, these columns are for EDA
only; in Milestone 03 the scalers will be refitted on the training window to prevent look-ahead leakage.
""")

code(r"""
# --- Categorical encoding: nominal strings -> Boolean dummy indicator flags ----------------
# Two nominal variables are constructed from the data and encoded with pandas.get_dummies:
nominal = pd.DataFrame({
    "quarter": "Q" + master.index.quarter.astype(str),
    "regime":  np.where(master["usrec"] == 1, "recession", "expansion"),
}, index=master.index)
print("Nominal string columns (first 3 rows):"); display(nominal.head(3))

dummies = pd.get_dummies(nominal, prefix=["q", "regime"], drop_first=True, dtype=int)  # reference: Q1, expansion
print("\nAfter get_dummies(drop_first=True) -> one Boolean 0/1 flag per non-reference level:")
display(dummies.head(3))

# The master already carries the same encoding; verify the two agree exactly
assert (dummies[["q_Q2", "q_Q3", "q_Q4"]].to_numpy() == master[["q2", "q3", "q4"]].to_numpy()).all()
assert (dummies["regime_recession"].to_numpy() == master["usrec"].to_numpy()).all()

dummy_counts = master[["usrec", "q2", "q3", "q4", "covid_period", "copper_avail", "iron_avail", "icsa_spike"]].agg(["sum", "mean"]).T
dummy_counts.columns = ["weeks = 1", "share"]
dummy_counts["share"] = dummy_counts["share"].round(3)
dummy_counts.to_csv(TABLES / "t07_dummy_counts.csv")
display(dummy_counts)
""")

md(r"""
### Interpretation: dummy encoding
`get_dummies(drop_first=True)` converts the two nominal strings into four 0/1 indicators (`Q2`, `Q3`, `Q4`,
`recession`); Q1 and expansion are the reference levels, which avoids the dummy-variable trap in a regression with
an intercept. The assertion confirms the master's `q2–q4` and `usrec` columns are identical to this encoding.
The remaining flags are binary by construction: `covid_period` (43 weeks), the two availability flags, and the
target-derived `icsa_spike`, which marks the 150 weeks (top decile) in which claims rose by more than
5.2 % week-over-week. Only 120 weeks (8 %) fall inside an NBER recession, which already warns that any
regime-interaction hypothesis will rest on a small number of recession observations.
""")

# =============================================================================
md(r"""
# **Section 3: Exploratory Data Analysis & Initial Findings**

## 3.1 Univariate summary statistics
""")

code(r"""
def univariate(s: pd.Series) -> pd.Series:
    s = s.dropna(); q1, q3 = s.quantile([0.25, 0.75])
    return pd.Series({"n": len(s), "mean": s.mean(), "median": s.median(), "SD": s.std(ddof=1), "IQR": q3 - q1,
                      "min": s.min(), "max": s.max(), "skewness": stats.skew(s)})

uni_cols = (["icsa", "icsa_pct_chg_1w"] + [f"{k}_mean" for k in KEYS]
            + [f"{k}_pct_1w" for k in KEYS] + [f"{k}_vol_4w" for k in KEYS])
uni = master[uni_cols].apply(univariate).T
uni.insert(0, "unit", ["persons/wk", "%"] + [UNITS[k] for k in KEYS] + ["%"] * 4 + ["log-ret SD"] * 4)
uni["n"] = uni["n"].astype(int)
uni.to_csv(TABLES / "t08_univariate.csv")
display(uni.round(3))
""")

code(r"""
# Resistant vs non-resistant measures: how much do the mean/SD move if the 44 COVID weeks are removed?
covid_mask = (master.index >= COVID[0]) & (master.index <= COVID[1])
resist = pd.DataFrame({
    "all weeks":        univariate(master["icsa"]),
    "excluding Mar-Dec 2020": univariate(master.loc[~covid_mask, "icsa"]),   # 43 weeks removed
}).loc[["n", "mean", "median", "SD", "IQR"]]
resist["% change"] = ((resist.iloc[:, 1] / resist.iloc[:, 0] - 1) * 100).round(1)
resist.to_csv(TABLES / "t09_resistant_vs_nonresistant.csv")
display(resist.round(1))
""")

md(r"""
### Interpretation
**Claims.** Mean weekly claims (362,000) sit 15 % above the median (315,000) and the SD (331,000) is 2.3 times the
IQR (146,000), the signature of a heavy right tail. Removing the 43 pandemic weeks cuts the mean by 10 % and the SD by
70 % but moves the median by under 1 % and the IQR by 5 %: the median and IQR are *resistant*, the mean and SD are not.
We therefore report medians and IQRs as the headline descriptives and use the log scale in models.

**Commodities.** Crude oil averages 61 USD/bbl with an almost symmetric distribution (skew 0.1); copper averages
6,460 USD/t; iron ore 107 USD/t. Natural gas (mean 4.06 vs median 3.30 USD/MMBtu) is right-skewed. The weekly
*percentage changes* are centred near zero, as expected for prices, but their tails differ sharply: oil and gas
have week-over-week moves of −83 % / +373 % and −77 % / +301 % (the April 2020 oil collapse and the 2005/2022 gas
squeezes), whereas copper and iron ore never move more than ±20 % in a week. Copper is the least volatile input in
this sample.
""")

md(r"""
## 3.2 Outlier diagnostic: z-score rule vs quartile (IQR) rule
""")

code(r"""
def outlier_audit(s: pd.Series) -> dict:
    s = s.dropna()
    z = (s - s.mean()) / s.std(ddof=1)
    q1, q3 = s.quantile([0.25, 0.75]); iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return {"n": len(s), "z-rule |z|>3 (count)": int((z.abs() > 3).sum()),
            "z upper bound": s.mean() + 3 * s.std(ddof=1),
            "IQR-rule (count)": int(((s < lo) | (s > hi)).sum()), "IQR upper bound": hi,
            "max": s.max()}

audit_cols = ["icsa", "icsa_pct_chg_1w"] + [f"{k}_pct_1w" for k in KEYS]
audit_all = pd.DataFrame({c: outlier_audit(master[c]) for c in audit_cols}).T
audit_excl = pd.DataFrame({c: outlier_audit(master.loc[~covid_mask, c]) for c in audit_cols}).T
audit = pd.concat({"full sample": audit_all, "excluding Mar-Dec 2020": audit_excl}, axis=1)
audit.to_csv(TABLES / "t10_outlier_audit.csv")
display(audit_all.round(1)); display(audit_excl.round(1))
""")

md(r"""
### Interpretation: masking and variance inflation
The two rules disagree by an order of magnitude. On weekly claims the z-score rule flags **18** weeks, the IQR rule
**71**; on the weekly % change in claims the z-rule flags **2** weeks against **51** for the IQR rule. The reason is
*variance inflation*: the pandemic weeks push the SD of claims from 101,000 to 331,000, so the z-rule's upper
bound climbs to 1.35 million and everything short of the COVID spike is hidden behind it. This is the **masking
effect**: the most extreme outliers inflate the very scale used to detect outliers, concealing the 2008–09 peak
(665,000) and every other recession week. The IQR rule, whose bound (606,000) depends only on the middle half of the
data, is unaffected and isolates exactly the recession periods. Dropping the 43 pandemic weeks and re-running the
z-rule raises its count to 24, confirming that those weeks had been masking others.

These extreme weeks are *real* events, not errors, so they are **retained**. Their influence is controlled
instead through (i) the log transform of the target, (ii) the `covid_period` dummy, which lets a model absorb the
pandemic level shift, and (iii) robust loss functions where appropriate. For the commodity shocks the same pattern
holds: the −83 % / +373 % oil weeks of April–May 2020 alone move the SD of `oil_pct_1w` from 4.4 to 11.0 percentage
points, so the z-rule finds only 3 outliers where the IQR rule finds 55.
""")

md(r"""
## 3.3 Bivariate and multivariate exploration
""")

code(r"""
# (a) Correlation matrix of the key continuous variables (log levels, weekly % changes, volatility, regime)
corr_cols = (["log_icsa", "icsa_pct_chg_1w"] + [f"{k}_log_mean" for k in KEYS]
             + [f"{k}_pct_1w" for k in KEYS] + [f"{k}_vol_4w" for k in KEYS] + ["usrec"])
corr = master[corr_cols].corr(method="pearson")
corr.to_csv(TABLES / "t11_correlation_matrix.csv")
display(corr.round(2))
""")

code(r"""
# (b) Cross-correlation of each commodity's weekly % change with the % change in claims, lags 0..16.
#     A positive lag k means the commodity move happened k weeks BEFORE the claims move.
y = master["icsa_pct_chg_1w"]
xcorr = pd.DataFrame({k: [y.corr(master[f"{k}_pct_1w"].shift(l)) for l in range(0, MAX_LAG + 1)] for k in KEYS},
                     index=pd.Index(range(0, MAX_LAG + 1), name="lag (weeks)"))
n_eff = {k: int(pd.concat([y, master[f"{k}_pct_1w"]], axis=1).dropna().shape[0]) for k in KEYS}
band = {k: 2 / np.sqrt(n_eff[k]) for k in KEYS}         # approximate 95 % band for a zero correlation
xcorr.to_csv(TABLES / "t12_cross_correlation_lags.csv")
best = pd.DataFrame({"strongest lag": xcorr.abs().idxmax(), "r at that lag": [xcorr[k][xcorr[k].abs().idxmax()] for k in KEYS],
                     "n": pd.Series(n_eff), "±2/√n band": pd.Series(band)}).round(3)
best.to_csv(TABLES / "t13_xcorr_best_lag.csv")
display(xcorr.round(3).T); display(best)
""")

code(r"""
# (c) Group-by aggregation: labour market and commodity behaviour in recession vs expansion weeks
grp_cols = ["icsa", "icsa_pct_chg_1w", "icsa_spike"] + [f"{k}_pct_1w" for k in KEYS] + [f"{k}_vol_4w" for k in KEYS]
regime = master["usrec"].map({0: "expansion", 1: "recession"}).rename("regime")
grp = master.groupby(regime)[grp_cols].agg(["median", "mean"])
grp.to_csv(TABLES / "t14_groupby_regime.csv")
display(grp.T.round(3))
print("weeks per regime:", regime.value_counts().to_dict())
""")

code(r"""
# (d) Contingency tables: did a large commodity shock 4 weeks earlier precede a claims spike?
#     shock = |weekly % change| in the top decile of that commodity's own distribution
LAG_CT = 4
ct_rows = []
for k in KEYS:
    absmove = master[f"{k}_pct_1w"].abs()
    shock = (absmove >= absmove.quantile(0.90)).astype(float).where(absmove.notna()).shift(LAG_CT)
    tab = pd.crosstab(shock.map({0.0: "no shock", 1.0: "shock"}), master["icsa_spike"].map({0: "no spike", 1: "spike"}))
    chi2, p, dof, _ = stats.chi2_contingency(tab)
    rate_shock = tab.loc["shock", "spike"] / tab.loc["shock"].sum()
    rate_none = tab.loc["no shock", "spike"] / tab.loc["no shock"].sum()
    ct_rows.append({"commodity": LABELS[k], "spike rate after shock": rate_shock, "spike rate otherwise": rate_none,
                    "relative risk": rate_shock / rate_none, "chi2": chi2, "p-value": p})
    print(f"\n{LABELS[k]} shock at t-{LAG_CT}  ×  claims spike at t"); display(tab)
contingency = pd.DataFrame(ct_rows).round(4)
contingency.to_csv(TABLES / "t15_contingency_shock_spike.csv", index=False)
display(contingency)
""")

md(r"""
### Interpretation
**Levels.** In log levels, claims correlate *negatively* with oil (−0.20) and copper (−0.28) and *positively*
with iron ore (+0.29) and the recession flag (+0.34). The copper result is the classic "Dr. Copper" pattern: copper is
bought when factories expand, so high copper prices coincide with low unemployment. Oil shows the same demand-side
sign. The iron-ore sign is largely a sample artefact (iron ore exists only from 2010, when claims trended downward
while iron ore first fell then recovered). These level correlations are dominated by shared slow trends and are
**not** evidence about shocks; they mainly tell us that *levels* must enter models with care (detrended, or as
controls).

**Shocks and lags.** Week-over-week changes are, as expected for a noisy weekly series, only weakly cross-correlated
(all |r| < 0.14). The informative part is the *shape* across lags: oil's correlation is most negative at lags 0–1
(an oil price *fall* coincides with claims *rising*, consistent with 2008 and 2020, when demand collapses drove both),
copper peaks at lag 0 and again at lags 7–8, and iron ore has an isolated −0.13 at lag 6. The coefficients that clear
the ±2/√n band are oil at lags 0–1, copper at lags 0 and 7, and iron ore at lag 6; no natural-gas lag clears it. None of these is yet a causal finding, but they tell the
modelling stage where to look and, importantly, warn that the sign may be *negative*: commodity collapses, not only
spikes, precede layoff waves.

**Regimes.** Recession weeks (n = 120) have a median claims level of 432,500 against 309,000 in expansions, a mean
weekly claims change of +9.5 % versus −0.2 %, and 4-week oil volatility about 1.8 times higher on average (0.041 vs 0.023). Commodity *returns* are
lower in recessions for every commodity, again pointing to demand-driven co-movement.

**Contingency.** Conditioning on a top-decile absolute move four weeks earlier, a natural-gas shock is followed by a
claims spike in 18.5 % of weeks versus 8.9 % otherwise (relative risk 2.1, χ² = 10.8, p = 0.001). Oil, copper and
iron ore shocks do not shift the spike rate significantly at this particular lag. The gas result is the strongest
single bivariate signal in the data and feeds directly into hypothesis H2.
""")

md(r"""
## 3.4 Publication-quality visualisations
Conventions: one y-axis per panel; a fixed hue per commodity in every figure (oil blue, gas orange, copper aqua,
iron ore yellow), claims in near-black, NBER recessions as neutral-gray bands; units on every axis; captions below
each figure.
""")

code(r"""
usrec_runs = []           # (start, end) of each recession, for shading
in_rec = master["usrec"].astype(bool)
starts = master.index[in_rec & ~in_rec.shift(1, fill_value=False)]
ends = master.index[in_rec & ~in_rec.shift(-1, fill_value=False)]
usrec_runs = list(zip(starts, ends))

def shade_recessions(ax):
    for s, e in usrec_runs:
        ax.axvspan(s, e, color=COLORS["rec"], zorder=0, lw=0)

# ---- Figure 1: the target --------------------------------------------------------------
fig, ax = plt.subplots(figsize=(10, 4.6))
shade_recessions(ax)
ax.plot(master.index, master["icsa"], color=COLORS["claims"], lw=1.4)
ax.set_yscale("log")
ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda v, _: f"{v/1e6:.0f}M" if v >= 1e6 else f"{v/1e3:.0f}k"))
ax.set_yticks([200e3, 300e3, 500e3, 1e6, 2e6, 4e6, 6e6]); ax.yaxis.set_minor_formatter(mpl.ticker.NullFormatter())
ax.set_ylim(150e3, 9e6)
ax.set_ylabel("Initial claims per week (persons, log scale)")
ax.set_xlabel("Week ending (Saturday)")
ax.set_title("US initial jobless claims, weekly, Jan 1998 – Sep 2026")
for d, txt, off in [("2009-03-28", "Mar 2009: 665k", (0, 6)), ("2020-04-04", "Apr 2020: 6.14M", (-8, 0))]:
    ax.annotate(txt, (pd.Timestamp(d), master.loc[d, "icsa"]), xytext=off, textcoords="offset points",
                ha="center" if off[0] == 0 else "right", va="center", fontsize=9, color=COLORS["muted"])
ax.text(0.01, 0.95, "Shaded: NBER recessions", transform=ax.transAxes, fontsize=9, color=COLORS["muted"], va="top")
ax.margins(x=0.01); ax.grid(axis="x", visible=False)
fig.tight_layout(); fig.savefig(FIGS / "fig1_claims_timeseries.png"); plt.show()
""")

md(r"""
**Figure 1.** Weekly US initial unemployment-insurance claims (seasonally adjusted, persons per week) on a logarithmic
axis, 3 Jan 1998 to 26 Sep 2026. Gray bands mark NBER recessions (2001, 2007–09, 2020). The log scale shows the 2001
and 2008–09 episodes, which a linear axis flattens against the 2020 spike. Source: FRED series ICSA.
""")

code(r"""
# ---- Figure 2: the predictors, small multiples with each commodity's own unit ---------------
fig, axes = plt.subplots(2, 2, figsize=(10, 6.2), sharex=True)
for ax, k in zip(axes.ravel(), KEYS):
    shade_recessions(ax)
    ax.plot(master.index, master[f"{k}_mean"], color=COLORS[k], lw=1.3)
    ax.set_title(LABELS[k], color=COLORS["claims"], loc="left")
    ax.set_ylabel(f"Weekly mean price ({UNITS[k]})")
    ax.margins(x=0.01); ax.grid(axis="x", visible=False)
    first = master[f"{k}_mean"].first_valid_index()
    if first > pd.Timestamp("1998-12-31"):            # structural gap, not a stray missing week
        ax.text(first, ax.get_ylim()[1] * 0.93, f"◄ no data before {first:%b %Y}", fontsize=8.5, color=COLORS["muted"], ha="left", va="top")
for ax in axes[1]:
    ax.set_xlabel("Week ending (Saturday)")
fig.suptitle("Weekly mean commodity prices, Jan 1998 – Sep 2026 (gray bands: NBER recessions)", x=0.01, ha="left", fontweight="semibold")
fig.tight_layout(); fig.savefig(FIGS / "fig2_commodity_prices.png"); plt.show()
""")

md(r"""
**Figure 2.** Weekly mean prices of the four input commodities, each on its own axis and physical unit:
WTI crude oil (USD per barrel, FRED DCOILWTICO), Henry Hub natural gas (USD per MMBtu, FRED DHHNGSP), COMEX copper
front-month futures converted to USD per metric tonne (Yahoo Finance HG=F), and iron ore 62 % Fe CFR China futures
(USD per metric tonne, Yahoo Finance TIO=F). Copper and iron ore begin when their futures histories begin
(Sep 2000 and Oct 2010); earlier weeks are missing by construction. All four fall sharply inside the 2008–09 and 2020
recessions, which is why the shock–claims relationship must be examined in both directions.
""")

code(r"""
# ---- Figure 3: lag structure --------------------------------------------------------------
fig, axes = plt.subplots(2, 2, figsize=(10, 6.2), sharex=True, sharey=True)
lags = xcorr.index.to_numpy()
for ax, k in zip(axes.ravel(), KEYS):
    ax.axhspan(-band[k], band[k], color=COLORS["rec"], zorder=0, lw=0)
    ax.bar(lags, xcorr[k], width=0.7, color=COLORS[k], zorder=2)
    ax.axhline(0, color=COLORS["muted"], lw=0.8)
    j = int(xcorr[k].abs().idxmax())
    outside = [int(l) for l in lags if abs(xcorr[k][l]) > band[k]]
    ax.text(0.99, 0.95, f"strongest: lag {j} (r = {xcorr[k][j]:+.2f})\noutside band: {outside if outside else 'none'}",
            transform=ax.transAxes, ha="right", va="top", fontsize=8.5, color=COLORS["claims"])
    ax.set_title(f"{LABELS[k]}  (n = {n_eff[k]:,} weeks)", loc="left")
    ax.set_xticks(range(0, 17, 2)); ax.grid(axis="x", visible=False)
for ax in axes[:, 0]:
    ax.set_ylabel("Pearson r with Δ% claims")
for ax in axes[1]:
    ax.set_xlabel("Lag k (weeks the commodity move precedes the claims move)")
fig.suptitle("Cross-correlation between weekly % change in commodity price at week t−k and % change in initial claims at week t\n"
             "(gray band: ±2/√n, the approximate 95 % interval for zero correlation)", x=0.01, ha="left", fontweight="semibold", fontsize=10.5)
fig.tight_layout(); fig.savefig(FIGS / "fig3_lag_crosscorrelation.png"); plt.show()
""")

md(r"""
**Figure 3.** Lead–lag structure between commodity price shocks and claims. Each bar is the Pearson correlation between
the week-over-week percentage change in a commodity's weekly mean price *k* weeks earlier and the week-over-week
percentage change in initial claims; the gray band is ±2/√n. Correlations are small, as expected for noisy weekly
changes, but oil's effect is concentrated at lags 0–1 with a negative sign, copper shows a secondary dip at lags 7–8,
and iron ore's one coefficient outside the band is at lag 6. The figure motivates keeping short (0–2) and medium
(6–8) lags per commodity rather than the full 16-week block.
""")

code(r"""
# ---- Figure 4: correlation heatmap (diverging: blue negative, gray zero, red positive) ------
pretty = {"log_icsa": "log claims", "icsa_pct_chg_1w": "Δ% claims", "usrec": "recession"}
for k in KEYS:
    pretty.update({f"{k}_log_mean": f"log {k}", f"{k}_pct_1w": f"Δ% {k}", f"{k}_vol_4w": f"vol4w {k}"})
cm = mpl.colors.LinearSegmentedColormap.from_list("div", ["#2a78d6", "#f0efec", "#e34948"])
fig, ax = plt.subplots(figsize=(9.5, 8))
mask = np.triu(np.ones_like(corr, dtype=bool), k=1)
sns.heatmap(corr.rename(index=pretty, columns=pretty), mask=mask, cmap=cm, vmin=-1, vmax=1, center=0,
            annot=True, fmt=".2f", annot_kws={"size": 7.5}, linewidths=1, linecolor="white",
            cbar_kws={"label": "Pearson correlation coefficient", "shrink": 0.7}, ax=ax, square=True)
ax.set_title("Pearson correlations among target, commodity levels, weekly shocks, volatility and regime", loc="left")
ax.tick_params(axis="x", rotation=60); ax.grid(False)
fig.tight_layout(); fig.savefig(FIGS / "fig4_correlation_heatmap.png"); plt.show()
""")

md(r"""
**Figure 4.** Lower triangle of the Pearson correlation matrix for the target (log level and weekly % change),
commodity log levels, weekly % changes, trailing 4-week volatilities and the NBER recession flag (pairwise-complete
observations). Diverging scale: blue negative, gray zero, red positive. Levels are strongly inter-correlated
(oil–copper 0.82), so they should not enter a linear model together untransformed; the % change block is nearly
orthogonal, which is desirable for the lagged-shock features.
""")

code(r"""
# ---- Figure 5: distribution of claims change after a commodity shock vs otherwise -----------
rows = []
for k in KEYS:
    absmove = master[f"{k}_pct_1w"].abs()
    shock = (absmove >= absmove.quantile(0.90)).astype(float).where(absmove.notna()).shift(LAG_CT)
    tmp = pd.DataFrame({"commodity": LABELS[k], "group": shock.map({1.0: "after a top-decile shock (t−4)", 0.0: "other weeks"}),
                        "dy": master["icsa_pct_chg_1w"]}).dropna()
    rows.append(tmp)
plot_df = pd.concat(rows)
fig, ax = plt.subplots(figsize=(10, 4.8))
order = [LABELS[k] for k in KEYS]
sns.boxplot(data=plot_df, x="commodity", y="dy", hue="group", order=order, hue_order=["other weeks", "after a top-decile shock (t−4)"],
            palette={"other weeks": "#c3c2b7", "after a top-decile shock (t−4)": "#2a78d6"}, width=0.6, gap=0.12,
            showfliers=False, linewidth=1, ax=ax)
# recolour the shock boxes with each commodity's own hue so identity follows the entity
shock_patches = [p for p in ax.patches if isinstance(p, mpl.patches.PathPatch)][len(order):]
for p, k in zip(shock_patches, KEYS):
    p.set_facecolor(COLORS[k])
ax.axhline(0, color=COLORS["muted"], lw=0.8)
ax.set_ylim(-12, 18)
ax.set_ylabel("Week-over-week change in initial claims (%)"); ax.set_xlabel("")
ax.set_title("Weekly % change in claims, four weeks after a top-decile commodity price move vs all other weeks")
handles, labels_ = ax.get_legend_handles_labels()
handles[1] = mpl.patches.Patch(facecolor="white", edgecolor=COLORS["claims"], label=labels_[1])
ax.legend(handles, ["other weeks (gray)", "after a top-decile shock at t−4 (commodity colour)"], loc="upper left", fontsize=9)
ax.grid(axis="x", visible=False)
# direct label: spike share per group under each pair
for i, k in enumerate(KEYS):
    r = contingency.loc[contingency["commodity"] == LABELS[k]].iloc[0]
    ax.text(i, -11.3, f"spike rate {r['spike rate otherwise']*100:.0f}% → {r['spike rate after shock']*100:.0f}%",
            ha="center", fontsize=8.5, color=COLORS["muted"])
fig.tight_layout(); fig.savefig(FIGS / "fig5_claims_change_after_shock.png"); plt.show()
""")

md(r"""
**Figure 5.** Distribution (median, interquartile box, 1.5×IQR whiskers; outliers beyond ±12/18 % hidden for legibility,
not removed from the statistics) of the week-over-week percentage change in initial claims, split by whether the
commodity recorded a top-decile absolute weekly price move four weeks earlier. Gray boxes are all other weeks;
coloured boxes follow a shock. Text under each pair gives the share of weeks that are claims *spikes* (top-decile
rises, > 5.2 %). Natural-gas shocks double the spike rate (9 % → 18 %), the clearest bivariate pattern in the data;
the other commodities show wider dispersion after shocks but little shift in the centre.
""")

# =============================================================================
md(r"""
# **Section 4: Formal Hypothesis Framing & Analytical Plan**

Notation: $Y_t$ is the weekly change in log initial claims, $\Delta \log(\text{ICSA}_t)$ (equivalently the weekly
% change); $\Delta p^{c}_{t-k}$ is the % change in commodity $c$'s weekly mean price $k$ weeks earlier;
$\sigma^{c}_{t}$ is its trailing 4-week volatility; $R_t$ is the NBER recession flag.

**H1 — Energy shocks (crude oil).**
$H_0: \beta^{oil}_k = 0 \;\; \forall k \in \{0,\dots,16\}$ versus
$H_1: \beta^{oil}_k \neq 0$ for at least one $k$, in $Y_t = \alpha + \sum_k \beta^{oil}_k \Delta p^{oil}_{t-k} + \gamma' Z_t + \varepsilon_t$.
The EDA suggests $\beta^{oil}_{0,1} < 0$ (price collapses, not spikes, precede claims rises), so the test is two-sided.

**H2 — Energy shocks (natural gas).**
$H_0: \beta^{gas}_k = 0 \;\; \forall k$ versus $H_1: \beta^{gas}_k > 0$ for some $k \in \{2,\dots,8\}$.
Motivated by the contingency result (gas shock at $t-4$ doubles the spike probability).

**H3 — Industrial-metal shocks (copper and iron ore).**
$H_0: \beta^{cu}_k = \beta^{fe}_k = 0 \;\; \forall k$ versus $H_1$: at least one differs from zero.
Given the "Dr. Copper" pattern we expect *negative* coefficients (falling metal prices signal shrinking orders and
subsequent layoffs); the direction will be reported, not assumed.

**H4 — Volatility, not only direction.**
$H_0: \delta^{c} = 0$ versus $H_1: \delta^{c} > 0$ in $Y_t = \alpha + \delta^{c}\sigma^{c}_{t-4} + \gamma' Z_t + \varepsilon_t$,
for each commodity $c$: uncertainty about input costs raises layoffs independently of the sign of the price move.

**H5 — Lag structure and regime dependence.**
$H_0$: the lag $k^{*}$ at which $|\beta^{c}_{k}|$ is maximal is the same in recession and expansion weeks, and the
interaction $\beta^{c}_{k} \cdot R_t$ is zero; $H_1$: the transmission is faster and/or stronger in recessions
($\theta^{c}_{k} \neq 0$ in $Y_t = \alpha + \beta^{c}_{k}\Delta p^{c}_{t-k} + \theta^{c}_{k}\,\Delta p^{c}_{t-k} R_t + \lambda R_t + \gamma' Z_t + \varepsilon_t$).
The proposal's expectation is $k^{*} \in [4, 12]$ weeks.

**Analytical plan.** H1–H3 will be tested with distributed-lag regressions on $\Delta\log$ claims with Newey–West
(HAC) standard errors, complemented by Granger-causality F-tests; H4 adds volatility terms; H5 adds the recession
interaction and a rolling-window re-estimation. The predictive counterpart is a gradient-boosted regressor on the
same features with time-series cross-validation, from which the strongest lags per commodity will be read off
(permutation importance) and kept for the final, parsimonious model. All scalers and thresholds will be refitted
on the training window only.
""")

code(r"""
# Variable mapping: every hypothesis -> concrete columns in master_weekly.csv
controls = "usrec, covid_period, q2, q3, q4, lagged target (icsa_pct_chg_1w shifted 1–2)"
mapping = pd.DataFrame([
    ["H1", "icsa_pct_chg_1w  (alt.: Δ log_icsa; icsa_spike for classification)",
     "oil_pct_lag0..16  (oil_pct_1w = lag 0)", controls + ", gas_pct_lag*"],
    ["H2", "icsa_pct_chg_1w / icsa_spike", "gas_pct_lag2..8", controls + ", oil_pct_lag*"],
    ["H3", "icsa_pct_chg_1w / icsa_spike", "copper_pct_lag0..16, iron_pct_lag0..16", controls + ", oil_pct_lag*, iron_avail"],
    ["H4", "icsa_pct_chg_1w", "oil_vol_4w, gas_vol_4w, copper_vol_4w, iron_vol_4w (each shifted 4 weeks)", controls + ", own {c}_pct_lag4"],
    ["H5", "icsa_pct_chg_1w", "{c}_pct_lagk × usrec (interaction) for the k* found under H1–H3", controls],
], columns=["Hypothesis", "Target / response (Y)", "Primary explanatory predictors (X)", "Confounders / controls (Z)"])
mapping.to_csv(TABLES / "t16_hypothesis_variable_mapping.csv", index=False)
display(mapping.style.hide(axis="index").set_properties(**{"text-align": "left", "white-space": "pre-wrap"}))
""")

md(r"""
# **Section 5: Progressive Manuscript Workflow**
The accompanying PDF, *Milestone02_Report.pdf*, is written as Draft Section II (Data and Preprocessing) and Draft
Section III (Exploratory Data Analysis) of the final manuscript, with the hypotheses of Section 4 above as the
bridge into the modelling sections. All numbers in the PDF are read from the CSV tables in `data/processed/tables/`
and the figures in `figures/`, both produced by this notebook.
""")

code(r"""
# Export the data dictionary and list every artefact produced by this notebook
data_dictionary(master).to_csv(ROOT / "data" / "processed" / "data_dictionary.csv", index=False)
print("Tables:"); print("\n".join(f"  {p.name}" for p in sorted(TABLES.glob("*.csv"))))
print("Figures:"); print("\n".join(f"  {p.name}" for p in sorted(FIGS.glob("*.png"))))
""")

nb["cells"] = cells
nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
out = ROOT / "Milestone02_Analysis.ipynb"
nbf.write(nb, out)
print("wrote", out, "with", len(cells), "cells")
