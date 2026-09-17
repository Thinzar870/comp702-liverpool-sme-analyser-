import sqlite3
conn = sqlite3.connect("output/liverpool_sme_analyser.db")
cur = conn.cursor()
total = cur.execute("SELECT COUNT(*) FROM financial_ratios").fetchone()[0]
print(f"Total rows: {total:,}")
for col in ["current_ratio", "gross_margin_pct", "debt_to_equity", "health_score"]:
    n = cur.execute(f"SELECT COUNT(*) FROM financial_ratios WHERE {col} IS NOT NULL").fetchone()[0]
    print(f"{col}: {n:,} non-null ({100*n/total:.1f}%)")
conn.close()