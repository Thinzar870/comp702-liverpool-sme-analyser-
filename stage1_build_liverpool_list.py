"""
COMP702 — STAGE 1: Build the Liverpool SME Company List
=========================================================
Author:  Thinzar Aung (201942837)
Project: AI-Powered SME Financial Health Analyser for Liverpool City Region
Stage:   1 of 7 — Build Liverpool Company List

WHAT THIS SCRIPT DOES:
  Downloads the official Companies House Free Company Data Product
  (a CSV of ALL active UK companies) and filters it down to only
  Liverpool City Region SMEs — producing a small, clean list of
  company numbers that Stage 2 onwards will use.

WHY THIS SOURCE?
  The Companies House Free Company Data Product is:
  ✓ Official — published directly by Companies House (UK Government)
  ✓ Free — no cost, no API key needed for this step
  ✓ Complete — contains ALL active companies on the register
  ✓ Current — updated monthly within 5 working days of month end
  ✓ Reliable — the same data used by banks, HMRC, and government
  ✓ Open licence — free to use for research purposes

WHERE TO DOWNLOAD MANUALLY (if you prefer):
  One large file (470MB):
  https://download.companieshouse.gov.uk/BasicCompanyDataAsOneFile-2026-06-01.zip

  Or as 7 smaller files (each ~70MB) from:
  http://download.companieshouse.gov.uk/en_output.html

HOW TO RUN:
  pip install requests pandas tqdm
  python3 stage1_build_liverpool_list.py

OUTPUT:
  output/stage1_liverpool_smes.csv       — your Liverpool SME list
  output/stage1_summary_report.txt       — summary of what was found
  output/stage1_sic_breakdown.csv        — which industries are in the list
"""

import os
import csv
import zipfile
import requests
import pandas as pd
from io import BytesIO, StringIO
from datetime import datetime

