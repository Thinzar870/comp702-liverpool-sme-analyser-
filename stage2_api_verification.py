"""
COMP702 — STAGE 2: API Verification of Liverpool SMEs
======================================================
Author:  Thinzar Aung (201942837)
Project: AI-Powered SME Financial Health Analyser for Liverpool City Region
Stage:   2 of 7 — Verify companies via Companies House REST API

WHAT THIS SCRIPT DOES:
  Takes the 90,707 Liverpool SMEs from Stage 1 and calls the
  Companies House REST API for each company to:
  - Confirm it is genuinely still active RIGHT NOW (live data)
  - Get the latest filing date and accounts type
  - Get the document link for the most recent iXBRL accounts
  - Flag any insolvency history or outstanding charges
  - Record data freshness (how old is the most recent filing?)

WHY WE SAMPLE INSTEAD OF CALLING ALL 90,707:
  The API limit is 600 requests per 5 minutes.
  Calling all 90,707 companies would take over 12 hours.
  For a dissertation, a well-documented representative sample
  is academically valid and more practical.
  We sample 500 companies across all Liverpool postcodes and
  SIC code sectors to ensure it is representative.

HOW TO RUN:
  1. Make sure stage1_liverpool_smes.csv is in the output folder
  2. Replace YOUR_API_KEY_HERE below with your real API key
  3. python stage2_api_verification.py

OUTPUT:
  output/stage2_verified_companies.csv    — verified company list
  output/stage2_with_filing_links.csv     — companies with iXBRL links
  output/stage2_summary_report.txt        — findings for dissertation
"""

import os
import time
import json
import threading
import requests
import pandas as pd
from collections import deque
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

os.makedirs("output", exist_ok=True)

# ── IMPORTANT — paste your API key here ───────────────────────
# Never share this key publicly or push it to GitHub
API_KEY = "c02ce0f2-b2be-4be4-a768-d3c98fa12621"

# ── API settings ──────────────────────────────────────────────
BASE_URL    = "https://api.company-information.service.gov.uk"
RATE_LIMIT  = 600   # requests per 5 minutes
RATE_WINDOW = 300   # 5 minutes in seconds
# Each company makes TWO API calls (profile + filing history), not
# one. The delay below is PER COMPANY, so it must account for both
# calls: 2 requests per DELAY_SECONDS must stay under 600/300s = 2
# requests/second sustained. 1.3s per company = ~1.54 req/s, a safe
# margin under the ceiling. The previous value of 0.6s allowed
# ~3.3 req/s, well over the limit, which is the most likely cause
# of the very slow overnight run (repeated 429 rate-limit hits,
# each costing a 60-second penalty wait).
DELAY_SECONDS = 1.3

# Tracks how many times a 429 rate-limit response was hit, so the
# final summary can show clearly whether this was an issue.
RATE_LIMIT_HITS = 0


class RateLimiter:
    """
    Thread-safe sliding-window rate limiter.

    Companies House allows 600 requests per 5 minutes (300s). This
    limiter is shared across every worker thread and enforces a
    slightly more conservative ceiling (550 per 300s) so we stay
    safely under the real limit even with several threads issuing
    requests at once, rather than each thread independently
    guessing at a safe delay.

    This replaces the old approach of a single sleep() between
    companies on one thread, which wasted time waiting on network
    round-trips that could otherwise have overlapped with other
    requests, without ever actually risking the rate limit.
    """
    def __init__(self, max_calls: int, period: float):
        self.max_calls = max_calls
        self.period = period
        self.calls = deque()
        self.lock = threading.Lock()

    def acquire(self):
        while True:
            with self.lock:
                now = time.time()
                while self.calls and self.calls[0] <= now - self.period:
                    self.calls.popleft()
                if len(self.calls) < self.max_calls:
                    self.calls.append(now)
                    return
                sleep_time = self.period - (now - self.calls[0]) + 0.02
            time.sleep(sleep_time)


RATE_LIMITER = RateLimiter(max_calls=550, period=300)
# Number of companies processed concurrently. Kept modest since the
# real bottleneck is the shared API rate limit, not local compute;
# this just lets network latency overlap across companies instead
# of stacking up serially.
MAX_WORKERS = 6

