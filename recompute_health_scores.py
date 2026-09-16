"""
COMP702 — Recompute Health Scores (Excluding Corrupted Debt-to-Equity)
=========================================================================
Author:  Thinzar Aung (201942837)
Project: AI-Powered SME Financial Health Analyser for Liverpool

WHY THIS EXISTS:
  Testing surfaced a systematic Stage 3 tag-mapping issue: the "total
  assets" XBRL tag is being mismatched for a large share of filings,
  producing totals far smaller than Current Assets alone — which is
  mathematically impossible. This corrupts debt_to_equity for those
  filings (extreme values like 605, 3790, 671 instead of a normal
  0-3 range).

  The health_score formula treats any debt_to_equity > 3.0 as a red
  flag (-10 points) — so these corrupted values were silently
  penalising scores across a large share of the dataset, skewing
  "AT RISK" ratings that may not reflect real financial health.

  This script recomputes health_score and health_rating for every
  row already in financial_ratios, using the SAME scoring logic as
  Stage 3, but EXCLUDING debt_to_equity from the calculation when it
  fails a basic sanity check — rather than letting a corrupted
  number silently bias the score. No re-parsing or re-downloading
  needed; everything required is already in the database.

HOW TO RUN:
  python recompute_health_scores.py
"""

import sqlite3
from datetime import datetime

DB_PATH = "output/liverpool_sme_analyser.db"

# Same threshold used in the Stage 5 display guard, for consistency.
DEBT_TO_EQUITY_SANITY_LIMIT = 50


def is_debt_to_equity_plausible(de, current_assets, total_assets):
    if de is None:
        return False
    if de > DEBT_TO_EQUITY_SANITY_LIMIT:
        return False
    if current_assets is not None and total_assets is not None:
        if current_assets > total_assets * 1.05:
            return False
    return True


def recompute_score(current_ratio, gross_margin_pct, debt_to_equity,
                     current_assets, total_assets):
    """Same additive scoring logic as Stage 3, but skips
    debt_to_equity entirely when it fails the sanity check, instead
    of letting a corrupted value penalise the score."""
    score = 50
    fields_used = 0

    if current_ratio is not None:
        fields_used += 1
        if current_ratio > 2.0:
            score += 15
        elif current_ratio > 1.5:
            score += 10
        elif current_ratio < 1.0:
            score -= 20

    if gross_margin_pct is not None:
        fields_used += 1
        if gross_margin_pct > 30:
            score += 15
        elif gross_margin_pct > 15:
            score += 8
        elif gross_margin_pct < 0:
            score -= 20

    if is_debt_to_equity_plausible(debt_to_equity, current_assets, total_assets):
        fields_used += 1
        if debt_to_equity < 0.5:
            score += 10
        elif debt_to_equity < 1.5:
            score += 5
        elif debt_to_equity > 3.0:
            score -= 10

    if fields_used < 2:
        return None, "INSUFFICIENT DATA", fields_used

    final_score = max(0, min(100, score))
    if final_score >= 70:
        rating = "HEALTHY"
    elif final_score >= 50:
        rating = "MODERATE"
    else:
        rating = "AT RISK"

    return final_score, rating, fields_used


def recompute():
    print("\n" + "=" * 60)
    print("  COMP702 — RECOMPUTE HEALTH SCORES")
    print(f"  Generated: {datetime.now().strftime('%d %B %Y %H:%M')}")
    print("=" * 60)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Pull ratios joined with the matching financial_data row (same
    # company + balance sheet date) so we can check current/total
    # assets for the sanity check.
    cur.execute("""
        SELECT r.id, r.company_number, r.balance_sheet_date,
               r.current_ratio, r.gross_margin_pct, r.debt_to_equity,
               f.current_assets, f.total_assets, r.health_rating
        FROM financial_ratios r
        LEFT JOIN financial_data f
            ON r.company_number = f.company_number
            AND r.balance_sheet_date = f.balance_sheet_date
    """)
    rows = cur.fetchall()
    print(f"\n  Loaded {len(rows):,} ratio records")

    changed = 0
    now_at_risk_to_other = 0
    other_to_at_risk = 0
    updates = []

    for row in rows:
        (rid, company_number, bsd, current_ratio, gross_margin_pct,
         debt_to_equity, current_assets, total_assets,
         old_rating) = row

        new_score, new_rating, fields_used = recompute_score(
            current_ratio, gross_margin_pct, debt_to_equity,
            current_assets, total_assets
        )

        if new_rating != old_rating:
            changed += 1
            if old_rating == "AT RISK" and new_rating != "AT RISK":
                now_at_risk_to_other += 1
            elif old_rating != "AT RISK" and new_rating == "AT RISK":
                other_to_at_risk += 1

        updates.append((new_score, new_rating, fields_used, rid))

    cur.executemany("""
        UPDATE financial_ratios
        SET health_score = ?, health_rating = ?
        WHERE id = ?
    """, [(score, rating, rid) for (score, rating, _, rid) in updates])
    conn.commit()

    print(f"\n  ✓ Recomputed {len(updates):,} health scores")
    print(f"  Ratings changed: {changed:,} of {len(rows):,} "
          f"({changed / len(rows) * 100:.1f}%)" if rows else "")
    print(f"    AT RISK → healthier rating: {now_at_risk_to_other:,}")
    print(f"    Other → AT RISK: {other_to_at_risk:,}")

    # New distribution
    cur.execute("""
        SELECT health_rating, COUNT(*) FROM financial_ratios
        GROUP BY health_rating ORDER BY COUNT(*) DESC
    """)
    print(f"\n  NEW HEALTH RATING DISTRIBUTION:")
    for rating, count in cur.fetchall():
        print(f"    {rating}: {count:,}")

    conn.close()
    print("\n" + "=" * 60)
    print("  DONE — restart Stage 5 to see corrected scores")
    print("=" * 60)


if __name__ == "__main__":
    recompute()
