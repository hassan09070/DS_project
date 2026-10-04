"""
make_section2_notebook.py -- Derive the Section 2-only notebook from the full one.

Keeps: the title cell (retitled), the setup cell, a short "build the master" cell,
and every cell from the "Section 2" heading up to (not including) "Section 3".
Lines that export summary tables are stripped so the Section 2 branch carries
only what the brief asks for. Run after make_notebook.py; execute the result with
`jupyter nbconvert --execute`.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "Milestone02_Analysis.ipynb"
OUT = ROOT / "Milestone02_Section2_DataIngestion.ipynb"

nb = json.load(open(SRC))
cells = nb["cells"]
text = lambda c: "".join(c["source"])
i2 = next(i for i, c in enumerate(cells) if text(c).startswith("# **Section 2"))
i3 = next(i for i, c in enumerate(cells) if text(c).startswith("# **Section 3"))
build = next(c for c in cells if c["cell_type"] == "code" and "master = build_master()" in text(c))

title = dict(cells[0])
title["source"] = (text(cells[0])
    .replace("# **Milestone 02: Data Preparation, EDA and Hypothesis Report**",
             "# **Milestone 02 — Section 2: Data Ingestion, Cleaning & Structural Readiness**")
    .replace("This notebook is the executable companion to the Milestone 02 PDF (Draft Sections II and III of the manuscript).\n"
             "Every table and figure in the PDF is produced here and written to `data/processed/tables/` and `figures/`.",
             "This notebook covers only Section 2 of the Milestone 02 brief: collection audit, alignment, missing-data strategy,\n"
             "transformations and encoding."))
intro = {"cell_type": "markdown", "metadata": {},
         "source": "## Build the master dataset\nThe master table is rebuilt from the cached raw files so that every check below runs against the same object."}

keep = [title, cells[1], intro, build] + cells[i2:i3]
for c in keep:
    if c["cell_type"] == "code":
        lines = text(c).split("\n")
        c["source"] = "\n".join(l for l in lines if not re.search(r"to_csv\(TABLES|^TABLES = |^FIGS = |master\.to_csv\(ROOT", l))
        c["outputs"] = []
        c["execution_count"] = None
nb["cells"] = keep
json.dump(nb, open(OUT, "w"), indent=1)
print(f"wrote {OUT.name} with {len(keep)} cells")
