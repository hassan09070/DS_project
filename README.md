# Commodity price shocks as an early-warning signal for US initial jobless claims

Data Science for Social Good project (SDG 8, Target 8.5).
Team: Rana Mohammad Sarib Khan (rk09083), Abdullah Ahmed (aa09303), Hassan Shahzad (ms09070).

## Milestone 02 deliverables

| Item | Path |
|---|---|
| Executable notebook (all tables and figures) | `Milestone02_Analysis.ipynb` |
| Manuscript draft, Sections II–IV (PDF) | `report/Milestone02_Report.pdf` |
| Weekly master dataset | `data/processed/master_weekly.csv` (1,500 weeks × 17 columns; lags 1–16 created on demand by `add_lags()`) |
| Data dictionary | `data/processed/data_dictionary.csv` |
| Tables used in the report | `data/processed/tables/` |
| Figures | `figures/` |
| Raw pulls with provenance manifest | `data/raw/` |

## Reproduce from scratch

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python src/collect.py              # FRED + Yahoo Finance -> data/raw/  (add --force to re-download)
.venv/bin/python src/build_master.py         # -> data/processed/master_weekly.csv
.venv/bin/python src/make_notebook.py        # regenerates the notebook source
.venv/bin/jupyter nbconvert --to notebook --execute --inplace Milestone02_Analysis.ipynb
.venv/bin/python src/make_report.py          # -> build/Milestone02_Report.docx -> report/Milestone02_Report.pdf
```

The DOCX→PDF step uses LibreOffice if `soffice` is installed, otherwise Apple Pages via AppleScript (macOS).

## Data notes

* One row = one week ending Saturday (the Department of Labor claims week). Sample starts 1998-01-03.
* Copper futures (HG=F) begin 2000-08-30 and iron ore futures (TIO=F) begin 2010-10-14; earlier weeks are NaN by design.
* FRED's daily Henry Hub series is sparse before April 2007; those weeks are NaN.
* FRED blocks browser-style User-Agent strings without full headers; `collect.py` uses the default `python-requests` agent.
* Milestone 01 files (`DSSG - Project Team and Proposal.pdf`, `Data Source Selection.docx`) are kept at the repo root.
