import sqlite3

conn = sqlite3.connect("output/liverpool_sme_analyser.db")
cur = conn.cursor()

# Bug 4 signature: current_assets exactly equals current_liabilities,
# which forces current_ratio to exactly 1.0 -- discovered via manual
# verification of Elegance By B Ltd and Ermine Security Limited.
cur.execute("""
    SELECT COUNT(*) FROM financial_data
    WHERE current_assets IS NOT NULL
      AND current_assets = current_liabilities
      AND current_assets > 0
""")
exact_match_count = cur.fetchone()[0]

cur.execute("SELECT COUNT(*) FROM financial_data WHERE current_assets IS NOT NULL")
total_with_data = cur.fetchone()[0]

cur.execute("""
    SELECT COUNT(DISTINCT company_number) FROM financial_data
    WHERE current_assets IS NOT NULL
      AND current_assets = current_liabilities
      AND current_assets > 0
""")
distinct_companies = cur.fetchone()[0]

print(f"Rows where current_assets == current_liabilities (>0): {exact_match_count:,}")
print(f"  out of {total_with_data:,} rows with current_assets present")
print(f"  ({100*exact_match_count/total_with_data:.2f}%)")
print(f"Distinct companies affected: {distinct_companies:,}")

conn.close()
