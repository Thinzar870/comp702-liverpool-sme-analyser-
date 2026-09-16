"""
COMP702 — Finalize Stage 3 Outputs From Live Checkpoint
==========================================================
Author:  Thinzar Aung (201942837)
Project: AI-Powered SME Financial Health Analyser for Liverpool

WHY THIS EXISTS:
  stage3_parse_ixbrl.py only calls save_outputs() — which writes
  stage3_financial_data.csv, stage3_with_financials.csv, the
  parsing log, and the summary report — once, at the very end of
  a FULLY COMPLETED run.

  If you stop the run early (e.g. because the real pace turned out
  much slower than the printed estimate), none of those final
  files get written, even though output/stage3_progress.csv (the
  live checkpoint, saved every 20 companies) already contains the
  exact same per-filing data — company info, download status,
  parse method, and every extracted financial figure.

  This script reads stage3_progress.csv and reproduces everything
  save_outputs() would have produced, so you can stop the run
  whenever you choose and still get a complete, valid dataset to
  feed into Stage 4 — no data loss, no waiting for full completion.

HOW TO RUN:
  Stop stage3_parse_ixbrl.py (Ctrl+C, wait for it to exit cleanly),
  then run:
    python finalize_stage3_demo.py
"""

import os
import json
import pandas as pd
from datetime import datetime

PROGRESS_PATH = "output/stage3_progress.csv"


def finalize():
    print("\n" + "=" * 60)
    print("  COMP702 — FINALIZE STAGE 3 OUTPUTS FROM CHECKPOINT")
    print(f"  Generated: {datetime.now().strftime('%d %B %Y %H:%M')}")
    print("=" * 60)

    if not os.path.exists(PROGRESS_PATH):
        print(f"\n  ✗ {PROGRESS_PATH} not found — has Stage 3 started yet?")
        return

    results_df = pd.read_csv(PROGRESS_PATH, dtype={"company_number": str})
    print(f"\n  Loaded {len(results_df):,} filing rows from {PROGRESS_PATH}")
    n_companies = results_df["company_number"].nunique()
    print(f"  Covering {n_companies:,} unique companies")

    # ── Main structured dataset (same as save_outputs) ──────────
    csv_path = "output/stage3_financial_data.csv"
    results_df.to_csv(csv_path, index=False)
    print(f"\n  ✓ Financial data CSV: {csv_path} ({len(results_df):,} rows)")

    # ── Only rows with actual financial data ────────────────────
    financial_cols = ["turnover", "gross_profit", "current_ratio",
                       "net_margin_pct", "health_score"]
    present_cols = [c for c in financial_cols if c in results_df.columns]
    if present_cols:
        has_data = results_df[results_df[present_cols].notna().any(axis=1)]
    else:
        has_data = results_df.iloc[0:0]
    has_data.to_csv("output/stage3_with_financials.csv", index=False)
    print(f"  ✓ Rows with financial data: {len(has_data):,}")

    # ── Parse method breakdown (derived directly from checkpoint,
    #    no separate parsing_log needed — same underlying data) ──
    parsed_count = 0
    failed_count = 0
    pdf_count = 0
    if "parse_method" in results_df.columns:
        methods = results_df["parse_method"].value_counts()
        print(f"\n  PARSING METHOD BREAKDOWN:")
        for method, count in methods.items():
            print(f"    {method}: {count:,}")
        parsed_count = int(
            methods.get("ixbrlparse", 0) + methods.get("beautifulsoup", 0)
        )
        failed_count = int(methods.get("parse_failed", 0))
        pdf_count = int(methods.get("pdf_skipped", 0))

    # ── Health rating distribution ───────────────────────────────
    if "health_rating" in results_df.columns:
        ratings = results_df["health_rating"].value_counts()
        print(f"\n  HEALTH RATING DISTRIBUTION:")
        for rating, count in ratings.items():
            pct = count / len(results_df) * 100
            print(f"    {rating}: {count:,} ({pct:.1f}%)")

    # ── Financial summary statistics ─────────────────────────────
    numeric_cols = ["turnover", "gross_profit", "profit_before_tax",
                     "current_ratio", "gross_margin_pct", "health_score"]
    available = [c for c in numeric_cols if c in results_df.columns]
    if available:
        print(f"\n  FINANCIAL SUMMARY (companies with data):")
        for col in available:
            col_data = pd.to_numeric(results_df[col], errors="coerce").dropna()
            if len(col_data) > 0:
                print(f"    {col}:")
                print(f"      Mean:   {col_data.mean():>12,.2f}")
                print(f"      Median: {col_data.median():>12,.2f}")
                print(f"      Count:  {len(col_data):>12,}")

    # ── Summary report ────────────────────────────────────────────
    with open("output/stage3_parsing_report.txt", "w") as f:
        f.write("=" * 60 + "\n")
        f.write("COMP702 — STAGE 3 PARSING REPORT (early-stopped run)\n")
        f.write("AI-Powered SME Financial Health Analyser for Liverpool\n")
        f.write(f"Thinzar Aung (201942837)\n")
        f.write(f"Generated: {datetime.now().strftime('%d %B %Y %H:%M')}\n")
        f.write("=" * 60 + "\n\n")
        f.write(
            "NOTE: this run was stopped before processing the full demo\n"
            "sample, due to the real per-company rate being far slower\n"
            "than the script's initial estimate (oldest-incorporated\n"
            "companies have unusually large filing histories). This\n"
            "report reflects only the companies actually completed.\n\n"
        )
        f.write("PARSING RESULTS\n" + "-" * 40 + "\n")
        f.write(f"Companies completed:         {n_companies:,}\n")
        f.write(f"Total filing rows processed: {len(results_df):,}\n")
        f.write(f"Successfully parsed:         {parsed_count:,}\n")
        f.write(f"PDF only (no iXBRL):         {pdf_count:,}\n")
        f.write(f"Parse failed:                {failed_count:,}\n")
        if len(results_df) > 0:
            f.write(
                f"Parse success rate:          "
                f"{parsed_count / len(results_df) * 100:.1f}%\n\n"
            )
        f.write("FINANCIAL FIELDS EXTRACTED\n" + "-" * 40 + "\n")
        for col in available:
            col_data = pd.to_numeric(results_df[col], errors="coerce").dropna()
            f.write(f"{col}: {len(col_data):,} rows have this field\n")
        f.write("\nNEXT STEP — STAGE 4\n" + "-" * 40 + "\n")
        f.write("Feed stage3_financial_data.csv into Stage 4 as normal.\n")

    print(f"\n  ✓ Summary report saved: output/stage3_parsing_report.txt")
    print("\n" + "=" * 60)
    print(f"  DONE — {n_companies:,} companies ready for Stage 4")
    print("=" * 60)


if __name__ == "__main__":
    finalize()
