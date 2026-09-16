import pandas as pd

df = pd.read_csv("output/stage3_financial_data.csv", dtype=str, low_memory=False)
df["current_ratio"] = pd.to_numeric(df["current_ratio"], errors="coerce")

valid = df["current_ratio"].dropna()
print(f"Total rows with a current_ratio value: {len(valid):,}")
print(f"Mean: {valid.mean():.2f}  Median: {valid.median():.2f}")
print()

# How many rows are pushing the mean up?
for cutoff in [10, 20, 50, 100, 500, 1000]:
    n = (valid > cutoff).sum()
    pct = 100 * n / len(valid)
    print(f"Rows with current_ratio > {cutoff}: {n:,} ({pct:.2f}%)")

print()
print("Top 10 most extreme current_ratio rows:")
cols = [c for c in ["company_number", "company_name", "current_ratio",
                     "current_assets", "current_liabilities"] if c in df.columns]
print(df.loc[valid.sort_values(ascending=False).index[:10], cols].to_string(index=False))