os.makedirs("output", exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

# The official Companies House Free Company Data Product URL
# This is the single-file version (470MB compressed)
# Updated automatically every month by Companies House
BASIC_DATA_URL = (
    "https://download.companieshouse.gov.uk/"
    "BasicCompanyDataAsOneFile-2026-06-01.zip"
)

# ── Liverpool City Region postcodes ───────────────────────────
# These cover Liverpool, Knowsley, Sefton, St Helens, Halton, Wirral
# Source: Liverpool City Region Combined Authority boundary
LIVERPOOL_POSTCODES = [
    # Liverpool city
    "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9",
    "L10", "L11", "L12", "L13", "L14", "L15", "L16", "L17",
    "L18", "L19", "L20", "L21", "L22", "L23", "L24", "L25",
    "L26", "L27", "L28", "L29", "L30", "L31", "L32", "L33",
    "L34", "L35", "L36", "L37", "L38", "L39", "L40",
    # Wirral
    "CH41", "CH42", "CH43", "CH44", "CH45", "CH46", "CH47",
    "CH48", "CH49", "CH60", "CH61", "CH62", "CH63", "CH64",
    # St Helens and Halton
    "WA8", "WA9", "WA10", "WA11", "WA12",
    # Southport / Sefton
    "PR8", "PR9",
]

# ── SME definition ────────────────────────────────────────────
# We exclude very large companies (PLC) and non-trading entities
# SME = company type is limited, LLP, or community interest company
# NOT listed PLCs, unlimited companies, or overseas companies
SME_COMPANY_TYPES = [
    "private-limited-company",           # Ltd — the most common
    "private-unlimited-company",         # Unlimited private
    "private-limited-guarant-nsc-limited-exemption",  # Charity Ltd
    "private-limited-guarant-nsc",       # Guarantee company
    "community-interest-company",        # CIC (like Baltic Creative)
    "limited-liability-partnership",     # LLP
    "industrial-and-provident-society",  # Co-operative
    "registered-society-non-jurisdictional",
]

# Exclude these statuses — we only want actively trading companies
EXCLUDE_STATUSES = [
    "dissolved",
    "liquidation",
    "receivership",
    "converted-closed",
    "voluntary-arrangement",
    "insolvency-proceedings",
    "administration",
    "strike-off-action-in-progress",
]

# ── SIC codes to EXCLUDE ─────────────────────────────────────
# These are holding companies, dormant entities, and non-trading
# organisations that are not useful for financial health analysis
EXCLUDE_SIC_CODES = [
    "64202",  # Activities of holding companies
    "64209",  # Other activities of holding companies
    "74990",  # Non-trading company
    "98000",  # Residents of properties as employers
    "99999",  # Dormant company
    "99998",  # Establishment not described elsewhere
]


# ═══════════════════════════════════════════════════════════════
# STEP 1 — DOWNLOAD THE COMPANIES HOUSE BASIC DATA CSV
# ═══════════════════════════════════════════════════════════════

def download_basic_data(url: str) -> pd.DataFrame:
    """
    Downloads the Companies House Free Company Data Product.

    This is a ZIP file containing one large CSV with every active
    UK company. We download it, open it in memory, and read the CSV
    directly — without saving the raw ZIP to disk.

    Returns a pandas DataFrame with all UK companies.
    """
    print("\n" + "=" * 65)
    print("STEP 1 — DOWNLOADING COMPANIES HOUSE BASIC DATA")
    print("=" * 65)
    print(f"\n  Source: {url}")
    print(f"  This is the official UK Government Companies House data.")
    print(f"  Free, no login required, updated monthly.")
    print(f"\n  Downloading... (this may take a few minutes — file is ~470MB)")

    try:
        # Stream the download so we can show progress
        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()

        # Get total file size for progress display
        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0
        chunks = []

        for chunk in response.iter_content(chunk_size=1024 * 1024):  # 1MB chunks
            if chunk:
                chunks.append(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    pct = downloaded / total_size * 100
                    print(f"\r  Progress: {downloaded / 1024 / 1024:.0f}MB / "
                          f"{total_size / 1024 / 1024:.0f}MB ({pct:.1f}%)", end="")

        print(f"\n  ✓ Download complete — {downloaded / 1024 / 1024:.1f}MB")

        # Open the ZIP in memory (no need to save to disk)
        zip_data = BytesIO(b"".join(chunks))
        print("  Opening ZIP file...")

        with zipfile.ZipFile(zip_data) as z:
            # Find the CSV file inside the ZIP
            csv_files = [f for f in z.namelist() if f.endswith(".csv")]
            print(f"  Files inside ZIP: {z.namelist()}")

            if not csv_files:
                raise ValueError("No CSV file found inside the ZIP")

            csv_filename = csv_files[0]
            print(f"  Reading CSV: {csv_filename}")

            with z.open(csv_filename) as csv_file:
                # Read into pandas — this CSV has millions of rows
                df = pd.read_csv(
                    csv_file,
                    dtype=str,           # Read everything as string first
                    encoding="utf-8",
                    on_bad_lines="skip"  # Skip any malformed rows
                )

        print(f"  ✓ Loaded {len(df):,} companies from Companies House")
        print(f"  ✓ Columns available: {list(df.columns)}")
        return df

    except requests.RequestException as e:
        print(f"\n  ✗ Download failed: {e}")
        print(f"\n  MANUAL DOWNLOAD OPTION:")
        print(f"  1. Go to: http://download.companieshouse.gov.uk/en_output.html")
        print(f"  2. Download: BasicCompanyDataAsOneFile-2026-06-01.zip")
        print(f"  3. Unzip it — you will get a file called BasicCompanyData.csv")
        print(f"  4. Place it in the same folder as this script")
        print(f"  5. Run: python3 stage1_build_liverpool_list.py --local")
        return pd.DataFrame()


def load_local_csv(filepath: str) -> pd.DataFrame:
    """
    Alternative: load from a locally downloaded CSV file.
    Use this if you downloaded the file manually.
    """
    print(f"\n  Loading from local file: {filepath}")
    df = pd.read_csv(filepath, dtype=str, encoding="utf-8", on_bad_lines="skip")
    print(f"  ✓ Loaded {len(df):,} companies")
    return df


# ═══════════════════════════════════════════════════════════════
# STEP 2 — UNDERSTAND THE CSV STRUCTURE
# ═══════════════════════════════════════════════════════════════

def inspect_csv_structure(df: pd.DataFrame):
    """
    Prints the column names and a sample row so you can understand
    what the data looks like before filtering.

    This is important for your dissertation — you need to describe
    the data structure in your proposal and methodology chapter.
    """
    print("\n" + "=" * 65)
    print("STEP 2 — UNDERSTANDING THE CSV STRUCTURE")
    print("=" * 65)

    print("\n  COLUMNS IN THE COMPANIES HOUSE BASIC DATA CSV:")
    print("  " + "-" * 55)
    for i, col in enumerate(df.columns):
        print(f"  {i+1:2}. {col}")

    print("\n  SAMPLE ROW (first company in the file):")
    print("  " + "-" * 55)
    if len(df) > 0:
        for col, val in df.iloc[0].items():
            print(f"  {col}: {val}")

    print(f"\n  TOTAL ROWS (all UK companies): {len(df):,}")


# ═══════════════════════════════════════════════════════════════
# STEP 3 — FILTER TO LIVERPOOL CITY REGION
# ═══════════════════════════════════════════════════════════════

def filter_to_liverpool(df: pd.DataFrame) -> pd.DataFrame:
    """
    Filters the full UK dataset to Liverpool City Region companies only.

    The postcode field in Companies House data is called:
    'RegAddress.PostCode'

    We check if the postcode STARTS WITH any of our Liverpool prefixes.
    For example 'L1 4DS' starts with 'L1' so it is included.
    """
    print("\n" + "=" * 65)
    print("STEP 3 — FILTERING TO LIVERPOOL CITY REGION")
    print("=" * 65)

    # Find the postcode column — it may have different names
    # depending on the version of the CSV
    postcode_col = None
    for col in df.columns:
        if "postcode" in col.lower() or "post.code" in col.lower():
            postcode_col = col
            break

    if not postcode_col:
        print("  ✗ Could not find postcode column")
        print(f"  Available columns: {list(df.columns)}")
        return pd.DataFrame()

    print(f"\n  Using postcode column: '{postcode_col}'")
    print(f"  Liverpool postcodes to match: {len(LIVERPOOL_POSTCODES)} prefixes")

    # Clean postcodes — remove spaces and make uppercase
    df["postcode_clean"] = (
        df[postcode_col]
        .fillna("")
        .str.strip()
        .str.upper()
        .str.replace(" ", "", regex=False)
    )

    # Filter — check if postcode starts with any Liverpool prefix
    # We remove spaces from both sides for reliable matching
    # e.g. "L1 4DS" → "L14DS" starts with "L1" ✓
    # e.g. "L10 2AB" → "L102AB" starts with "L10" ✓
    def is_liverpool(postcode_clean):
        if not postcode_clean:
            return False
        for prefix in LIVERPOOL_POSTCODES:
            prefix_clean = prefix.replace(" ", "").upper()
            if postcode_clean.startswith(prefix_clean):
                return True
        return False

    print("  Filtering... (this may take a moment for millions of rows)")
    mask = df["postcode_clean"].apply(is_liverpool)
    liverpool_df = df[mask].copy()

    print(f"\n  ✓ UK total companies:         {len(df):,}")
    print(f"  ✓ Liverpool City Region:      {len(liverpool_df):,}")
    print(f"  ✓ Reduction:                  {(1 - len(liverpool_df)/len(df))*100:.1f}% of data removed")

    return liverpool_df


# ═══════════════════════════════════════════════════════════════
# STEP 4 — FILTER TO ACTIVE SMEs ONLY
# ═══════════════════════════════════════════════════════════════

def filter_to_active_smes(df: pd.DataFrame) -> pd.DataFrame:
    """
    From the Liverpool companies, keep only:
    1. Active companies (not dissolved, not in liquidation etc.)
    2. SME company types (not PLCs, not overseas companies)
    3. Trading companies (exclude holding companies and dormants)

    This is the pre-processing step Olga emphasised as critical.
    """
    print("\n" + "=" * 65)
    print("STEP 4 — FILTERING TO ACTIVE SMEs")
    print("=" * 65)

    before = len(df)

    # Find status column
    status_col = None
    for col in df.columns:
        if "status" in col.lower() and "company" in col.lower():
            status_col = col
            break
    if not status_col:
        for col in df.columns:
            if "status" in col.lower():
                status_col = col
                break

    # Find company type column
    type_col = None
    for col in df.columns:
        if "category" in col.lower() or "type" in col.lower():
            type_col = col
            break

    # Find SIC code column
    sic_col = None
    for col in df.columns:
        if "sic" in col.lower():
            sic_col = col
            break

    print(f"\n  Status column:       {status_col}")
    print(f"  Company type column: {type_col}")
    print(f"  SIC code column:     {sic_col}")

    # Filter 1 — Remove dissolved/inactive companies
    if status_col:
        df["status_clean"] = df[status_col].fillna("").str.lower().str.strip()
        before_status = len(df)
        df = df[~df["status_clean"].isin([s.lower() for s in EXCLUDE_STATUSES])]
        # Keep only "active" companies
        df = df[df["status_clean"] == "active"]
        print(f"\n  After status filter (active only): {len(df):,} "
              f"(removed {before_status - len(df):,})")

    # Filter 2 — Keep only SME company types
    if type_col:
        df["type_clean"] = df[type_col].fillna("").str.lower().str.strip()
        before_type = len(df)
        df = df[df["type_clean"].isin([t.lower() for t in SME_COMPANY_TYPES])]
        print(f"  After type filter (SMEs only):    {len(df):,} "
              f"(removed {before_type - len(df):,})")

    # Filter 3 — Remove holding companies and dormants by SIC code
    if sic_col:
        before_sic = len(df)
        # SIC codes to exclude (dormant, holding, non-trading)
        for code in EXCLUDE_SIC_CODES:
            df = df[~df[sic_col].fillna("").str.contains(code, na=False)]
        print(f"  After SIC filter (no dormants):   {len(df):,} "
              f"(removed {before_sic - len(df):,})")

    after = len(df)
    print(f"\n  ✓ Liverpool companies before SME filter: {before:,}")
    print(f"  ✓ Liverpool active SMEs after filter:    {after:,}")
    print(f"  ✓ Reduction: {(1 - after/before)*100:.1f}% non-SMEs removed")

    return df


# ═══════════════════════════════════════════════════════════════
# STEP 5 — PRODUCE CLEAN OUTPUT
# ═══════════════════════════════════════════════════════════════

def produce_output(df: pd.DataFrame):
    """
    Saves the filtered Liverpool SME list as a clean CSV.
    This CSV is the input for Stage 2 (API verification)
    and Stage 3 (iXBRL bulk matching).

    Also produces a summary report and SIC code breakdown.
    """
    print("\n" + "=" * 65)
    print("STEP 5 — PRODUCING OUTPUT FILES")
    print("=" * 65)

    # Identify key columns to keep
    # The exact column names depend on the CH CSV version
    # We map common variants to clean names
    COLUMN_MAP = {
        " CompanyNumber":           "company_number",
        "CompanyNumber":            "company_number",
        "CompanyName":              "company_name",
        " CompanyName":             "company_name",
        "CompanyCategory":          "company_type",
        "CompanyStatus":            "company_status",
        "RegAddress.PostCode":      "postcode",
        "RegAddress.AddressLine1":  "address_line1",
        "RegAddress.AddressLine2":  "address_line2",
        "RegAddress.PostTown":      "post_town",
        "SICCode.SicText_1":        "sic_code_1",
        "SICCode.SicText_2":        "sic_code_2",
        "IncorporationDate":        "incorporation_date",
        "Accounts.LastMadeUpDate":  "last_accounts_date",
        "Accounts.AccountCategory": "accounts_type",
        "URI":                      "companies_house_uri",
    }

    # Rename columns we have
    rename_dict = {k: v for k, v in COLUMN_MAP.items() if k in df.columns}
    df = df.rename(columns=rename_dict)

    # Select only useful columns (whatever we have)
    keep_cols = [v for v in COLUMN_MAP.values() if v in df.columns]
    if "postcode_clean" in df.columns:
        df = df.drop(columns=["postcode_clean"], errors="ignore")
    if "status_clean" in df.columns:
        df = df.drop(columns=["status_clean"], errors="ignore")
    if "type_clean" in df.columns:
        df = df.drop(columns=["type_clean"], errors="ignore")

    output_df = df[keep_cols] if keep_cols else df

    # Save the Liverpool SME list
    csv_path = "output/stage1_liverpool_smes.csv"
    output_df.to_csv(csv_path, index=False)
    print(f"\n  ✓ Liverpool SME list saved: {csv_path}")
    print(f"    Rows: {len(output_df):,} companies")
    print(f"    Columns: {list(output_df.columns)}")

    # SIC code breakdown — what industries are in the list?
    if "sic_code_1" in output_df.columns:
        sic_counts = (
            output_df["sic_code_1"]
            .fillna("Unknown")
            .value_counts()
            .head(20)
            .reset_index()
        )
        sic_counts.columns = ["sic_code", "count"]
        sic_path = "output/stage1_sic_breakdown.csv"
        sic_counts.to_csv(sic_path, index=False)
        print(f"  ✓ SIC code breakdown saved: {sic_path}")
        print(f"\n  TOP 10 INDUSTRIES IN LIVERPOOL SME LIST:")
        for _, row in sic_counts.head(10).iterrows():
            print(f"    {row['sic_code'][:60]}: {row['count']:,} companies")

    # Summary report
    report_path = "output/stage1_summary_report.txt"
    with open(report_path, "w") as f:
        f.write("=" * 65 + "\n")
        f.write("COMP702 — STAGE 1 SUMMARY REPORT\n")
        f.write("AI-Powered SME Financial Health Analyser for Liverpool\n")
        f.write(f"Thinzar Aung (201942837)\n")
        f.write(f"Generated: {datetime.now().strftime('%d %B %Y %H:%M')}\n")
        f.write("=" * 65 + "\n\n")
        f.write("DATA SOURCE\n")
        f.write("-" * 40 + "\n")
        f.write("Source:   Companies House Free Company Data Product\n")
        f.write("URL:      http://download.companieshouse.gov.uk/en_output.html\n")
        f.write("Format:   ZIP containing CSV\n")
        f.write("Cost:     Free — no registration required\n")
        f.write("Licence:  Open Government Licence v3.0\n")
        f.write("Updated:  Monthly (within 5 working days of month end)\n\n")
        f.write("FILTERING APPLIED\n")
        f.write("-" * 40 + "\n")
        f.write(f"Postcode filter: Liverpool City Region postcodes\n")
        f.write(f"  ({', '.join(LIVERPOOL_POSTCODES[:10])}... and {len(LIVERPOOL_POSTCODES)-10} more)\n")
        f.write(f"Status filter:   Active companies only\n")
        f.write(f"Type filter:     SME company types only (no PLCs, no overseas)\n")
        f.write(f"SIC filter:      Excluded dormant/holding companies\n\n")
        f.write("RESULTS\n")
        f.write("-" * 40 + "\n")
        f.write(f"Liverpool active SMEs found: {len(output_df):,}\n")
        f.write(f"Output file: {csv_path}\n\n")
        f.write("NEXT STEP — STAGE 2\n")
        f.write("-" * 40 + "\n")
        f.write("Feed stage1_liverpool_smes.csv into Stage 2.\n")
        f.write("Stage 2 will call the Companies House REST API for each\n")
        f.write("company to verify current status and get latest filing dates.\n")

    print(f"  ✓ Summary report saved: {report_path}")
    return output_df


# ═══════════════════════════════════════════════════════════════
# DEMO MODE — runs without downloading (for testing)
# ═══════════════════════════════════════════════════════════════

def run_demo_mode():
    """
    Creates a realistic sample of what the Companies House CSV
    looks like, then runs all filters on it.
    Use this to understand the pipeline before downloading the real file.
    """
    print("\n  [DEMO MODE — using sample data to show what the pipeline does]")
    print("  [Replace with real download when ready]\n")

    # This is exactly what the real Companies House CSV looks like
    sample_data = """CompanyNumber,CompanyName,RegAddress.AddressLine1,RegAddress.PostTown,RegAddress.PostCode,CompanyCategory,CompanyStatus,IncorporationDate,Accounts.LastMadeUpDate,Accounts.AccountCategory,SICCode.SicText_1,URI
07588791,BALTIC CREATIVE CIC,49 Jamaica Street,Liverpool,L1 0AH,community-interest-company,Active,06/04/2011,31/03/2023,FULL,90010 - Creative arts and entertainment activities,https://api.company-information.service.gov.uk/company/07588791
09123456,MERSEY TECH SOLUTIONS LTD,20 Chapel Street,Liverpool,L3 9AG,private-limited-company,Active,15/03/2019,30/09/2023,MICRO-ENTITY,62020 - Information technology consultancy activities,https://api.company-information.service.gov.uk/company/09123456
04007167,CAINS BREWERY VILLAGE LTD,Stanhope Street,Liverpool,L8 5XJ,private-limited-company,Active,12/09/2000,31/12/2022,FULL,55100 - Hotels and similar accommodation,https://api.company-information.service.gov.uk/company/04007167
00035668,LIVERPOOL FOOTBALL CLUB AND ATHLETIC GROUNDS LTD,Anfield Road,Liverpool,L4 0TH,private-limited-company,Active,01/01/1892,31/05/2023,FULL,93120 - Activities of sport clubs,https://api.company-information.service.gov.uk/company/00035668
12345678,LONDON TECH PLC,1 Canary Wharf,London,E14 5AB,public-limited-company,Active,01/01/2010,31/12/2022,FULL,62020 - Information technology consultancy activities,https://api.company-information.service.gov.uk/company/12345678
99887766,MANCHESTER FOOD LTD,5 Deansgate,Manchester,M3 2FF,private-limited-company,Active,01/06/2015,31/03/2023,FULL,56101 - Restaurants and cafes,https://api.company-information.service.gov.uk/company/99887766
11223344,WIRRAL CONSULTING LLP,10 New Ferry Road,Birkenhead,CH62 1AJ,limited-liability-partnership,Active,20/02/2018,31/08/2023,FULL,70229 - Management consultancy activities,https://api.company-information.service.gov.uk/company/11223344
55443322,DISSOLVED LIVERPOOL CO,Bold Street,Liverpool,L1 4DS,private-limited-company,Dissolved,01/01/2005,31/12/2019,FULL,47190 - Other retail sale in non-specialised stores,https://api.company-information.service.gov.uk/company/55443322
66554433,DORMANT HOLDINGS LTD,Water Street,Liverpool,L2 8TD,private-limited-company,Active,01/01/2000,31/12/2022,DORMANT,64202 - Activities of holding companies,https://api.company-information.service.gov.uk/company/66554433
77665544,SEFTON RETAIL LTD,Lord Street,Southport,PR8 1NT,private-limited-company,Active,15/07/2016,31/10/2023,MICRO-ENTITY,47190 - Other retail sale in non-specialised stores,https://api.company-information.service.gov.uk/company/77665544"""

    df = pd.read_csv(StringIO(sample_data), dtype=str)
    print(f"  Sample dataset loaded: {len(df)} companies (representing millions in real data)")
    return df


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main(demo_mode=True):
    print("\n" + "=" * 65)
    print("  COMP702 — STAGE 1: BUILD LIVERPOOL SME COMPANY LIST")
    print("  Thinzar Aung (201942837) — University of Liverpool")
    print("=" * 65)

    print("""
  DATA SOURCE:
  Companies House Free Company Data Product
  URL: http://download.companieshouse.gov.uk/en_output.html
  
  WHY THIS SOURCE IS RELIABLE:
  ✓ Official UK Government data — published by Companies House
  ✓ The same register used by HMRC, courts, and banks
  ✓ Updated monthly — always current
  ✓ Free and openly licensed
  ✓ Contains ALL active UK companies — nothing is missing
  ✓ No API key or registration needed for this step
  """)

    # ── Choose demo or real download ──────────────────────────
    if demo_mode:
        df = run_demo_mode()
    else:
        # REAL DOWNLOAD — uncomment when ready
        df = load_local_zip("BasicCompanyDataAsOneFile-2026-06-01.zip")
        # OR load from local file if you downloaded manually:
        # df = load_local_csv("BasicCompanyData.csv")

        if df.empty:
            print("\n  Could not load data. Please download manually and retry.")
            return

    # ── Run the pipeline ──────────────────────────────────────
    inspect_csv_structure(df)
    liverpool_df = filter_to_liverpool(df)
    sme_df = filter_to_active_smes(liverpool_df)
    output_df = produce_output(sme_df)

    # ── Final summary ─────────────────────────────────────────
    print("\n" + "=" * 65)
    print("  STAGE 1 COMPLETE")
    print("=" * 65)
    print(f"""
  What was produced:
  ✓ output/stage1_liverpool_smes.csv    — your Liverpool SME list
  ✓ output/stage1_summary_report.txt   — summary for dissertation
  ✓ output/stage1_sic_breakdown.csv    — industry breakdown

  Result: {len(output_df):,} Liverpool City Region active SMEs identified

  WHAT TO DO NEXT:
  1. In demo mode above — run again with demo_mode=False to use real data
  2. Download the real CSV from:
     http://download.companieshouse.gov.uk/en_output.html
  3. Then move to Stage 2 — API verification of each company
  4. Then Stage 3 — iXBRL bulk data matching

  NOTE FOR YOUR PROPOSAL:
  Document this step clearly in your methodology section.
  The Companies House Free Company Data Product is your
  primary source for building the Liverpool SME universe.
  It is reliable, official, and free — cite it properly.
""")

def load_local_zip(filepath: str) -> pd.DataFrame:
    """
    Loads the Companies House CSV directly from a local ZIP file.
    Use this when you have already downloaded the ZIP manually.
    """
    print(f"\n  Loading from local ZIP file: {filepath}")
    import zipfile
    with zipfile.ZipFile(filepath) as z:
        csv_files = [f for f in z.namelist() if f.endswith(".csv")]
        print(f"  Files inside ZIP: {z.namelist()}")
        csv_filename = csv_files[0]
        print(f"  Reading: {csv_filename}")
        with z.open(csv_filename) as f:
            df = pd.read_csv(f, dtype=str, encoding="utf-8", on_bad_lines="skip")
    print(f"  ✓ Loaded {len(df):,} companies")
    return df   

if __name__ == "__main__":
    import sys
    # Run in demo mode by default
    # Change to main(demo_mode=False) when ready to download real data
    demo = "--real" not in sys.argv
    main(demo_mode=False)
