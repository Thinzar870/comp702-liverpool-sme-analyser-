# AI-Powered SME Financial Health Analyser for the Liverpool City Region

**COMP702 MSc Dissertation Project**
Thinzar Aung (201942837) — University of Liverpool
Supervisor: Dr Olga Anosova — Second Marker: Tony McCabe

## Overview

This project builds a working pipeline that identifies every active company
registered at Companies House with a Liverpool City Region postcode,
retrieves and parses their filed financial accounts (iXBRL format), and
presents a derived Financial Health Score for each through a searchable web
application. All data is sourced from Companies House under the Open
Government Licence.

Beyond the pipeline itself, a significant part of this project is a
systematic investigation of real-world data-quality problems in Companies
House's iXBRL filings — see **Data Quality Findings** below.

## Project status

This is a working prototype, not a finished, fully-scaled product:

- **88,679** Liverpool City Region companies verified as active (Stage 2)
- **66,769** of those have a usable iXBRL filing link (75.3%)
- **25,500** companies processed and checkpointed at time of writing (38.2%
  of the 66,769 target) — the pipeline is designed to be resumed and
  extended to full coverage without any code changes
- **44,052** financial ratio records computed
- Web application (Stage 5) runs locally via Streamlit; not yet publicly
  deployed (see dissertation Section 7 for the deployment plan)

## Pipeline architecture

Five independent, checkpointed stages, each re-runnable on its own:

| Stage | Script | Purpose |
|---|---|---|
| 1 | `stage1_build_liverpool_list.py` | Filters the Companies House bulk CSV by Liverpool City Region postcode and company type to build a candidate list |
| 2 | `stage2_api_verification.py` | Verifies each candidate against the live Companies House REST API; retrieves filing links |
| 3 | `stage3_parse_ixbrl.py` | Downloads and parses each company's iXBRL accounts documents |
| 4 | `stage4_database.py` | Pre-processes and loads everything into a SQLite database |
| 5 | `stage5_app.py` | Streamlit web application for searching and viewing company financial profiles |

Each stage checkpoints its progress every 20 companies, so a stage can be
stopped and resumed at any time with zero data loss — a deliberate design
choice given this pipeline was developed on shared, non-persistent
university infrastructure.

## Setup

```bash
pip install -r requirements.txt
```

Requires Python 3.10+.

## Running the pipeline

Run each stage in order. Each will automatically resume from its last
checkpoint if interrupted and re-run:

```bash
python stage1_build_liverpool_list.py
python stage2_api_verification.py
python stage3_parse_ixbrl.py      # slowest stage — can take many hours
python stage4_database.py
python -m streamlit run stage5_app.py
```

If Stage 3 is stopped before completing the full target, run
`finalize_stage3_demo.py` to produce a complete, valid dataset from
whatever has been checkpointed so far, so Stage 4 can proceed without
waiting for a full run.

## Data quality findings

A significant methodological contribution of this project is the discovery,
diagnosis, and (where feasible) correction of five distinct systematic
defects in the extracted financial data — full detail is in the
dissertation's Section 6. In brief:

1. **Total Assets tag-mapping error** — corrupted debt-to-equity for a
   large subset of filings; fixed via `recompute_health_scores.py`.
2. **Data freshness misclassification** — used a flat cutoff instead of
   each company's actual statutory filing deadline; fixed via
   `recompute_freshness.py`.
3. **Current liabilities tag-mapping defect** — implausibly small values
   inflating current ratios; guarded against in `stage4_database.py`.
4. **Net-current-assets fallback** — micro-entity filings with only a
   combined balance-sheet line producing a false current ratio of exactly
   1.0; affects ~8.4% of rows (see `check_bug4_scale.py`).
5. **Adjacent balance-sheet subtotal confusion** — found only through
   manual verification against original filings, not detectable by any
   automated check; the highest-priority item for future work.

**Important:** `recompute_health_scores.py` and `recompute_freshness.py`
must be re-run after every `stage4_database.py` run, since Stage 4 rebuilds
the database from scratch and will silently revert both corrections
otherwise.

## Helper / diagnostic scripts

- `check_progress.py`, `check_current_ratio_outliers.py`,
  `check_guard_impact.py`, `check_bug4_scale.py` — diagnostic tools used to
  investigate and quantify the data-quality defects above
- `make_verification_worksheet.py` — generates a sample of companies for
  manual verification against original Companies House filings
- `database_viewer.py`, `csv_export.py` — utilities for inspecting the
  database and exporting data

## Data and ethics

All data used is publicly available Companies House data under the Open
Government Licence. No human participants were involved in this project
(data category A0). See the dissertation's Section 9 for full detail.

## Tech stack

Python, pandas, requests, BeautifulSoup4 + lxml (iXBRL parsing),
ixbrlparse, SQLite, Streamlit.
