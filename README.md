# Milestone 02 — Section 2: Data Ingestion, Cleaning & Structural Readiness

| Brief item | Where it is |
|---|---|
| Scraping / collection audit | `src/collect.py`, `data/raw/manifest.json`, notebook §2.1 |
| Data alignment & structural organisation | `src/build_master.py`, `data/processed/master_weekly.csv`, notebook §2.2 |
| Cleaning & missing-data strategy | notebook §2.3 |
| Transformations & encoding (log, z-score / Min-Max, dummies) | notebook §2.4 |

Notebook: `Milestone02_Section2_DataIngestion.ipynb` (executed; all outputs inline).

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python src/collect.py
.venv/bin/python src/build_master.py
.venv/bin/jupyter nbconvert --to notebook --execute --inplace Milestone02_Section2_DataIngestion.ipynb
```
