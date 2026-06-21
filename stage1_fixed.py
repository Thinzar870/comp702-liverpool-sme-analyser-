"""
COMP702 — STAGE 1 FIXED: Build the Liverpool SME Company List
==============================================================
Author:  Thinzar Aung (201942837)
Project: AI-Powered SME Financial Health Analyser for Liverpool City Region

FIXED VERSION — column names now match the real Companies House CSV exactly.

HOW TO RUN:
  python stage1_fixed.py
"""

import os
import csv
import zipfile
import pandas as pd
from io import StringIO
from datetime import datetime

os.makedirs("output", exist_ok=True)

# ── Liverpool City Region postcodes ───────────────────────────
LIVERPOOL_POSTCODES = [
    "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9",
    "L10", "L11", "L12", "L13", "L14", "L15", "L16", "L17",
    "L18", "L19", "L20", "L21", "L22", "L23", "L24", "L25",
    "L26", "L27", "L28", "L29", "L30", "L31", "L32", "L33",
    "L34", "L35", "L36", "L37", "L38", "L39", "L40",
    "CH41", "CH42", "CH43", "CH44", "CH45", "CH46", "CH47",
    "CH48", "CH49", "CH60", "CH61", "CH62", "CH63", "CH64",
    "WA8", "WA9", "WA10", "WA11", "WA12",
    "PR8", "PR9",
]

# SME company types — using EXACT values from your real CSV
SME_COMPANY_TYPES = [
    "Private Limited Company",
    "Private Unlimited Company",
    "Community Interest Company",
    "Limited Liability Partnership",
    "Private Limited Company by Guarantee",
    "Industrial and Provident Society",
    "Registered Society",
    "Charitable Incorporated Organisation",
    "Private Limited Company by guarantee without share capital",
    "Private Unlimited Company without Share Capital",
    "PRI/LTD BY GUAR/NSC (Private, limited by guarantee, no share capital)",
    "PRI/LBG/NSC (Private, Limited by guarantee, no share capital, use of 'Limited' exemption)",
]

# SIC codes to exclude — dormant and holding companies
EXCLUDE_SIC_PREFIXES = ["64202", "64209", "74990", "99999", "99998"]


def load_local_zip(filepath: str) -> pd.DataFrame:
    print(f"\n  Loading from local ZIP: {filepath}")
    with zipfile.ZipFile(filepath) as z:
        csv_files = [f for f in z.namelist() if f.endswith(".csv")]
        print(f"  Files inside ZIP: {z.namelist()}")
        csv_filename = csv_files[0]
        print(f"  Reading: {csv_filename}")
        with z.open(csv_filename) as f:
            df = pd.read_csv(f, dtype=str, encoding="utf-8",
                             on_bad_lines="skip", low_memory=False)
    print(f"  ✓ Loaded {len(df):,} companies")
    print(f"  ✓ Columns: {list(df.columns[:10])}...")
    return df


def filter_to_liverpool(df: pd.DataFrame) -> pd.DataFrame:
    print("\n" + "="*60)
    print("STEP 3 — FILTERING TO LIVERPOOL CITY REGION")
    print("="*60)

    # The real column name from your CSV
    postcode_col = "RegAddress.PostCode"

    if postcode_col not in df.columns:
        # Try to find it
        matches = [c for c in df.columns if "postcode" in c.lower()
                   or "post" in c.lower()]
        print(f"  Could not find '{postcode_col}'")
        print(f"  Postcode-like columns found: {matches}")
        if matches:
            postcode_col = matches[0]
            print(f"  Using: {postcode_col}")
        else:
            print("  ERROR: No postcode column found")
            return pd.DataFrame()

    print(f"  Using postcode column: '{postcode_col}'")

    # Clean postcodes
    df["postcode_clean"] = (
        df[postcode_col]
        .fillna("")
        .str.strip()
        .str.upper()
        .str.replace(" ", "", regex=False)
    )

    # Filter to Liverpool postcodes
    def is_liverpool(pc):
        if not pc:
            return False
        for prefix in LIVERPOOL_POSTCODES:
            prefix_clean = prefix.replace(" ", "").upper()
            if pc.startswith(prefix_clean):
                return True
        return False

    print("  Filtering postcodes... (may take a minute)")
    mask = df["postcode_clean"].apply(is_liverpool)
    liverpool_df = df[mask].copy()

    print(f"\n  UK total:             {len(df):,}")
    print(f"  Liverpool matches:    {len(liverpool_df):,}")

    if len(liverpool_df) == 0:
        # Debug — show sample postcodes
        sample = df[postcode_col].dropna().head(20).tolist()
        print(f"  DEBUG sample postcodes: {sample}")

    return liverpool_df


