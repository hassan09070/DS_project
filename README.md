# Milestone 02 — Section 2: Data Ingestion, Cleaning & Structural Readiness

This branch contains only the Section 2 deliverables. This file walks through the pipeline end to end and
then maps every bullet of the Section 2 brief to the exact place where it is done.

## End-to-end flow

```
FRED CSV endpoint ─┐                       ┌─ data/raw/*.csv + manifest.json
Yahoo Finance ─────┤  src/collect.py  ───► │
                   └───────────────────────┘
                                 │
                                 ▼
                     src/build_master.py  ───►  data/processed/master_weekly.csv  (1,500 weeks × 115 columns)
                                                data/processed/data_dictionary.csv
                                 │
                                 ▼
             Milestone02_Section2_DataIngestion.ipynb  (audit, alignment checks, missing data,
                                                        transformations, encoding — outputs inline)
```

1. **Collect** (`src/collect.py`). Eight raw series are downloaded: six from FRED (weekly initial claims ICSA, daily WTI
   oil DCOILWTICO, daily Henry Hub gas DHHNGSP, monthly NBER recession flag USREC, and the monthly copper and iron-ore
   benchmarks kept for reference) and two from Yahoo Finance via `yfinance` (copper futures HG=F, iron-ore futures TIO=F).
   Each file is cached under `data/raw/` and `manifest.json` records its URL, pull time, row count and date span.
2. **Build the master table** (`src/build_master.py`). Daily prices are collapsed to the claims week (Sunday–Saturday,
   labelled by the Saturday), the monthly recession flag is forward-filled to weeks, everything is left-joined onto the
   claims index, and derived features are added: % changes, 16 lags, volatility, log levels, z-score and Min-Max copies,
   and the 0/1 dummies. Sanity assertions run before the CSV is written.
3. **Document and check** (notebook). The notebook imports the two scripts, rebuilds the table, and shows the evidence the
   brief asks for: the collection audit, the alignment code and a worked example, the missing-value report and its rationale,
   and the transformation / encoding steps with interpretation after each one.

