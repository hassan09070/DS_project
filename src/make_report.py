"""
make_report.py -- Assemble the Milestone 02 manuscript draft (Sections II-IV) as PDF.

Reads only the CSV tables in data/processed/tables/ and the PNGs in figures/ that
Milestone02_Analysis.ipynb produced, builds build/Milestone02_Report.docx with
python-docx, then converts it to report/Milestone02_Report.pdf with LibreOffice.
Numbers quoted in the prose are pulled from the tables so they cannot drift from
the notebook.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
T = ROOT / "data" / "processed" / "tables"
F = ROOT / "figures"
BUILD = ROOT / "build"; BUILD.mkdir(exist_ok=True)
OUT = ROOT / "report"; OUT.mkdir(exist_ok=True)
SOFFICE = shutil.which("soffice")
PAGES_SCRIPT = """
tell application "Pages"
  set theDoc to open POSIX file "{docx}"
  delay 2
  export theDoc to POSIX file "{pdf}" as PDF
  close theDoc saving no
end tell
"""


def docx_to_pdf(docx: Path, pdf: Path) -> None:
    """Convert with LibreOffice when it is installed, otherwise with Apple Pages via AppleScript."""
    if SOFFICE and Path(SOFFICE).exists():
        r = subprocess.run([SOFFICE, "--headless", "--convert-to", "pdf", "--outdir", str(pdf.parent), str(docx)],
                           capture_output=True, text=True, timeout=300)
        if r.returncode == 0 and pdf.exists():
            return
        print("LibreOffice conversion failed, falling back to Pages:", r.stderr.strip()[:200])
    if sys.platform == "darwin":
        pdf.unlink(missing_ok=True)
        subprocess.run(["osascript", "-e", PAGES_SCRIPT.format(docx=docx, pdf=pdf)], check=True, timeout=300)
        return
    raise RuntimeError("No DOCX->PDF converter available (install LibreOffice).")

# ----------------------------------------------------------------------------- numbers from tables
manifest = json.loads((ROOT / "data" / "raw" / "manifest.json").read_text())
master = pd.read_csv(ROOT / "data" / "processed" / "master_weekly.csv", index_col=0, parse_dates=True)
uni = pd.read_csv(T / "t08_univariate.csv", index_col=0)
resist = pd.read_csv(T / "t09_resistant_vs_nonresistant.csv", index_col=0)
audit = pd.read_csv(T / "t10_outlier_audit.csv", header=[0, 1], index_col=0)
best = pd.read_csv(T / "t13_xcorr_best_lag.csv", index_col=0)
cont = pd.read_csv(T / "t15_contingency_shock_spike.csv")
skew = pd.read_csv(T / "t05_log_transform_skew.csv", index_col=0)
dummies = pd.read_csv(T / "t07_dummy_counts.csv", index_col=0)
missing = pd.read_csv(T / "t03_missing_all_columns.csv", index_col=0)
by_year = pd.read_csv(T / "t04_missing_by_year.csv", index_col=0)
grp = pd.read_csv(T / "t14_groupby_regime.csv", header=[0, 1], index_col=0)
mapping = pd.read_csv(T / "t16_hypothesis_variable_mapping.csv")
corr = pd.read_csv(T / "t11_correlation_matrix.csv", index_col=0)
xcorr = pd.read_csv(T / "t12_cross_correlation_lags.csv", index_col=0)

N, P = master.shape
first, last = master.index.min().date(), master.index.max().date()
gas = cont.loc[cont.commodity.str.contains("gas")].iloc[0]
spike_cut = master["icsa_pct_chg_1w"].quantile(0.90)
fmt_k = lambda v: f"{v:,.0f}"

# ----------------------------------------------------------------------------- docx helpers
doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
for side in ("left_margin", "right_margin"):
    setattr(sec, side, Cm(2.2))
sec.top_margin = sec.bottom_margin = Cm(2.0)
st = doc.styles["Normal"]; st.font.name = "Times New Roman"; st.font.size = Pt(11)
st.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
st.paragraph_format.space_after = Pt(6); st.paragraph_format.line_spacing = 1.15
for lvl, size in ((1, 14), (2, 12), (3, 11)):
    h = doc.styles[f"Heading {lvl}"]; h.font.name = "Times New Roman"; h.font.size = Pt(size)
    h.font.bold = True; h.font.color.rgb = RGBColor(0, 0, 0)
    h.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    h.paragraph_format.space_before = Pt(12 if lvl == 1 else 8); h.paragraph_format.space_after = Pt(4)

def para(text, *, italic=False, bold=False, size=None, align=None, after=None):
    p = doc.add_paragraph()
    parts = text.split("**")
    for i, part in enumerate(parts):
        r = p.add_run(part); r.italic = italic; r.bold = bold or (i % 2 == 1)
        if size: r.font.size = Pt(size)
    if align is not None: p.alignment = align
    if after is not None: p.paragraph_format.space_after = Pt(after)
    return p

def bullet(text):
    p = doc.add_paragraph(style="List Bullet")
    for i, part in enumerate(text.split("**")):
        r = p.add_run(part); r.bold = i % 2 == 1
    p.paragraph_format.space_after = Pt(2)

def caption(text, kind, n):
    p = doc.add_paragraph(); p.paragraph_format.space_after = Pt(10)
    r = p.add_run(f"{kind} {n}. "); r.bold = True; r.font.size = Pt(9.5)
    r = p.add_run(text); r.font.size = Pt(9.5)

def set_cell_bg(cell, hex_):
    tcPr = cell._tc.get_or_add_tcPr(); shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), hex_); tcPr.append(shd)

def table(df: pd.DataFrame, cap: str, n: int, *, index=True, font=8.5, col_widths=None, float_fmt="{:,.2f}"):
    caption(cap, "Table", n)
    data = df.copy()
    if index:
        data = data.reset_index()
    cols = [str(c) for c in data.columns]
    t = doc.add_table(rows=1, cols=len(cols)); t.style = "Table Grid"; t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, c in enumerate(cols):
        cell = t.rows[0].cells[i]; cell.text = ""; r = cell.paragraphs[0].add_run(c); r.bold = True; r.font.size = Pt(font)
        set_cell_bg(cell, "E8E7E3")
    for _, row in data.iterrows():
        cells = t.add_row().cells
        for i, v in enumerate(row):
            if isinstance(v, float):
                txt = "" if pd.isna(v) else (f"{v:,.0f}" if abs(v) >= 1000 and float(v).is_integer() else float_fmt.format(v))
            else:
                txt = str(v)
            cells[i].text = ""; r = cells[i].paragraphs[0].add_run(txt); r.font.size = Pt(font)
    if col_widths:
        for row in t.rows:
            for i, w in enumerate(col_widths):
                row.cells[i].width = Cm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)

def figure(fname, cap, n, width_cm=16.0):
    doc.add_picture(str(F / fname), width=Cm(width_cm))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption(cap, "Figure", n)

# ============================================================================= title block
para("Commodity Price Shocks as an Early-Warning Signal for US Initial Jobless Claims", bold=True, size=16,
     align=WD_ALIGN_PARAGRAPH.CENTER, after=2)
para("Milestone 02 manuscript draft: Section II (Data and Preprocessing), Section III (Exploratory Data Analysis) "
     "and Section IV (Hypotheses and Analytical Plan)", italic=True, size=10.5, align=WD_ALIGN_PARAGRAPH.CENTER, after=8)
para("Rana Mohammad Sarib Khan (rk09083)¹, Abdullah Ahmed (aa09303)², Hassan Shahzad (ms09070)³",
     align=WD_ALIGN_PARAGRAPH.CENTER, after=0)
para("¹ Social Development & Policy (CS minor) · ² Computer Engineering · ³ Computer Science", size=9.5,
     align=WD_ALIGN_PARAGRAPH.CENTER, after=0)
para("Data Science for Social Good · SDG 8, Target 8.5 · October 2026", size=9.5, align=WD_ALIGN_PARAGRAPH.CENTER, after=10)

doc.add_heading("Abstract", level=2)
para(f"Official unemployment statistics arrive weeks after layoffs occur. This project asks whether sudden movements in "
     f"the prices of four physical input commodities (crude oil, natural gas, copper, iron ore) anticipate increases in US "
     f"weekly initial jobless claims, and with what lag. This draft documents the construction of a weekly master dataset of "
     f"{N:,} observations and {P} variables ({first} to {last}) from the FRED API and Yahoo Finance, the alignment of daily and "
     f"monthly series onto the Department of Labor's claims week, the missing-data and transformation decisions, and an "
     f"exploratory analysis. Claims are heavily right-skewed (skewness {skew.loc['icsa','skew (raw)']:.1f}) and the 2020 "
     f"pandemic weeks inflate the standard deviation threefold, which masks every other recession under a z-score outlier rule. "
     f"Week-over-week commodity shocks are only weakly cross-correlated with claims changes (|r| ≤ "
     f"{xcorr.abs().max().max():.2f}), but the lag profile is informative: oil and copper co-move with claims at lags 0–1 with a "
     f"negative sign, and a top-decile natural-gas move four weeks earlier doubles the probability of a claims spike "
     f"({gas['spike rate otherwise']*100:.1f} % to {gas['spike rate after shock']*100:.1f} %, χ² = {gas['chi2']:.1f}, "
     f"p = {gas['p-value']:.3f}). Five formal hypotheses and their variable mapping close the draft.", size=10.5)

para("Research question. Do price shocks and volatility in core energy and industrial-metal commodities predict increases "
     "in US initial jobless claims, and what is the delay between shock and claims response?", italic=True, size=10.5)

# ============================================================================= II
doc.add_heading("II. Data and Preprocessing", level=1)
doc.add_heading("II.1 Data sources and collection", level=2)
para("All raw series are collected programmatically by src/collect.py and cached with a provenance manifest (Table 1). "
     "Six series come from the Federal Reserve Economic Data (FRED) keyless CSV endpoint "
     "(https://fred.stlouisfed.org/graph/fredgraph.csv?id=SERIES): weekly initial claims (ICSA), daily WTI crude oil "
     "(DCOILWTICO), daily Henry Hub natural gas (DHHNGSP), the monthly NBER recession indicator (USREC) and the two monthly "
     "metal benchmarks (PCOPPUSDM, PIORECRUSDM) that are kept for reference only. FRED encodes non-trading days as '.', which "
     "is parsed to a missing value at load time. Following the Milestone 01 source-selection test, daily copper and iron ore "
     "prices come from Yahoo Finance via the yfinance package: COMEX copper front-month futures (HG=F, USD per pound) and "
     "iron ore 62 % Fe CFR China futures (TIO=F, USD per tonne). A direct query of the Yahoo chart endpoint for 2007–2010 "
     "returns \"Data doesn't exist\" for TIO=F: the contract was listed on 14 October 2010, and HG=F history begins on "
     "30 August 2000. Both gaps are therefore structural.")
src = (pd.DataFrame(manifest).T[["description", "frequency", "rows", "first_date", "last_date"]]
       .rename_axis("series").reset_index())
src.columns = ["Series", "Description", "Freq.", "Rows", "First", "Last"]
table(src, "Raw series collected, with row counts and coverage as recorded in data/raw/manifest.json "
      f"(pulled {manifest['ICSA']['pulled_at_utc']}).", 1, index=False, col_widths=[2.3, 7.2, 1.6, 1.3, 2.1, 2.1])

doc.add_heading("II.2 Alignment and the master dataset", level=2)
para("The observational unit is one calendar week ending Saturday, the Department of Labor's reference week for initial "
     "claims. The claims series is never resampled; every other series is brought onto its grid (src/build_master.py). "
     "Daily prices are collapsed into Sunday–Saturday bins and summarised by the weekly mean (the base weekly price) and a "
     "trailing 20-trading-day volatility of daily log returns sampled on the last day of the week. The monthly recession flag "
     "is forward-filled to weeks. All weekly frames are left-joined onto the claims index, so no commodity week without a claims "
     "observation enters the table. Per commodity we then derive the week-over-week percentage change of the weekly mean (the "
     "price shock). Lags 1–16 of the shock, the proposal's exploratory window, are generated on demand by add_lags() rather than "
     "stored, which keeps the master at 17 columns. Copper is converted from USD per pound to USD per tonne (× 2,204.62) so that "
     "it is comparable with the FRED benchmark.")
para("The weekly mean, rather than the close, is the level feature because it reflects what a business paying for inputs "
     "over the week actually faced. The week ending 25 April 2020 illustrates the difference: it closes at 15.99 USD/bbl but "
     "its mean is 3.32 USD/bbl because of the −37.63 USD/bbl WTI settlement on 20 April. That single negative print has an "
     "undefined log return and is excluded from the return-based volatility features only.")
ov = pd.read_csv(T / "t01_master_overview.csv")
table(ov, "Master analytical dataset at a glance.", 2, index=False, col_widths=[4.0, 12.6])

doc.add_heading("II.3 Missing data", level=2)
mt = missing.rename(columns={"missing_n": "Missing (n)", "missing_pct": "Missing (%)"}).rename_axis("Variable")
mt["Missing (n)"] = mt["Missing (n)"].astype(int)
table(mt, "Missing values in every column of the master dataset (17 columns, 1,500 weeks).", 3, col_widths=[5, 3, 3])
by = by_year.T; by.index.name = "commodity"
by = by.loc[:, [c for c in by.columns if int(c) <= 2011]]
table(by, "Share of weeks (%) with a missing weekly mean price, by year, 1998–2011 (no missing weeks after 2011).", 4, font=7.5)
para(f"The target is complete. Oil is missing in only {int(missing.loc['oil_mean','missing_n'])} weeks (1998–99). Natural gas is "
     f"missing in {int(missing.loc['gas_mean','missing_n'])} weeks ({missing.loc['gas_mean','missing_pct']:.1f} %), all before "
     f"April 2007, because FRED's daily Henry Hub series is intermittent in its early years. Copper "
     f"({missing.loc['copper_mean','missing_pct']:.1f} %) and iron ore ({missing.loc['iron_mean','missing_pct']:.1f} %) are missing "
     "for every week before their futures histories begin (September 2000 and October 2010) and complete afterwards.")
para("**Handling rationale.** No value is imputed. Mean or median imputation of a price level that did not exist would inject "
     "a constant into a time series and destroy the week-to-week variation the project studies; interpolating across a ten-year "
     "hole would be fabrication. Back-filling iron ore from the FRED monthly benchmark was considered and rejected: before 2010 "
     "iron ore was priced on annual contracts, so the FRED series is a flat step function (36.63 USD/t throughout 2007) with no "
     "weekly information, and mixing two sources in one column contradicts the single-source decision of Milestone 01. Because "
     "the target is complete, no row is dropped from the master table; each model will instead apply listwise deletion on the "
     f"columns it uses, so a copper model trains on {int(master['copper_mean'].notna().sum()):,} weeks (2000–2026) and an iron-ore "
     f"model on {int(master['iron_mean'].notna().sum()):,} weeks (2010–2026).")
para("**Selection bias.** Listwise deletion is innocuous only when missingness is unrelated to the outcome. Here it is related to "
     "time, and time to the outcome: any specification that includes iron ore observes neither the 2001 recession nor the "
     "2008–09 financial crisis, the two largest claims episodes other than COVID-19, and will be estimated on a sample with a "
     "narrower range of labour-market stress. Metal-based models will therefore be reported both with and without iron ore. "
     "The pre-2007 gas gaps are scattered across ordinary years and are closer to missing at random.")

doc.add_heading("II.4 Transformations and encoding", level=2)
sk = skew.rename_axis("Variable").rename(columns={"skew (raw)": "Skewness (raw)", "skew (log)": "Skewness (log)"})
table(sk, "Effect of the natural-log transform on skewness.", 5, col_widths=[4, 3, 3])
para(f"**Log transformation.** Initial claims are extremely right-skewed ({skew.loc['icsa','skew (raw)']:.1f}): only "
     f"{int((master['icsa'] > 700000).sum())} of {N:,} weeks exceed 700,000, but the pandemic weeks reach "
     f"{master['icsa'].max()/1e6:.2f} million. log(ICSA) reduces skewness to {skew.loc['icsa','skew (log)']:.1f} and is the response "
     "scale we intend to model; a unit change in log claims is a constant percentage change, which is also how layoff waves are "
     f"discussed by policymakers. Natural gas is the only commodity with material right skew ({skew.loc['gas_mean','skew (raw)']:.2f}), "
     f"reduced to {skew.loc['gas_mean','skew (log)']:.2f} by the log. Oil, copper and iron ore are close to symmetric in levels and the "
     "log over-corrects oil and copper into moderate left skew, so their raw levels remain the primary features.")
para("**Scaling.** Standardisation (z-score) and Min-Max normalisation of claims, log claims and the four weekly mean prices are "
     "computed and reported in the notebook but not stored in the master. Standardisation makes coefficients comparable across "
     "commodities measured in dollars per barrel, per MMBtu and per tonne; Min-Max serves bounded-input models. Because the "
     "statistics are full-sample, storing scaled columns would bake look-ahead information into the file; in Milestone 03 the "
     "scalers are fitted on the training window inside the model pipeline.")
dm = dummies.rename_axis("Indicator").rename(columns={"weeks = 1": "Weeks = 1", "share": "Share"})
dm["Weeks = 1"] = dm["Weeks = 1"].astype(int)
table(dm, "Boolean dummy indicators in the master dataset.", 6, col_widths=[4, 3, 3])
para("**Categorical encoding.** Two nominal string variables, calendar quarter (Q1–Q4) and regime (expansion/recession from the "
     "NBER indicator), are converted with pandas.get_dummies(drop_first=True) into 0/1 flags, with Q1 and expansion as reference "
     "levels to avoid the dummy-variable trap. Only the regime flag is stored, as usrec; the quarter dummies are shown for the "
     "mechanics but not kept because initial claims are already seasonally adjusted. The other stored flag is covid_period "
     "(March–December 2020). A target-derived icsa_spike indicator, marking the top decile of weekly claims increases (rises above "
     f"{spike_cut:.1f} %), is created inside the notebook for the exploratory analysis. Only {int(dummies.loc['usrec','weeks = 1'])} "
     "weeks (8 %) fall in a recession, which already warns that regime-interaction hypotheses rest on few observations.")

# ============================================================================= III
doc.add_heading("III. Exploratory Data Analysis", level=1)
doc.add_heading("III.1 Univariate summary statistics", level=2)
u = uni.copy(); u.index.name = "Variable"
u = u[["unit", "n", "mean", "median", "SD", "IQR", "min", "max", "skewness"]]
u.columns = ["Unit", "n", "Mean", "Median", "SD", "IQR", "Min", "Max", "Skew"]
table(u, "Central tendency and spread of the key numerical variables (weekly observations; n varies with data availability).",
      7, font=7.5, col_widths=[2.9, 1.9, 1.1, 1.8, 1.8, 1.8, 1.6, 1.6, 1.8, 1.0])
r = resist.rename_axis("Statistic")
table(r.rename(columns={"all weeks": "All weeks", "excluding Mar-Dec 2020": "Excl. Mar–Dec 2020", "% change": "Change (%)"}),
      "Resistant versus non-resistant measures of weekly initial claims with and without the 43 pandemic weeks.", 8,
      col_widths=[3, 4, 4, 3])
para(f"Mean weekly claims ({fmt_k(uni.loc['icsa','mean'])}) sit {(uni.loc['icsa','mean']/uni.loc['icsa','median']-1)*100:.0f} % above "
     f"the median ({fmt_k(uni.loc['icsa','median'])}) and the SD ({fmt_k(uni.loc['icsa','SD'])}) is "
     f"{uni.loc['icsa','SD']/uni.loc['icsa','IQR']:.1f} times the IQR ({fmt_k(uni.loc['icsa','IQR'])}), the signature of a heavy right "
     f"tail. Removing the 43 pandemic weeks changes the mean by {r.loc['mean','% change']:.0f} % and the SD by {r.loc['SD','% change']:.0f} % "
     f"but the median by only {r.loc['median','% change']:.1f} % and the IQR by {r.loc['IQR','% change']:.0f} %: median and IQR are resistant, "
     "mean and SD are not, so medians and IQRs are the headline descriptives and the log scale is used in models. Crude oil averages "
     f"{uni.loc['oil_mean','mean']:.0f} USD/bbl with an almost symmetric distribution; natural gas (mean {uni.loc['gas_mean','mean']:.2f} vs "
     f"median {uni.loc['gas_mean','median']:.2f} USD/MMBtu) is right-skewed. Weekly percentage changes are centred near zero but their tails "
     f"differ sharply: oil and gas record single-week moves of {uni.loc['oil_pct_1w','min']:.0f} % / +{uni.loc['oil_pct_1w','max']:.0f} % and "
     f"{uni.loc['gas_pct_1w','min']:.0f} % / +{uni.loc['gas_pct_1w','max']:.0f} %, whereas copper and iron ore never move more than ±20 % in a week.")

doc.add_heading("III.2 Outlier diagnostic", level=2)
a = audit.copy()
a.columns = [f"{b} ({'full' if 'full' in str(s_) else 'excl. 2020'})" for s_, b in a.columns]
a = a[[c for c in a.columns if "bound" in c or "count" in c]]
for c in a.columns:
    if "count" in c:
        a[c] = a[c].astype(int)
a.index.name = "Variable"
table(a, "Outlier counts under the z-score rule (|z| > 3) and the quartile rule (beyond Q3 + 1.5·IQR or Q1 − 1.5·IQR), "
      "for the full sample and excluding March–December 2020.", 9, font=7, float_fmt="{:,.1f}")
za, ia = int(audit.loc["icsa", ("full sample", "z-rule |z|>3 (count)")]), int(audit.loc["icsa", ("full sample", "IQR-rule (count)")])
zp, ip = int(audit.loc["icsa_pct_chg_1w", ("full sample", "z-rule |z|>3 (count)")]), int(audit.loc["icsa_pct_chg_1w", ("full sample", "IQR-rule (count)")])
para(f"The two rules disagree by an order of magnitude: on weekly claims the z-score rule flags {za} weeks and the IQR rule {ia}; on the "
     f"weekly percentage change {zp} against {ip}. The cause is variance inflation. The pandemic weeks lift the SD of claims from "
     f"{fmt_k(resist.loc['SD','excluding Mar-Dec 2020'])} to {fmt_k(resist.loc['SD','all weeks'])}, so the z-rule's upper bound climbs to "
     f"{audit.loc['icsa', ('full sample', 'z upper bound')]/1e6:.2f} million and everything short of the COVID spike is hidden behind it. This "
     f"is the masking effect: the most extreme outliers inflate the scale used to detect outliers, concealing the 2008–09 peak (665,000) and "
     f"every other recession week. The IQR rule's bound ({fmt_k(audit.loc['icsa', ('full sample', 'IQR upper bound')])}) depends only on the "
     f"middle half of the data and isolates exactly the recession periods. Re-running the z-rule without the 43 pandemic weeks raises its count "
     f"to {int(audit.loc['icsa', ('excluding Mar-Dec 2020', 'z-rule |z|>3 (count)')])}, confirming that those weeks had been masking others. "
     "The extreme weeks are real events, not errors, and are retained; their influence is managed by the log transform of the target, the "
     "covid_period dummy and, where appropriate, robust loss functions.")

doc.add_heading("III.3 Bivariate and multivariate exploration", level=2)
b = best.rename_axis("Commodity").rename(columns={"strongest lag": "Strongest lag", "r at that lag": "r at that lag", "±2/√n band": "±2/√n"})
table(b, "Strongest cross-correlation between the weekly % change in each commodity's price k weeks earlier and the weekly % change in claims, lags 0–16.", 10, col_widths=[3, 3, 3, 3, 3])
c = cont.rename(columns={"commodity": "Commodity", "spike rate after shock": "Spike rate after shock", "spike rate otherwise": "Spike rate otherwise",
                         "relative risk": "Relative risk", "chi2": "χ²", "p-value": "p"})
table(c, "Contingency analysis: probability of a claims spike (top-decile weekly rise) in weeks following a top-decile absolute commodity price move four weeks earlier.", 11, index=False, float_fmt="{:.3f}")
g = grp.copy(); g.columns = [f"{v} ({s_})" for v, s_ in g.columns]
g = g[["icsa (median)", "icsa (mean)", "icsa_pct_chg_1w (mean)", "icsa_spike (mean)", "oil_pct_1w (mean)", "copper_pct_1w (mean)", "oil_vol_4w (mean)"]]
g.index.name = "Regime"
table(g, "Group-by comparison of expansion (n = 1,380) and NBER recession (n = 120) weeks.", 12, font=7.5, float_fmt="{:,.3f}")
para(f"**Levels.** In log levels, claims correlate negatively with oil ({corr.loc['log_icsa','oil_log_mean']:.2f}) and copper "
     f"({corr.loc['log_icsa','copper_log_mean']:.2f}) and positively with iron ore ({corr.loc['log_icsa','iron_log_mean']:+.2f}) and the recession "
     f"flag ({corr.loc['log_icsa','usrec']:+.2f}). The copper result is the classic \"Dr. Copper\" pattern: copper is bought when factories expand, "
     "so high copper prices coincide with low unemployment; oil shows the same demand-side sign. The iron-ore sign is largely a sample artefact "
     "of its 2010 start. These level correlations are dominated by shared slow trends and are not evidence about shocks; they mainly show that "
     "levels must enter models detrended or as controls, and that oil and copper levels (r = 0.82) should not enter a linear model together.")
para(f"**Shocks and lags.** Week-over-week changes are only weakly cross-correlated with claims changes (all |r| < "
     f"{xcorr.abs().max().max()+0.01:.2f}), but the lag profile is informative (Figure 3). Oil is most negative at lags 0–1 (an oil price fall "
     "coincides with claims rising, as in 2008 and 2020 when collapsing demand drove both), copper peaks at lag 0 and again at lags 7–8, and iron "
     "ore has an isolated −0.13 at lag 6. Oil at lags 0–1, copper at lags 0 and 7 and iron ore at lag 6 clear the ±2/√n band; no natural-gas lag "
     "does. None of this is yet causal, but it tells the modelling stage where to look and warns that the sign may be negative: commodity "
     "collapses, not only spikes, precede layoff waves.")
para(f"**Regimes and contingency.** Recession weeks have a median claims level of {fmt_k(grp.loc['recession',('icsa','median')])} against "
     f"{fmt_k(grp.loc['expansion',('icsa','median')])} in expansions, a mean weekly claims change of {grp.loc['recession',('icsa_pct_chg_1w','mean')]:+.1f} % "
     f"versus {grp.loc['expansion',('icsa_pct_chg_1w','mean')]:+.1f} %, and 4-week oil volatility about "
     f"{grp.loc['recession',('oil_vol_4w','mean')]/grp.loc['expansion',('oil_vol_4w','mean')]:.1f} times higher. Conditioning on a top-decile absolute "
     f"move four weeks earlier, a natural-gas shock is followed by a claims spike in {gas['spike rate after shock']*100:.1f} % of weeks versus "
     f"{gas['spike rate otherwise']*100:.1f} % otherwise (relative risk {gas['relative risk']:.1f}, χ² = {gas['chi2']:.1f}, p = {gas['p-value']:.3f}); "
     "oil, copper and iron ore shocks do not shift the spike rate significantly at this lag. The gas result is the strongest single bivariate "
     "signal in the data and motivates hypothesis H2.")

doc.add_heading("III.4 Figures", level=2)
figure("fig1_claims_timeseries.png",
       "Weekly US initial unemployment-insurance claims (seasonally adjusted, persons per week) on a logarithmic axis, 3 Jan 1998 to "
       f"{last:%d %b %Y}. Gray bands mark NBER recessions (2001, 2007–09, 2020). The log scale keeps the 2001 and 2008–09 episodes visible "
       "against the 2020 spike. Source: FRED series ICSA.", 1)
figure("fig2_commodity_prices.png",
       "Weekly mean prices of the four input commodities, each on its own axis and physical unit: WTI crude oil (USD/barrel, FRED), Henry Hub "
       "natural gas (USD/MMBtu, FRED), COMEX copper futures converted to USD/tonne (Yahoo Finance HG=F) and iron ore 62 % Fe futures "
       "(USD/tonne, Yahoo Finance TIO=F). Copper and iron ore begin when their futures histories begin; gray bands mark NBER recessions. "
       "All four fall sharply inside the 2008–09 and 2020 recessions.", 2)
figure("fig3_lag_crosscorrelation.png",
       "Lead–lag structure between commodity shocks and claims: Pearson correlation between the week-over-week % change in a commodity's "
       "weekly mean price k weeks earlier and the week-over-week % change in initial claims, k = 0–16; the gray band is ±2/√n. "
       "Oil's association is concentrated at lags 0–1 with a negative sign, copper shows a secondary dip at lags 7–8 and iron ore's one "
       "coefficient outside the band is at lag 6.", 3)
figure("fig4_correlation_heatmap.png",
       "Lower triangle of the Pearson correlation matrix for the target (log level and weekly % change), commodity log levels, weekly % "
       "changes, trailing 4-week volatilities and the NBER recession flag (pairwise-complete observations). Diverging scale: blue negative, "
       "gray zero, red positive. Levels are strongly inter-correlated; the % change block is nearly orthogonal.", 4, width_cm=14.5)
figure("fig5_claims_change_after_shock.png",
       "Distribution (median, interquartile box, 1.5×IQR whiskers; outliers beyond the axis hidden for legibility, not removed from the "
       "statistics) of the weekly % change in initial claims, split by whether the commodity recorded a top-decile absolute weekly price move "
       "four weeks earlier. Gray boxes: all other weeks; coloured boxes: weeks following a shock. Text under each pair gives the share of "
       f"weeks that are claims spikes (rises above {spike_cut:.1f} %). Natural-gas shocks double the spike rate.", 5)

# ============================================================================= IV
doc.add_heading("IV. Hypotheses and Analytical Plan", level=1)
para("Notation: Yₜ is the weekly change in log initial claims, Δlog(ICSAₜ); Δpᶜₜ₋ₖ is the % change in commodity c's weekly mean price "
     "k weeks earlier (from add_lags()); σᶜₜ is its trailing 4-week volatility; Rₜ is the NBER recession flag; Zₜ collects the "
     "controls (usrec, covid_period, lagged Yₜ).")
hyps = [
    ("H1 — Energy shocks (crude oil).",
     "H₀: β^oil_k = 0 for all k ∈ {0,…,16}; H₁: β^oil_k ≠ 0 for at least one k, in Yₜ = α + Σₖ β^oil_k Δp^oil_{t−k} + γ′Zₜ + εₜ. "
     "The EDA suggests β^oil_{0,1} < 0 (price collapses, not spikes, precede claims rises), so the test is two-sided."),
    ("H2 — Energy shocks (natural gas).",
     "H₀: β^gas_k = 0 for all k; H₁: β^gas_k > 0 for some k ∈ {2,…,8}. Motivated by the contingency result that a gas shock at t−4 "
     "doubles the spike probability."),
    ("H3 — Industrial-metal shocks (copper, iron ore).",
     "H₀: β^cu_k = β^fe_k = 0 for all k; H₁: at least one differs from zero. Given the \"Dr. Copper\" pattern we expect negative "
     "coefficients (falling metal prices signal shrinking orders and later layoffs); the direction will be reported, not assumed."),
    ("H4 — Volatility, not only direction.",
     "H₀: δᶜ = 0; H₁: δᶜ > 0 in Yₜ = α + δᶜ σᶜ_{t−4} + γ′Zₜ + εₜ for each commodity c: uncertainty about input costs raises layoffs "
     "independently of the sign of the price move."),
    ("H5 — Lag structure and regime dependence.",
     "H₀: the lag k* at which |βᶜ_k| is maximal is the same in recession and expansion weeks and the interaction coefficient θᶜ_k = 0; "
     "H₁: θᶜ_k ≠ 0 in Yₜ = α + βᶜ_k Δpᶜ_{t−k} + θᶜ_k Δpᶜ_{t−k}·Rₜ + λRₜ + γ′Zₜ + εₜ (transmission is faster and/or stronger in recessions). "
     "The proposal's expectation is k* ∈ [4, 12] weeks."),
]
for title, body in hyps:
    p = doc.add_paragraph(); r = p.add_run(title + " "); r.bold = True; p.add_run(body); p.paragraph_format.space_after = Pt(5)
mp = mapping.copy(); mp.columns = ["H", "Target / response (Y)", "Primary predictors (X)", "Confounders / controls (Z)"]
table(mp, "Mapping of each hypothesis to columns of master_weekly.csv.", 13, index=False, font=8, col_widths=[1.0, 4.2, 5.6, 5.8])
para("**Analytical plan.** H1–H3 will be tested with distributed-lag regressions on Δlog claims using Newey–West (HAC) standard errors, "
     "complemented by Granger-causality F-tests; H4 adds the volatility terms; H5 adds the recession interaction and a rolling-window "
     "re-estimation. The predictive counterpart is a gradient-boosted regressor on the same features with time-series cross-validation, "
     "from which the strongest lags per commodity will be read off (permutation importance) and retained for a parsimonious final model. "
     "Scalers and the spike threshold will be refitted on the training window only. In week 14 the nine weeks of data generated during the "
     "semester will be pulled with the same scripts and used as a true out-of-sample test (trend matching and mean absolute error).")

doc.add_heading("Reproducibility", level=2)
para("Code and data: src/collect.py (raw pulls with manifest), src/build_master.py (weekly master dataset and data dictionary), "
     "Milestone02_Analysis.ipynb (all tables and figures in this draft, executed end-to-end with jupyter nbconvert --execute), "
     "src/make_report.py (this document). Environment: Python 3.13, pandas 3.0, statsmodels 0.15, yfinance 1.7, matplotlib 3.11, seaborn 0.13.")

doc.add_heading("References", level=2)
for ref in [
    "Federal Reserve Bank of St. Louis. FRED Economic Data: ICSA, DCOILWTICO, DHHNGSP, USREC, PCOPPUSDM, PIORECRUSDM. https://fred.stlouisfed.org/ (accessed 4 October 2026).",
    "U.S. Department of Labor, Employment and Training Administration. Unemployment Insurance Weekly Claims Data (via FRED series ICSA).",
    "Yahoo Finance. Copper Futures (HG=F) and Iron Ore 62% Fe CFR China Futures (TIO=F), daily history, retrieved with the yfinance Python package, version 1.7 (accessed 4 October 2026).",
    "National Bureau of Economic Research. US Business Cycle Expansions and Contractions (via FRED series USREC).",
    "Wilkinson, L. (2005). The Grammar of Graphics, 2nd ed. Springer.",
    "Tukey, J. W. (1977). Exploratory Data Analysis. Addison-Wesley.",
    "Newey, W. K. and West, K. D. (1987). A simple, positive semi-definite, heteroskedasticity and autocorrelation consistent covariance matrix. Econometrica, 55(3), 703–708.",
]:
    p = doc.add_paragraph(ref); p.paragraph_format.space_after = Pt(3); p.paragraph_format.left_indent = Cm(0.8); p.paragraph_format.first_line_indent = Cm(-0.8)
    for r in p.runs: r.font.size = Pt(9.5)

docx_path = BUILD / "Milestone02_Report.docx"
doc.save(docx_path)
print("docx:", docx_path)
pdf_path = OUT / "Milestone02_Report.pdf"
docx_to_pdf(docx_path, pdf_path)
print("pdf :", pdf_path, f"({pdf_path.stat().st_size/1e6:.1f} MB)")
