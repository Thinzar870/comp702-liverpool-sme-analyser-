"""
Generates a manual-verification worksheet (R6) with a diverse sample of
8 companies and their pipeline-extracted values pre-filled, so you only
need to look each one up on Companies House and fill in the real figures.

Run: python make_verification_worksheet.py
Output: output/verification_worksheet.csv
"""
import sqlite3
import csv

DB_PATH = "output/liverpool_sme_analyser.db"
OUT_PATH = "output/verification_worksheet.csv"

RATINGS = ["HEALTHY", "MODERATE", "AT RISK", "INSUFFICIENT DATA"]
PER_RATING = 2

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Figure out the real column name for "accounts type" on the companies table
# rather than guessing again.
cur.execute("PRAGMA table_info(companies)")
companies_cols = [row[1] for row in cur.fetchall()]
accounts_type_col = next(
    (c for c in companies_cols if "accounts_type" in c.lower()), None
)
type_select = f"c.{accounts_type_col}," if accounts_type_col else "'' AS accounts_type,"

rows = []
for rating in RATINGS:
    cur.execute(f"""
        SELECT c.company_name, c.company_number, {type_select}
               f.balance_sheet_date, f.turnover, f.gross_profit,
               f.current_assets, f.current_liabilities, f.net_assets,
               r.current_ratio, r.gross_margin_pct, r.health_score, r.health_rating
        FROM companies c
        JOIN financial_data f ON c.company_number = f.company_number
        JOIN financial_ratios r ON c.company_number = r.company_number
                                AND f.balance_sheet_date = r.balance_sheet_date
        WHERE r.health_rating = ?
        ORDER BY RANDOM()
        LIMIT ?
    """, (rating, PER_RATING))
    rows.extend(cur.fetchall())

headers = [
    "company_name", "company_number", "accounts_type", "balance_sheet_date",
    "PIPELINE_turnover", "PIPELINE_gross_profit", "PIPELINE_current_assets",
    "PIPELINE_current_liabilities", "PIPELINE_net_assets", "PIPELINE_current_ratio",
    "PIPELINE_gross_margin_pct", "PIPELINE_health_score", "PIPELINE_health_rating",
    "MANUAL_turnover", "MANUAL_gross_profit", "MANUAL_current_assets",
    "MANUAL_current_liabilities", "MANUAL_net_assets",
    "MATCH_Y_N", "NOTES",
]

with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(list(row) + ["", "", "", "", "", "", ""])

print(f"Used accounts-type column: {accounts_type_col or '(none found - left blank)'}")
print(f"Wrote {len(rows)} companies to {OUT_PATH}")
print("Open it, and for each company_number, look it up at:")
print("  https://find-and-update.company-information.service.gov.uk/company/<company_number>")
print("Open its latest accounts filing, read off the 5 MANUAL_* columns, and mark MATCH_Y_N.")
conn.close()
