"""
COMP702 — Recompute Data Freshness Against Statutory Due Date
=================================================================
Author:  Thinzar Aung (201942837)
Project: AI-Powered SME Financial Health Analyser for Liverpool

WHY THIS EXISTS:
  The proposal (Requirement R9) states freshness would be "assessed
  against the statutory filing deadline rather than a fixed time
  threshold, since small companies filing annually within the legal
  window should not be flagged as a concern."

  The original implementation didn't actually do this — it used a
  flat 9/18-month cutoff from the last filing date, regardless of
  when that specific company's accounts are actually due. This
  risks mislabelling a company as "stale" when it's simply mid-way
  through its normal, legal annual filing cycle and hasn't reached
  its next deadline yet.

  Stage 2 already captures each company's actual due date
  (next_accounts_due) — it just wasn't being used. This script
  recomputes freshness properly using that field, already sitting
  in output/stage2_with_filing_links.csv. No re-verification or
  re-scraping needed.

NEW FRESHNESS CATEGORIES (replacing the old FRESH/CAUTION/STALE):
  ON TRACK   — next accounts not yet due; company is filing within
               its normal, legal annual cycle. NOT a cause for
               concern, regardless of how long ago the last filing was.
  DUE SOON   — next accounts due within 60 days.
  OVERDUE    — past the statutory due date. This is the only
               category that represents a genuine filing concern.
  UNKNOWN    — no due date available to assess against.

HOW TO RUN:
  python recompute_freshness.py
"""

import os
import sqlite3
import pandas as pd
from datetime import datetime

DB_PATH = "output/liverpool_sme_analyser.db"
SOURCE_CSV = "output/stage2_with_filing_links.csv"
DUE_SOON_WINDOW_DAYS = 60


def classify_freshness(due_date_str):
    if not due_date_str or str(due_date_str).lower() in ("nan", "none", ""):
        return "UNKNOWN", None

    try:
        due_date = datetime.strptime(str(due_date_str)[:10], "%Y-%m-%d")
    except ValueError:
        return "UNKNOWN", None

    days_until_due = (due_date - datetime.now()).days

    if days_until_due < 0:
        return f"OVERDUE — {abs(days_until_due)} days past due", days_until_due
    elif days_until_due <= DUE_SOON_WINDOW_DAYS:
        return f"DUE SOON — due in {days_until_due} days", days_until_due
    else:
        return "ON TRACK — within normal filing window", days_until_due


def recompute():
    print("\n" + "=" * 65)
    print("  COMP702 — RECOMPUTE DATA FRESHNESS (statutory due date)")
    print(f"  Generated: {datetime.now().strftime('%d %B %Y %H:%M')}")
    print("=" * 65)

    if not os.path.exists(SOURCE_CSV):
        print(f"\n  \u2717 {SOURCE_CSV} not found.")
        return

    df = pd.read_csv(SOURCE_CSV, dtype=str)
    print(f"\n  Loaded {len(df):,} companies from {SOURCE_CSV}")

    if "next_accounts_due" not in df.columns:
        print("  \u2717 'next_accounts_due' column not found — cannot recompute.")
        return

    results = df["next_accounts_due"].apply(classify_freshness)
    df["new_freshness_flag"] = results.apply(lambda r: r[0])
    df["days_until_due"] = results.apply(lambda r: r[1])

    print(f"\n  NEW FRESHNESS DISTRIBUTION (statutory-due-date based):")
    # Group by the category prefix (before the em-dash detail) for a clean summary
    category = df["new_freshness_flag"].str.split(" — ").str[0]
    for cat, count in category.value_counts().items():
        pct = count / len(df) * 100
        print(f"    {cat}: {count:,} ({pct:.1f}%)")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(companies)")
    existing_cols = [row[1] for row in cur.fetchall()]
    if "next_accounts_due" not in existing_cols:
        cur.execute("ALTER TABLE companies ADD COLUMN next_accounts_due TEXT")
    if "days_until_due" not in existing_cols:
        cur.execute("ALTER TABLE companies ADD COLUMN days_until_due INTEGER")

    updates = [
        (row["new_freshness_flag"], row.get("next_accounts_due", ""),
         row["days_until_due"], row["company_number"])
        for _, row in df.iterrows()
    ]
    cur.executemany("""
        UPDATE companies
        SET data_freshness_flag = ?, next_accounts_due = ?, days_until_due = ?
        WHERE company_number = ?
    """, updates)
    conn.commit()
    conn.close()

    print(f"\n  \u2713 Updated {len(updates):,} companies in the database")
    print("=" * 65)
    print("  DONE — restart Stage 5 to see corrected freshness labels")
    print("=" * 65)


if __name__ == "__main__":
    recompute()
