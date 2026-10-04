# Milestone 02 — Section 2: Data Ingestion, Cleaning & Structural Readiness

This branch holds only the Section 2 part of Milestone 02.

| Item | Path |
|---|---|
| Notebook (collection audit, alignment, missing data, transformations, encoding) | `Milestone02_Section2_DataIngestion.ipynb` |
| Raw pulls + provenance manifest | `data/raw/` |
| Weekly master dataset (1,500 weeks × 115 columns) | `data/processed/master_weekly.csv` |
| Data dictionary | `data/processed/data_dictionary.csv` |
| Section 2 summary tables | `data/processed/tables/t02…t07` |
| Collection script (FRED + Yahoo Finance) | `src/collect.py` |
| Master dataset builder | `src/build_master.py` |

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python src/collect.py
.venv/bin/python src/build_master.py
.venv/bin/jupyter nbconvert --to notebook --execute --inplace Milestone02_Section2_DataIngestion.ipynb
```