def filter_to_active_smes(df: pd.DataFrame) -> pd.DataFrame:
    print("\n" + "="*60)
    print("STEP 4 — FILTERING TO ACTIVE SMEs")
    print("="*60)

    before = len(df)

    # Show unique values to debug
    print(f"\n  Sample CompanyStatus values:")
    print(f"  {df['CompanyStatus'].value_counts().head(10).to_dict()}")
    print(f"\n  Sample CompanyCategory values:")
    print(f"  {df['CompanyCategory'].value_counts().head(10).to_dict()}")

    # Filter 1 — Active companies only
    status_col = "CompanyStatus"
    if status_col in df.columns:
        before_s = len(df)
        df = df[df[status_col].str.strip().str.lower() == "active"]
        print(f"\n  After status filter (Active only): {len(df):,} "
              f"(removed {before_s - len(df):,})")

    # Filter 2 — SME company types only
    cat_col = "CompanyCategory"
    if cat_col in df.columns:
        before_t = len(df)
        # Keep any company that is NOT a PLC or overseas
        exclude_types = [
            "Public Limited Company",
            "Old Public Company",
            "Overseas Company",
            "European Public Limited-Liability Company (SE)",
            "Royal Charter Company",
        ]
        df = df[~df[cat_col].isin(exclude_types)]
        print(f"  After type filter (no PLCs/overseas): {len(df):,} "
              f"(removed {before_t - len(df):,})")

    # Filter 3 — Remove dormant/holding by SIC code
    sic_col = "SICCode.SicText_1"
    if sic_col in df.columns:
        before_sic = len(df)
        for prefix in EXCLUDE_SIC_PREFIXES:
            df = df[~df[sic_col].fillna("").str.startswith(prefix)]
        print(f"  After SIC filter (no dormants): {len(df):,} "
              f"(removed {before_sic - len(df):,})")

    # Remove helper column
    df = df.drop(columns=["postcode_clean"], errors="ignore")

    print(f"\n  Before SME filter: {before:,}")
    print(f"  After SME filter:  {len(df):,}")
    return df


def produce_output(df: pd.DataFrame):
    print("\n" + "="*60)
    print("STEP 5 — SAVING OUTPUT")
    print("="*60)

    # Rename columns to clean names
    rename_map = {
        "CompanyNumber":            "company_number",
        "CompanyName":              "company_name",
        "CompanyCategory":          "company_type",
        "CompanyStatus":            "company_status",
        "RegAddress.PostCode":      "postcode",
        "RegAddress.AddressLine1":  "address_line1",
        "RegAddress.PostTown":      "post_town",
        "SICCode.SicText_1":        "sic_code_1",
        "SICCode.SicText_2":        "sic_code_2",
        "IncorporationDate":        "incorporation_date",
        "Accounts.LastMadeUpDate":  "last_accounts_date",
        "Accounts.AccountCategory": "accounts_type",
        "URI":                      "companies_house_uri",
    }

    df = df.rename(columns=rename_map)
    keep = [v for v in rename_map.values() if v in df.columns]
    output_df = df[keep]

    # Save Liverpool SME list
    csv_path = "output/stage1_liverpool_smes.csv"
    output_df.to_csv(csv_path, index=False)
    print(f"\n  ✓ Liverpool SME list: {csv_path}")
    print(f"    {len(output_df):,} companies")

    # SIC breakdown
    if "sic_code_1" in output_df.columns:
        sic = (output_df["sic_code_1"]
               .fillna("Unknown")
               .value_counts()
               .head(20)
               .reset_index())
        sic.columns = ["sic_code", "count"]
        sic.to_csv("output/stage1_sic_breakdown.csv", index=False)
        print(f"\n  TOP 10 INDUSTRIES IN LIVERPOOL:")
        for _, row in sic.head(10).iterrows():
            print(f"    {str(row['sic_code'])[:55]}: {row['count']:,}")

    # Summary report
    with open("output/stage1_summary_report.txt", "w") as f:
        f.write("="*60 + "\n")
        f.write("COMP702 — STAGE 1 SUMMARY REPORT\n")
        f.write("AI-Powered SME Financial Health Analyser for Liverpool\n")
        f.write(f"Thinzar Aung (201942837)\n")
        f.write(f"Generated: {datetime.now().strftime('%d %B %Y %H:%M')}\n")
        f.write("="*60 + "\n\n")
        f.write("DATA SOURCE\n")
        f.write("-"*40 + "\n")
        f.write("Companies House Free Company Data Product\n")
        f.write("http://download.companieshouse.gov.uk/en_output.html\n")
        f.write("Free, Open Government Licence v3.0, updated monthly\n\n")
        f.write("RESULTS\n")
        f.write("-"*40 + "\n")
        f.write(f"Liverpool active SMEs found: {len(output_df):,}\n\n")
        f.write("NEXT STEP — STAGE 2\n")
        f.write("-"*40 + "\n")
        f.write("Feed stage1_liverpool_smes.csv into Stage 2.\n")
        f.write("Stage 2 calls the Companies House REST API for each\n")
        f.write("company to verify current status and get filing dates.\n")

    print(f"\n  ✓ Summary report saved")
    return output_df


def main():
    print("\n" + "="*60)
    print("  COMP702 STAGE 1 — LIVERPOOL SME LIST (FIXED VERSION)")
    print("  Thinzar Aung (201942837)")
    print("="*60)

    df = load_local_zip("BasicCompanyDataAsOneFile-2026-06-01.zip")
    liverpool_df = filter_to_liverpool(df)

    if len(liverpool_df) == 0:
        print("\n  ERROR: No Liverpool companies found after postcode filter.")
        print("  Check the postcode column values above.")
        return

    sme_df = filter_to_active_smes(liverpool_df)
    output_df = produce_output(sme_df)

    print("\n" + "="*60)
    print("  STAGE 1 COMPLETE")
    print(f"  {len(output_df):,} Liverpool City Region active SMEs found")
    print("="*60)


if __name__ == "__main__":
    main()
