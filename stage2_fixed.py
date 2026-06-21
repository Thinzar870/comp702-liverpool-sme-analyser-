"""
COMP702 — STAGE 2 FIXED: API Verification of Liverpool SMEs
============================================================
Author:  Thinzar Aung (201942837)
Project: AI-Powered SME Financial Health Analyser for Liverpool

FIXES IN THIS VERSION:
  - Extracts company number from companies_house_uri column
  - Handles missing ixbrl_doc_link column gracefully
  - Better error handling throughout

HOW TO RUN:
  python stage2_fixed.py
"""

import os
import time
import requests
import pandas as pd
from datetime import datetime

os.makedirs("output", exist_ok=True)

# ── Set your API key here ─────────────────────────────────────
API_KEY = "Your_API_Key_Here"

BASE_URL       = "https://api.company-information.service.gov.uk"
DELAY_SECONDS  = 0.6
SAMPLE_SIZE    = 500


# ═══════════════════════════════════════════════════════════════
# HELPER — extract company number from URI
# ═══════════════════════════════════════════════════════════════

def extract_company_number(uri: str) -> str:
    """
    Extracts company number from the companies_house_uri column.
    Example: 'http://business.data.gov.uk/id/company/11878997'
    Returns: '11878997'
    """
    if not uri or pd.isna(uri):
        return ""
    return str(uri).strip().rstrip("/").split("/")[-1]


# ═══════════════════════════════════════════════════════════════
# STEP 1 — LOAD AND SAMPLE
# ═══════════════════════════════════════════════════════════════

def load_and_sample(csv_path: str, sample_size: int) -> pd.DataFrame:
    print("\n" + "="*60)
    print("STEP 1 — LOADING STAGE 1 DATA AND SAMPLING")
    print("="*60)

    if not os.path.exists(csv_path):
        print(f"  ✗ File not found: {csv_path}")
        return pd.DataFrame()

    df = pd.read_csv(csv_path, dtype=str)
    print(f"\n  Loaded {len(df):,} Liverpool SMEs")
    print(f"  Columns: {list(df.columns)}")

    # Extract company number from URI column
    if "companies_house_uri" in df.columns:
        df["company_number"] = df["companies_house_uri"].apply(
            extract_company_number
        )
        valid = df[df["company_number"].str.len() > 0]
        print(f"  Valid company numbers extracted: {len(valid):,}")
        print(f"  Sample from: {valid.iloc[0]['company_number']} "
              f"to {valid.iloc[-1]['company_number']}")
        df = valid
    elif "company_number" in df.columns:
        df["company_number"] = df["company_number"].fillna("").str.strip()
        df = df[df["company_number"].str.len() > 0]
    else:
        print("  ✗ Cannot find company number column")
        print(f"  Available columns: {list(df.columns)}")
        return pd.DataFrame()

    # Sample
    if len(df) <= sample_size:
        sample = df.copy()
    else:
        sample = df.sample(sample_size, random_state=42)

    print(f"  Sampled {len(sample):,} companies for API verification")
    return sample.reset_index(drop=True)


# ═══════════════════════════════════════════════════════════════
# STEP 2 — API CALLS
# ═══════════════════════════════════════════════════════════════

def get_company_profile(company_number: str) -> dict:
    url = f"{BASE_URL}/company/{company_number}"
    try:
        r = requests.get(url, auth=(API_KEY, ""), timeout=10)
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 429:
            print(f"\n  ⚠ Rate limit — waiting 60s...")
            time.sleep(60)
            return get_company_profile(company_number)
        else:
            return {"error": f"http_{r.status_code}"}
    except Exception as e:
        return {"error": str(e)}


def get_filing_history(company_number: str) -> list:
    url = f"{BASE_URL}/company/{company_number}/filing-history"
    try:
        r = requests.get(
            url, auth=(API_KEY, ""),
            params={"category": "accounts", "items_per_page": 5},
            timeout=10
        )
        if r.status_code == 200:
            return r.json().get("items", [])
    except Exception:
        pass
    return []