Reproduce:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python src/collect.py            # add --force to re-download
.venv/bin/python src/build_master.py
.venv/bin/jupyter nbconvert --to notebook --execute --inplace Milestone02_Section2_DataIngestion.ipynb
```

## Where each bullet of the brief is done

### 1. Scraping / Collection Audit — "document the mechanics used to collect, scrape, or extract your raw files"

| What | Where |
|---|---|
| FRED download mechanics (keyless CSV endpoint, `.` parsed as missing) | `src/collect.py` → `fred_url()` line 61, `fetch_fred()` lines 65–78 (`na_values=["."]` on line 75) |
| Yahoo Finance mechanics via `yfinance.download` | `src/collect.py` → `fetch_yfinance()` lines 103–123 |
| Fallback to the raw Yahoo chart API with explicit `period1`/`period2` (so daily bars are kept over long ranges) | `src/collect.py` → `fetch_yahoo_chart_api()` lines 81–100 |
| Provenance record: URL, pull timestamp, rows, first/last date per file | `src/collect.py` → `record()` inside `main()`, lines 133–141; output `data/raw/manifest.json` |
| Cached raw files | `data/raw/ICSA.csv`, `DCOILWTICO.csv`, `DHHNGSP.csv`, `USREC.csv`, `PCOPPUSDM.csv`, `PIORECRUSDM.csv`, `HG_F.csv`, `TIO_F.csv` |
| Written audit (sources, endpoint quirks, structural start dates of HG=F 2000-08-30 and TIO=F 2010-10-14) | notebook cell 5 (markdown §2.1) |
| Printed audit trail: every file's frequency, rows, span, pull time and first row | notebook cell 6 |

### 2. Data Alignment & Structural Organization — "modeling-ready tabular layout … reshaping or merging (melt / pivot / concat / joins)"

| What | Where |
|---|---|
| Unit of observation: 1 row = 1 week ending Saturday (claims convention); check that all ICSA dates are Saturdays | `src/build_master.py` → `load_icsa()` line 52, assertion line 55 |
| Daily → weekly down-sampling (`resample("W-SAT")`): mean, last, trading-day count, within-week volatility, 4-week volatility | `src/build_master.py` → `weekly_from_daily()` lines 65–91 |
| Unit harmonisation: copper USD/lb → USD/tonne | `src/build_master.py` line 27 and line 48 |
| Monthly → weekly up-sampling of the recession flag (forward fill) | `src/build_master.py` line 121 |
| Join: all weekly frames left-joined onto the claims index | `src/build_master.py` line 116 |
| Feature construction: % change, log level, lags 1–16 (concat, no fragmentation) | `src/build_master.py` → `add_commodity_features()` lines 94–102 |
| Structural sanity assertions (unique monotonic index, start date, target never missing, expected NaN windows) | `src/build_master.py` lines 186–192 |
| Resulting modelling-ready table | `data/processed/master_weekly.csv` |
| Column-by-column description (unit, source, role) | `data/processed/data_dictionary.csv`, generated by `data_dictionary()` line 150 |
| The alignment functions printed in the notebook for review | notebook cell 8 |
| Worked example: five daily WTI prices → one weekly row, plus the all-Saturdays / 7-day-spacing check | notebook cell 9, interpretation cell 10 |
| Narrative of the four reshaping steps | notebook cell 7 (markdown §2.2) |

### 3. Cleaning & Missing Data Strategy

**"Report missing value counts and percentages across all features"**

| What | Where |
|---|---|
| Missing count and % for all 115 columns, the lag block summarised, and a by-year missingness table per commodity | notebook cell 12 |

**"Explicit rationale for handling missing data … and discuss potential selection bias"**

| What | Where |
|---|---|
| Decision table per variable group (target, oil, gas, copper, iron, lags, dummies) and why nothing is imputed; why FRED back-fill of iron ore was rejected; listwise deletion per model; the selection-bias paragraph (iron-ore models never see 2001 or 2008) | notebook cell 13 (markdown) |
| Cleaning rules implemented in code: FRED `.` → NaN | `src/collect.py` line 75 |
| Drop NaN days before aggregating | `src/build_master.py` line 46 |
| Weeks with zero trading days set to NaN | `src/build_master.py` line 89 |
| Negative WTI print (2020-04-20) excluded from log returns only, price level kept | `src/build_master.py` line 79 |
| Availability flags that record the structural gaps | `src/build_master.py` lines 126–127 |

### 4. Transformations & Encoding

**"Feature Rescaling: log-transformations applied to handle heavy right-skewness"**

| What | Where |
|---|---|
| `log_icsa` and `{commodity}_log_mean` columns | `src/build_master.py` line 108 (`log_icsa`) and `add_commodity_features()` line 98 |
| Skewness before vs after the log for claims and the four prices, with interpretation | notebook cell 15, interpretation cell 16 |

**"Scaling: normalization (Min-Max) or standardization (z-score) applied to continuous variables"**

| What | Where |
|---|---|
| `*_z` (z-score) and `*_mm` (Min-Max) copies of claims, log claims and the four weekly mean prices | `src/build_master.py` lines 131–137 (`SCALE_COLS` loop) |
| Summary of raw vs z vs Min-Max statistics, and the note that modelling will refit scalers on the training window | notebook cell 17, interpretation cell 18 |

**"Categorical Encoding: conversion of nominal categorical strings into Boolean dummy indicator flags"**

| What | Where |
|---|---|
| Nominal strings `quarter` (Q1–Q4) and `regime` (expansion/recession) built, converted with `pd.get_dummies(drop_first=True)`, and asserted equal to the master's `q2, q3, q4, usrec`; counts of every 0/1 flag | notebook cell 19, interpretation cell 20 |
| Dummy columns in the pipeline: `usrec`, `q2–q4`, `covid_period`, `copper_avail`, `iron_avail` | `src/build_master.py` lines 121–127 |

## Files on this branch

| Path | Role |
|---|---|
| `src/collect.py` | Collection + provenance manifest |
| `src/build_master.py` | Alignment, cleaning, features, scaling, dummies, data dictionary |
| `data/raw/` | 8 raw CSVs + `manifest.json` |
| `data/processed/master_weekly.csv` | The master analytical dataset |
| `data/processed/data_dictionary.csv` | Column descriptions |
| `Milestone02_Section2_DataIngestion.ipynb` | Executed Section 2 notebook |
| `requirements.txt`, `.gitignore` | Environment |
| `DSSG - Project Team and Proposal.pdf`, `Data Source Selection.docx`, `data_sources.txt`, `milestone.txt` | Milestone 1 material already on the repo |