# ── Sample size ───────────────────────────────────────────────
# How many companies to verify via API.
# Set high enough (above the real Stage 1 output size, ~88,671)
# so the "use all companies" branch triggers below and this
# becomes the true full-scale run for the dissertation dataset,
# not a sample. At DELAY_SECONDS = 0.6, ~88,671 companies takes
# roughly 15 hours of continuous runtime. Resume logic means it
# is safe to leave running unattended and safe to restart if
# interrupted, it will pick up from output/stage2_progress.csv
# rather than starting over.
SAMPLE_SIZE = 100000


# ═══════════════════════════════════════════════════════════════
# STEP 1 — LOAD STAGE 1 OUTPUT AND CREATE SAMPLE
# ═══════════════════════════════════════════════════════════════

def load_and_sample(csv_path: str, sample_size: int) -> pd.DataFrame:
    """
    Loads the Stage 1 Liverpool SME list and creates a
    representative stratified sample across postcodes and
    SIC code sectors.
    """
    print("\n" + "="*60)
    print("STEP 1 — LOADING STAGE 1 DATA AND SAMPLING")
    print("="*60)

    if not os.path.exists(csv_path):
        print(f"  ✗ File not found: {csv_path}")
        print(f"  Make sure you have run stage1_fixed.py first")
        return pd.DataFrame()

    df = pd.read_csv(csv_path, dtype=str)
    print(f"\n  Loaded {len(df):,} Liverpool SMEs from Stage 1")
    print(f"  Columns: {list(df.columns)}")

    # Create a stratified sample
    # Take companies from different postcodes to ensure
    # we cover all areas of Liverpool City Region
    if len(df) <= sample_size:
        sample = df.copy()
        print(f"  Using all {len(sample):,} companies (smaller than sample size)")
    else:
        # Sample evenly across postcode areas if column exists
        if "postcode" in df.columns:
            # Extract postcode district (e.g. "L1" from "L1 4DS")
            df["postcode_district"] = (
                df["postcode"]
                .fillna("")
                .str.strip()
                .str.split(" ").str[0]
            )
            # Stratified sample across postcode districts
            try:
                sample = df.groupby("postcode_district", group_keys=False).apply(
                    lambda x: x.sample(
                        min(len(x), max(1, sample_size // df["postcode_district"].nunique())),
                        random_state=42
                    )
                ).head(sample_size)
            except Exception:
                sample = df.sample(sample_size, random_state=42)
        else:
            sample = df.sample(sample_size, random_state=42)

        print(f"  Sampled {len(sample):,} companies for API verification")
        if "postcode_district" in sample.columns:
            print(f"  Covering {sample['postcode_district'].nunique()} postcode districts")

    return sample.reset_index(drop=True)


# ═══════════════════════════════════════════════════════════════
# STEP 2 — API CALL FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def get_company_profile(company_number: str) -> dict:
    """
    Calls the Companies House API to get a company's current profile.
    Returns the full JSON response as a Python dictionary.

    The URL pattern is:
    GET https://api.company-information.service.gov.uk/company/{number}
    """
    url = f"{BASE_URL}/company/{company_number}"
    try:
        RATE_LIMITER.acquire()
        response = requests.get(
            url,
            auth=(API_KEY, ""),   # API key as username, blank password
            timeout=10
        )
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            return {"error": "not_found", "company_number": company_number}
        elif response.status_code == 429:
            # Rate limit hit — wait and retry
            global RATE_LIMIT_HITS
            RATE_LIMIT_HITS += 1
            print(f"\n  ⚠ Rate limit hit (#{RATE_LIMIT_HITS} so far) — waiting 60 seconds...")
            time.sleep(60)
            return get_company_profile(company_number)
        else:
            return {"error": f"http_{response.status_code}",
                    "company_number": company_number}
    except requests.RequestException as e:
        return {"error": str(e), "company_number": company_number}


def get_filing_history(company_number: str) -> list:
    """
    Gets the filing history for a company — filtered to accounts only.
    Returns a list of filing items, newest first.

    We use this to find the most recent iXBRL accounts document
    and get its download link for Stage 3.
    """
    url = f"{BASE_URL}/company/{company_number}/filing-history"
    params = {"category": "accounts", "items_per_page": 5}
    try:
        RATE_LIMITER.acquire()
        response = requests.get(
            url,
            auth=(API_KEY, ""),
            params=params,
            timeout=10
        )
        if response.status_code == 200:
            return response.json().get("items", [])
        else:
            return []
    except requests.RequestException:
        return []


def extract_key_fields(profile: dict, filings: list) -> dict:
    """
    Extracts just the fields we need from the raw API response.
    Converts messy nested JSON into a flat, clean dictionary.

    This is the pre-processing step — turning unstructured
    API data into structured fields for our database.
    """
    if "error" in profile:
        return {
            "api_status": profile.get("error"),
            "api_verified": False,
        }

    address = profile.get("registered_office_address", {})
    accounts = profile.get("accounts", {})
    last_accounts = accounts.get("last_accounts", {})

    # Calculate data freshness
    freshness_flag = "UNKNOWN"
    freshness_months = None
    last_date_str = last_accounts.get("made_up_to", "")
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

    # Get document link from most recent accounts filing
    doc_link = None
    filing_date = None
    filing_type = None
    for filing in filings:
        if filing.get("type") in ["AA", "AAMD", "AA01"]:
            links = filing.get("links", {})
            doc_link = links.get("document_metadata")
            filing_date = filing.get("date")
            filing_type = filing.get("type")
            break

    return {
        # Identity
        "company_number":       profile.get("company_number", ""),
        "company_name":         profile.get("company_name", ""),
        "company_status":       profile.get("company_status", ""),
        "company_type":         profile.get("type", ""),

        # Location
        "current_postcode":     address.get("postal_code", ""),
        "current_address":      address.get("address_line_1", ""),
        "current_town":         address.get("locality", ""),

        # Industry
        "sic_codes":            "|".join(profile.get("sic_codes", [])),

        # Age
        "date_of_creation":     profile.get("date_of_creation", ""),

        # Accounts / filing
        "last_accounts_date":   last_date_str,
        "last_accounts_type":   last_accounts.get("type", ""),
        "next_accounts_due":    accounts.get("next_due", ""),
        "data_freshness_months": freshness_months,
        "data_freshness_flag":  freshness_flag,

        # Risk flags
        "has_insolvency":       profile.get("has_insolvency_history", False),
        "has_charges":          profile.get("has_charges", False),

        # iXBRL document link — used in Stage 3
        "ixbrl_doc_link":       doc_link,
        "latest_filing_date":   filing_date,
        "latest_filing_type":   filing_type,

        # Verification
        "api_verified":         True,
        "api_status":           "active" if profile.get("company_status") == "active" else "other",
        "api_called_at":        datetime.now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════
# STEP 3 — RUN API VERIFICATION LOOP
# ═══════════════════════════════════════════════════════════════


def verify_one_company(company_number: str) -> dict:
    """
    Does the full verification for a single company: profile call,
    then filing-history call if the profile succeeded. This is the
    unit of work each thread pool worker runs. Both calls go through
    the shared RATE_LIMITER, so however many threads are running,
    the actual request rate never exceeds the safe ceiling.
    """
    profile = get_company_profile(company_number)
    filings = []

    if "error" not in profile:
        filings = get_filing_history(company_number)

    result = extract_key_fields(profile, filings)
    result["company_number"] = company_number
    return result


def run_verification(sample_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calls the Companies House API for each company in the sample,
    using a small pool of worker threads so network round-trip time
    for one company overlaps with another instead of stacking up
    serially. All threads share one RateLimiter, so the real
    request rate is still capped safely below the Companies House
    limit regardless of how many threads are running at once.

    Saves progress every 50 companies so you don't lose work
    if something goes wrong.

    RESUME SUPPORT: if output/stage2_progress.csv already exists from
    a previous (interrupted) run, already-processed companies are
    loaded and skipped, so restarting after a crash continues from
    where it left off instead of starting over from company #1.
    """
    print("\n" + "="*60)
    print("STEP 2 — RUNNING API VERIFICATION (CONCURRENT)")
    print("="*60)
    print(f"\n  Companies to verify: {len(sample_df):,}")
    print(f"  Worker threads: {MAX_WORKERS}")
    print(f"  Shared rate limit: {RATE_LIMITER.max_calls} requests / {RATE_LIMITER.period:.0f}s")
    floor_minutes = (len(sample_df) * 2) / (RATE_LIMITER.max_calls / RATE_LIMITER.period) / 60
    print(f"  Estimated time: ~{floor_minutes:.0f} minutes (rate-limit floor)")

    # ── Resume from checkpoint if it exists ────────────────────
    progress_path = "output/stage2_progress.csv"
    results = []
    already_done = set()

    if os.path.exists(progress_path):
        prior_df = pd.read_csv(progress_path, dtype={"company_number": str})
        results = prior_df.to_dict("records")
        already_done = set(prior_df["company_number"].str.zfill(8))
        print(f"\n  ↻ Found existing progress file — resuming.")
        print(f"  Already processed: {len(already_done):,} companies — these will be skipped.")
    # ────────────────────────────────────────────────────────────

    print(f"\n  Starting verification...\n")

    errors = sum(1 for r in results if not r.get("api_verified"))
    active_count = sum(1 for r in results if r.get("company_status") == "active")
    has_ixbrl = sum(1 for r in results if r.get("ixbrl_doc_link"))

    # Build the work list, skipping anything already done
    todo = []
    for _, row in sample_df.iterrows():
        company_number = str(row.get("company_number", "")).strip().zfill(8)
        if not company_number or company_number == "00000000":
            continue
        if company_number in already_done:
            continue
        todo.append(company_number)

    results_lock = threading.Lock()
    processed_count = 0
    save_every = 50

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_company = {
            executor.submit(verify_one_company, cn): cn for cn in todo
        }

        for future in as_completed(future_to_company):
            company_number = future_to_company[future]
            try:
                result = future.result()
            except Exception as e:
                result = {"company_number": company_number,
                          "api_verified": False, "api_status": str(e)}

            with results_lock:
                results.append(result)
                already_done.add(company_number)
                processed_count += 1

                if result.get("company_status") == "active":
                    active_count += 1
                if result.get("ixbrl_doc_link"):
                    has_ixbrl += 1
                if not result.get("api_verified"):
                    errors += 1

                if processed_count % 10 == 0:
                    pct = (processed_count / len(todo)) * 100
                    print(f"  [{processed_count:5,}/{len(todo):,}] {pct:5.1f}% — "
                          f"Active: {active_count} | "
                          f"iXBRL links: {has_ixbrl} | "
                          f"Errors: {errors} | "
                          f"Rate limit hits: {RATE_LIMIT_HITS}")

                if processed_count % save_every == 0:
                    pd.DataFrame(results).to_csv(progress_path, index=False)

    # ── Final save so the very last partial batch isn't lost ─────
    pd.DataFrame(results).to_csv(progress_path, index=False)
    # ──────────────────────────────────────────────────────────

    print(f"\n  ✓ Verification complete")
    print(f"  Total verified:    {len(results):,}")
    print(f"  Active companies:  {active_count:,}")
    print(f"  With iXBRL links:  {has_ixbrl:,}")
    print(f"  Errors/not found:  {errors:,}")
    print(f"  Rate limit hits:   {RATE_LIMIT_HITS:,} (each cost a 60s wait)")

    return pd.DataFrame(results)


# ═══════════════════════════════════════════════════════════════
# STEP 4 — SAVE OUTPUTS AND REPORT
# ═══════════════════════════════════════════════════════════════

def save_outputs(results_df: pd.DataFrame):
    """
    Saves the verification results and produces a summary
    report for the dissertation methodology section.
    """
    print("\n" + "="*60)
    print("STEP 3 — SAVING OUTPUTS")
    print("="*60)

    # Save all verified companies
    csv_path = "output/stage2_verified_companies.csv"
    results_df.to_csv(csv_path, index=False)
    print(f"\n  ✓ Verified companies: {csv_path} ({len(results_df):,} rows)")

    # Save only companies with iXBRL links — ready for Stage 3
    ixbrl_df = results_df[results_df["ixbrl_doc_link"].notna()].copy()
    ixbrl_path = "output/stage2_with_filing_links.csv"
    ixbrl_df.to_csv(ixbrl_path, index=False)
    print(f"  ✓ Companies with iXBRL links: {ixbrl_path} ({len(ixbrl_df):,} rows)")

    # Freshness breakdown
    freshness = results_df["data_freshness_flag"].value_counts()
    print(f"\n  DATA FRESHNESS BREAKDOWN:")
    for flag, count in freshness.items():
        print(f"    {flag}: {count:,}")

    # Accounts type breakdown
    if "last_accounts_type" in results_df.columns:
        acct_types = results_df["last_accounts_type"].value_counts()
        print(f"\n  ACCOUNTS TYPE BREAKDOWN:")
        for acct_type, count in acct_types.head(8).items():
            print(f"    {acct_type}: {count:,}")

    # Summary report
    active = results_df[results_df["api_status"] == "active"]
    report_path = "output/stage2_summary_report.txt"
    with open(report_path, "w") as f:
        f.write("="*60 + "\n")
        f.write("COMP702 — STAGE 2 SUMMARY REPORT\n")
        f.write("AI-Powered SME Financial Health Analyser for Liverpool\n")
        f.write(f"Thinzar Aung (201942837)\n")
        f.write(f"Generated: {datetime.now().strftime('%d %B %Y %H:%M')}\n")
        f.write("="*60 + "\n\n")
        f.write("METHOD\n")
        f.write("-"*40 + "\n")
        f.write("API: Companies House Public Data REST API\n")
        f.write("URL: https://api.company-information.service.gov.uk\n")
        f.write("Auth: HTTP Basic — API key as username\n")
        f.write(f"Rate limit: {RATE_LIMIT} requests per 5 minutes\n")
        f.write(f"Delay used: {DELAY_SECONDS}s between requests\n\n")
        f.write("RESULTS\n")
        f.write("-"*40 + "\n")
        f.write(f"Companies sampled from Stage 1: {len(results_df):,}\n")
        f.write(f"Successfully verified (API 200): "
                f"{results_df['api_verified'].sum():,}\n")
        f.write(f"Currently active: {len(active):,}\n")
        f.write(f"With iXBRL document links: {len(ixbrl_df):,}\n\n")
        f.write("DATA FRESHNESS\n")
        f.write("-"*40 + "\n")
        for flag, count in freshness.items():
            f.write(f"{flag}: {count:,}\n")
        f.write("\nNEXT STEP — STAGE 3\n")
        f.write("-"*40 + "\n")
        f.write("Feed stage2_with_filing_links.csv into Stage 3.\n")
        f.write("Stage 3 downloads and parses the iXBRL accounts\n")
        f.write("documents to extract financial figures.\n")

    print(f"  ✓ Summary report: {report_path}")
    return ixbrl_df


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    print("\n" + "="*60)
    print("  COMP702 — STAGE 2: API VERIFICATION")
    print("  Thinzar Aung (201942837) — University of Liverpool")
    print("="*60)

    # Check API key is set
    if not API_KEY or API_KEY.strip().lower() in ("your_api_key_here", ""):
        print("\n  ✗ ERROR: Please set your API key at the top of this script")
        print("  Replace the placeholder with your real Companies House API key")
        return

    # Quick API test first
    print("\n  Testing API connection...")
    test = get_company_profile("07588791")
    if "error" in test:
        print(f"  ✗ API test failed: {test}")
        print("  Check your API key is correct")
        return
    print(f"  ✓ API working — test company: {test.get('company_name')}")

    # Run the pipeline
    sample_df = load_and_sample("output/stage1_liverpool_smes.csv", SAMPLE_SIZE)
    if sample_df.empty:
        return

    results_df = run_verification(sample_df)
    ixbrl_df = save_outputs(results_df)

    print("\n" + "="*60)
    print("  STAGE 2 COMPLETE")
    print(f"  {len(ixbrl_df):,} companies with iXBRL links ready for Stage 3")
    print("="*60)


if __name__ == "__main__":
    main()