def extract_fields(company_number: str, profile: dict, filings: list) -> dict:
    if "error" in profile:
        return {
            "company_number":    company_number,
            "api_verified":      False,
            "api_status":        profile.get("error", "unknown"),
            "ixbrl_doc_link":    None,
        }

    address      = profile.get("registered_office_address", {})
    accounts     = profile.get("accounts", {})
    last_accounts = accounts.get("last_accounts", {})

    # Data freshness
    freshness_flag   = "UNKNOWN"
    freshness_months = None
    last_date_str    = last_accounts.get("made_up_to", "")
    if last_date_str:
        try:
            last_date = datetime.strptime(last_date_str, "%Y-%m-%d")
            months_ago = (datetime.now() - last_date).days / 30
            freshness_months = round(months_ago, 1)
            if months_ago > 18:
                freshness_flag = "STALE — over 18 months"
            elif months_ago > 9:
                freshness_flag = "CAUTION — 9 to 18 months"
            else:
                freshness_flag = "FRESH — under 9 months"
        except ValueError:
            pass

    # iXBRL document link
    doc_link     = None
    filing_date  = None
    filing_type  = None
    for filing in filings:
        if filing.get("type") in ["AA", "AAMD"]:
            links    = filing.get("links", {})
            doc_link = links.get("document_metadata")
            filing_date = filing.get("date")
            filing_type = filing.get("type")
            break

    return {
        "company_number":        company_number,
        "company_name":          profile.get("company_name", ""),
        "company_status":        profile.get("company_status", ""),
        "company_type":          profile.get("type", ""),
        "current_postcode":      address.get("postal_code", ""),
        "current_town":          address.get("locality", ""),
        "sic_codes":             "|".join(profile.get("sic_codes", [])),
        "date_of_creation":      profile.get("date_of_creation", ""),
        "last_accounts_date":    last_date_str,
        "last_accounts_type":    last_accounts.get("type", ""),
        "next_accounts_due":     accounts.get("next_due", ""),
        "data_freshness_months": freshness_months,
        "data_freshness_flag":   freshness_flag,
        "has_insolvency":        profile.get("has_insolvency_history", False),
        "has_charges":           profile.get("has_charges", False),
        "ixbrl_doc_link":        doc_link,
        "latest_filing_date":    filing_date,
        "latest_filing_type":    filing_type,
        "api_verified":          True,
        "api_status":            profile.get("company_status", "unknown"),
        "api_called_at":         datetime.now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════
# STEP 3 — VERIFICATION LOOP
# ═══════════════════════════════════════════════════════════════

def run_verification(sample_df: pd.DataFrame) -> pd.DataFrame:
    print("\n" + "="*60)
    print("STEP 2 — RUNNING API VERIFICATION")
    print("="*60)

    total          = len(sample_df)
    est_mins       = (total * DELAY_SECONDS) / 60
    print(f"\n  Companies to verify: {total:,}")
    print(f"  Estimated time:      ~{est_mins:.0f} minutes")
    print(f"  Starting...\n")

    results        = []
    active_count   = 0
    has_ixbrl      = 0
    errors         = 0

    for i, row in sample_df.iterrows():
        company_number = str(row.get("company_number", "")).strip().zfill(8)

        if not company_number or company_number == "00000000":
            continue

        # Progress every 10
        if (i % 10 == 0) or i == 0:
            pct = ((list(sample_df.index).index(i) + 1) / total) * 100
            print(f"  [{list(sample_df.index).index(i)+1:4}/{total}] "
                  f"{pct:5.1f}% — "
                  f"Active: {active_count} | "
                  f"iXBRL: {has_ixbrl} | "
                  f"Errors: {errors}")

        profile  = get_company_profile(company_number)
        filings  = []

        if "error" not in profile:
            filings = get_filing_history(company_number)
            if profile.get("company_status") == "active":
                active_count += 1

        result = extract_fields(company_number, profile, filings)

        if result.get("ixbrl_doc_link"):
            has_ixbrl += 1
        if not result.get("api_verified"):
            errors += 1

        results.append(result)

        # Save progress every 50
        if len(results) % 50 == 0:
            pd.DataFrame(results).to_csv(
                "output/stage2_progress.csv", index=False
            )

        time.sleep(DELAY_SECONDS)

    print(f"\n  ✓ Complete")
    print(f"  Total:         {len(results):,}")
    print(f"  Active:        {active_count:,}")
    print(f"  iXBRL links:   {has_ixbrl:,}")
    print(f"  Errors:        {errors:,}")

    return pd.DataFrame(results)


# ═══════════════════════════════════════════════════════════════
# STEP 4 — SAVE OUTPUTS
# ═══════════════════════════════════════════════════════════════

def save_outputs(results_df: pd.DataFrame):
    print("\n" + "="*60)
    print("STEP 3 — SAVING OUTPUTS")
    print("="*60)

    # All verified
    results_df.to_csv("output/stage2_verified_companies.csv", index=False)
    print(f"\n  ✓ All verified: output/stage2_verified_companies.csv "
          f"({len(results_df):,} rows)")

    # Only those with iXBRL links
    if "ixbrl_doc_link" in results_df.columns:
        ixbrl_df = results_df[
            results_df["ixbrl_doc_link"].notna() &
            (results_df["ixbrl_doc_link"] != "")
        ].copy()
    else:
        ixbrl_df = pd.DataFrame()

    ixbrl_df.to_csv("output/stage2_with_filing_links.csv", index=False)
    print(f"  ✓ With iXBRL links: output/stage2_with_filing_links.csv "
          f"({len(ixbrl_df):,} rows)")

    # Freshness breakdown
    if "data_freshness_flag" in results_df.columns:
        print(f"\n  DATA FRESHNESS:")
        for flag, count in results_df["data_freshness_flag"].value_counts().items():
            print(f"    {flag}: {count:,}")

    # Accounts type breakdown
    if "last_accounts_type" in results_df.columns:
        print(f"\n  ACCOUNTS TYPES:")
        for t, count in results_df["last_accounts_type"].value_counts().head(8).items():
            print(f"    {t}: {count:,}")

    # Summary report
    active = results_df[results_df.get("api_status", pd.Series()) == "active"] \
        if "api_status" in results_df.columns else pd.DataFrame()

    with open("output/stage2_summary_report.txt", "w") as f:
        f.write("="*60 + "\n")
        f.write("COMP702 — STAGE 2 SUMMARY REPORT\n")
        f.write("AI-Powered SME Financial Health Analyser for Liverpool\n")
        f.write(f"Thinzar Aung (201942837)\n")
        f.write(f"Generated: {datetime.now().strftime('%d %B %Y %H:%M')}\n")
        f.write("="*60 + "\n\n")
        f.write("METHOD\n" + "-"*40 + "\n")
        f.write("API: Companies House Public Data REST API\n")
        f.write("Auth: HTTP Basic — API key as username, blank password\n")
        f.write(f"Rate limit respected: {DELAY_SECONDS}s delay between requests\n\n")
        f.write("RESULTS\n" + "-"*40 + "\n")
        f.write(f"Companies sampled:        {len(results_df):,}\n")
        if "api_verified" in results_df.columns:
            f.write(f"Successfully verified:    "
                    f"{results_df['api_verified'].sum():,}\n")
        f.write(f"With iXBRL doc links:     {len(ixbrl_df):,}\n\n")
        f.write("NEXT STEP — STAGE 3\n" + "-"*40 + "\n")
        f.write("Feed stage2_with_filing_links.csv into Stage 3.\n")
        f.write("Stage 3 downloads and parses iXBRL documents.\n")

    print(f"\n  ✓ Summary report saved")
    return ixbrl_df


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    print("\n" + "="*60)
    print("  COMP702 — STAGE 2: API VERIFICATION (FIXED)")
    print("  Thinzar Aung (201942837) — University of Liverpool")
    print("="*60)

    if API_KEY == "YOUR_API_KEY_HERE":
        print("\n  ✗ Please set your API key at the top of this script")
        return

    # Test connection
    print("\n  Testing API connection...")
    test = get_company_profile("07588791")
    if "error" in test:
        print(f"  ✗ API test failed: {test}")
        return
    print(f"  ✓ API working — {test.get('company_name')}")

    sample_df  = load_and_sample("output/stage1_liverpool_smes.csv", SAMPLE_SIZE)
    if sample_df.empty:
        return

    results_df = run_verification(sample_df)
    ixbrl_df   = save_outputs(results_df)

    print("\n" + "="*60)
    print("  STAGE 2 COMPLETE")
    print(f"  {len(ixbrl_df):,} companies ready for Stage 3")
    print("="*60)


if __name__ == "__main__":
    main()
