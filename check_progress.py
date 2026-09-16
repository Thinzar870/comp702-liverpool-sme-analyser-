import pandas as pd

df = pd.read_csv("output/stage3_progress.csv", dtype=str)
n_rows = len(df)
n_companies = df["company_number"].nunique()
print(f"{n_rows:,} filing rows checkpointed")
print(f"{n_companies:,} unique companies checkpointed")
print(f"Target: 66,769 companies")
print(f"Remaining: {66769 - n_companies:,} companies")
