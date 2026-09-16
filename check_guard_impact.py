import sqlite3

conn = sqlite3.connect("output/liverpool_sme_analyser.db")
cur = conn.cursor()

total = cur.execute("SELECT COUNT(*) FROM financial_ratios").fetchone()[0]
null_ratio = cur.execute(
    "SELECT COUNT(*) FROM financial_ratios WHERE current_ratio IS NULL"
).fetchone()[0]

# Distinct companies affected (not just rows, since a company can have multiple years)
affected_companies = cur.execute(
    "SELECT COUNT(DISTINCT company_number) FROM financial_ratios WHERE current_ratio IS NULL"
).fetchone()[0]

print(f"Total financial_ratios rows: {total:,}")
print(f"Rows with current_ratio = NULL: {null_ratio:,} ({100*null_ratio/total:.2f}%)")
print(f"Distinct companies with at least one NULL current_ratio: {affected_companies:,}")

conn.close()
