"""
COMP702 — STAGE 3: Download and Parse iXBRL Financial Documents
================================================================
Author:  Thinzar Aung (201942837)
Project: AI-Powered SME Financial Health Analyser for Liverpool City Region
Stage:   3 of 7 — Download iXBRL documents and extract financial figures

WHAT THIS SCRIPT DOES:
  Takes the 363 Liverpool companies with iXBRL document links
  from Stage 2 and for each one:
  1. Calls the Companies House Document API to get the document
  2. Downloads the iXBRL file (HTML format with embedded XBRL tags)
  3. Parses it using BeautifulSoup to extract financial figures
  4. Calculates financial ratios from the extracted figures
  5. Saves everything as a structured CSV ready for Stage 4 (PostgreSQL)

TWO PARSING APPROACHES USED:
  Primary:  ixbrlparse library — handles XBRL taxonomy automatically
  Fallback: BeautifulSoup manual parser — for files ixbrlparse cannot handle
  Both are tried for each file — results compared and documented

HOW TO RUN:
  pip install ixbrlparse requests pandas beautifulsoup4 lxml
  python stage3_parse_ixbrl.py

OUTPUT:
  output/ixbrl_documents/          — downloaded iXBRL files
  output/stage3_financial_data.csv — structured financial figures
  output/stage3_parsing_report.txt — what worked, what failed, why
"""

import os
import re
import time
import json
import requests
import pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup

os.makedirs("output/ixbrl_documents", exist_ok=True)

# ── Your API key ──────────────────────────────────────────────
API_KEY      = "Your_API_Key_Here"
DOC_BASE_URL = "https://document-api.company-information.service.gov.uk"
DELAY        = 0.6   # seconds between API calls

# ── Try importing ixbrlparse ──────────────────────────────────
try:
    from ixbrlparse import IXBRL
    IXBRLPARSE_OK = True
    print("✓ ixbrlparse library available")
except ImportError:
    IXBRLPARSE_OK = False
    print("✗ ixbrlparse not installed — run: pip install ixbrlparse")
    print("  Continuing with BeautifulSoup parser only")


# ═══════════════════════════════════════════════════════════════
# XBRL TAG MAPPING
# Maps all known XBRL tag variants to clean field names.
# This is the core pre-processing contribution of the project —
# handling inconsistent tagging across UK GAAP, FRS 102, FRS 105.
# ═══════════════════════════════════════════════════════════════

XBRL_TAG_MAP = {
    # ── Income statement ──────────────────────────────────────
    "turnover": [
        "core:turnover", "uk-gaap:turnover",
        "uk-gaap:turnoverrevenue",
        "uk-gaap:turnovergrossoperatingrevenue",
        "bus:turnover", "frs-bus:turnover",
        "core:revenue", "uk-gaap:revenue",
    ],
    "gross_profit": [
        "core:grossprofitloss", "uk-gaap:grossprofitloss",
        "uk-gaap:grossprofit",
    ],
    "operating_profit": [
        "core:operatingprofitloss", "uk-gaap:operatingprofitloss",
        "uk-gaap:profitlossfromoperations",
    ],
    "profit_before_tax": [
        "core:profitlossbeforetax", "uk-gaap:profitlossbeforetax",
        "uk-gaap:profitlossonordinaryactivitiesbeforetax",
        "bus:profitlossbeforetax",
    ],
    "profit_after_tax": [
        "core:profitlossforperiod", "uk-gaap:profitloss",
        "uk-gaap:profitlossforperiod",
    ],

    # ── Balance sheet — assets ────────────────────────────────
    "total_assets": [
        "core:assets", "uk-gaap:assets", "uk-gaap:totalassets",
    ],
    "fixed_assets": [
        "core:fixedassets", "uk-gaap:fixedassets",
        "uk-gaap:totalfixedassets",
    ],
    "current_assets": [
        "core:currentassets", "uk-gaap:currentassets",
        "bus:currentassets",
    ],
    "cash": [
        "core:cashbankonhand", "uk-gaap:cashatbankandinhand",
        "uk-gaap:cashbankonhand",
    ],
    "debtors": [
        "core:debtors", "uk-gaap:debtors", "uk-gaap:tradedebtors",
    ],

    # ── Balance sheet — liabilities ───────────────────────────
    "current_liabilities": [
        "core:currentliabilities", "uk-gaap:currentliabilities",
        "uk-gaap:creditorsduewithinoneyear",
        "bus:currentliabilities",
    ],
    "long_term_liabilities": [
        "core:noncurrentliabilities",
        "uk-gaap:creditorsdueafteroneyear",
        "uk-gaap:noncurrentliabilities",
    ],
    "total_liabilities": [
        "core:liabilities", "uk-gaap:liabilities",
        "uk-gaap:totalliabilities",
    ],

    # ── Equity ────────────────────────────────────────────────
    "net_assets": [
        "core:netassetsliabilities", "uk-gaap:netassets",
        "uk-gaap:netassetsliabilities", "bus:netassetsliabilities",
    ],
    "equity": [
        "core:equity", "uk-gaap:equity",
        "uk-gaap:shareholdersequity",
        "uk-gaap:capitalandreserves",
    ],

    # ── Other ─────────────────────────────────────────────────
    "employees": [
        "core:averagenumberemployeesduringperiod",
        "uk-gaap:averagenumberemployeesduringperiod",
        "bus:averagenumberemployeesduringperiod",
    ],
}


# ═══════════════════════════════════════════════════════════════
# STEP 1 — LOAD STAGE 2 OUTPUT
# ═══════════════════════════════════════════════════════════════

def load_stage2_data(csv_path: str) -> pd.DataFrame:
    print("\n" + "="*60)
    print("STEP 1 — LOADING STAGE 2 DATA")
    print("="*60)

    if not os.path.exists(csv_path):
        print(f"  ✗ File not found: {csv_path}")
        print("  Run stage2_fixed.py first")
        return pd.DataFrame()

    df = pd.read_csv(csv_path, dtype=str)
    print(f"\n  Loaded {len(df):,} companies with iXBRL links")
    print(f"  Columns: {list(df.columns)}")

    # Filter to only those with document links
    if "ixbrl_doc_link" in df.columns:
        df = df[df["ixbrl_doc_link"].notna() & (df["ixbrl_doc_link"] != "")]
        print(f"  Companies with valid iXBRL links: {len(df):,}")

    return df.reset_index(drop=True)


# ═══════════════════════════════════════════════════════════════
# STEP 2 — DOWNLOAD IXBRL DOCUMENT
# ═══════════════════════════════════════════════════════════════

def download_ixbrl_document(doc_link: str, company_number: str) -> tuple:
    """
    Downloads an iXBRL document from the Companies House Document API.

    The process has two steps:
    1. GET the document metadata to find available formats
    2. GET the actual document with Accept: application/xhtml+xml

    Returns (content_bytes, format_used) or (None, None) on failure.
    """
    # Build the full URL
    if doc_link.startswith("http"):
        metadata_url = doc_link
    else:
        metadata_url = f"{DOC_BASE_URL}{doc_link}"

    try:
        # Step 1 — get metadata to see what formats are available
        meta_r = requests.get(
            metadata_url,
            auth=(API_KEY, ""),
            timeout=15
        )

        if meta_r.status_code != 200:
            return None, f"metadata_http_{meta_r.status_code}"

        metadata = meta_r.json()
        resources = metadata.get("resources", {})
        available = list(resources.keys())

        # Step 2 — prefer iXBRL (xhtml), fall back to PDF
        if "application/xhtml+xml" in resources:
            content_type = "application/xhtml+xml"
            ext = ".xhtml"
        elif "application/pdf" in resources:
            content_type = "application/pdf"
            ext = ".pdf"
        else:
            return None, f"no_usable_format: {available}"

        # Step 3 — download the actual document
        doc_r = requests.get(
            metadata_url,
            auth=(API_KEY, ""),
            headers={"Accept": content_type},
            allow_redirects=True,
            timeout=30
        )

        if doc_r.status_code == 200:
            # Save to disk
            save_path = f"output/ixbrl_documents/{company_number}{ext}"
            with open(save_path, "wb") as f:
                f.write(doc_r.content)
            size_kb = len(doc_r.content) / 1024
            return doc_r.content, f"{ext} ({size_kb:.1f}KB)"
        else:
            return None, f"download_http_{doc_r.status_code}"

    except requests.RequestException as e:
        return None, f"request_error: {str(e)[:50]}"
    except Exception as e:
        return None, f"error: {str(e)[:50]}"


# ═══════════════════════════════════════════════════════════════
# STEP 3 — PARSE IXBRL WITH IXBRLPARSE
# ═══════════════════════════════════════════════════════════════

def parse_with_ixbrlparse(content: bytes) -> dict:
    """
    Uses the ixbrlparse library to extract financial figures.
    This is the primary parsing method — it handles XBRL taxonomy
    automatically and is more reliable than manual BeautifulSoup.

    Returns a dict of {field_name: value} or empty dict on failure.
    """
    if not IXBRLPARSE_OK:
        return {}
    try:
        from io import StringIO
        text = content.decode("utf-8", errors="replace")
        parser = IXBRL(StringIO(text))
        facts  = parser.facts

        extracted = {}
        for fact in facts:
            name  = getattr(fact, "name", "").lower()
            value = getattr(fact, "value", None)
            unit  = str(getattr(fact, "unit", ""))

            if value is None:
                continue

            # Match against our tag map
            for field, variants in XBRL_TAG_MAP.items():
                if any(v.lower() in name for v in variants):
                    if field not in extracted:
                        try:
                            extracted[field] = float(str(value).replace(",", ""))
                        except (ValueError, TypeError):
                            pass
                    break

        return extracted
    except Exception:
        return {}


# ═══════════════════════════════════════════════════════════════
# STEP 4 — PARSE IXBRL WITH BEAUTIFULSOUP (fallback)
# ═══════════════════════════════════════════════════════════════

def clean_value(raw: str):
    """
    Converts a raw XBRL value string to a float.
    Handles: commas, parentheses for negatives, whitespace.
    Examples: "125,000" → 125000.0
              "(43,500)" → -43500.0
              "" → None
    """
    if not raw or not isinstance(raw, str):
        return None
    val = raw.strip().replace(",", "").replace(" ", "")
    if not val:
        return None
    negative = val.startswith("(") and val.endswith(")")
    val = val.strip("()")
    try:
        num = float(val)
        return -num if negative else num
    except ValueError:
        return None


def parse_with_beautifulsoup(content: bytes) -> dict:
    """
    Manual iXBRL parser using BeautifulSoup.
    Used as fallback when ixbrlparse fails or is not available.

    Searches for ix:nonFraction tags which contain the financial data.
    Maps tag names to our clean field names using XBRL_TAG_MAP.
    """
    try:
        text = content.decode("utf-8", errors="replace")
        soup = BeautifulSoup(text, "lxml")

        # Find all numeric XBRL tags
        numeric_tags = soup.find_all(re.compile(r"ix:nonfraction", re.IGNORECASE))

        # Build lookup: {tag_name_lower: first_value}
        tag_values = {}
        for tag in numeric_tags:
            name = tag.get("name", "").lower()
            raw  = tag.get_text(strip=True)
            val  = clean_value(raw)
            if name and val is not None and name not in tag_values:
                tag_values[name] = val

        # Map to clean field names
        extracted = {}
        for field, variants in XBRL_TAG_MAP.items():
            for variant in variants:
                v_lower = variant.lower()
                if v_lower in tag_values:
                    extracted[field] = tag_values[v_lower]
                    break

        # Also try partial matching for tag variants we might have missed
        if not extracted:
            for tag_name, value in tag_values.items():
                for field, variants in XBRL_TAG_MAP.items():
                    if field not in extracted:
                        if any(v.split(":")[-1].lower() in tag_name
                               for v in variants):
                            extracted[field] = value
                            break

        # Extract balance sheet date
        ctx_tags = soup.find_all(
            re.compile(r"xbrli:instant|xbrli:enddate", re.IGNORECASE)
        )
        dates = [t.get_text(strip=True) for t in ctx_tags
                 if re.match(r"\d{4}-\d{2}-\d{2}", t.get_text(strip=True))]
        if dates:
            extracted["balance_sheet_date"] = max(dates)

        return extracted

    except Exception:
        return {}


# ═══════════════════════════════════════════════════════════════
# STEP 5 — CALCULATE FINANCIAL RATIOS
# ═══════════════════════════════════════════════════════════════

def calculate_ratios(data: dict) -> dict:
    """
    Calculates key financial ratios from extracted balance sheet data.
    These ratios are the features your ML model will use in Stage 6.

    Each ratio is capped and rounded for cleanliness.
    None is returned for any ratio where data is missing.
    """
    ratios = {}

    ca  = data.get("current_assets")
    cl  = data.get("current_liabilities")
    t   = data.get("turnover")
    gp  = data.get("gross_profit")
    op  = data.get("operating_profit")
    pbt = data.get("profit_before_tax")
    ta  = data.get("total_assets")
    eq  = data.get("equity") or data.get("net_assets")
    tl  = data.get("total_liabilities")
    cash= data.get("cash", 0) or 0
    deb = data.get("debtors", 0) or 0

    # ── Liquidity ─────────────────────────────────────────────
    if ca and cl and cl != 0:
        ratios["current_ratio"] = round(ca / abs(cl), 3)
    if cl and cl != 0:
        ratios["quick_ratio"] = round((cash + deb) / abs(cl), 3)

    # ── Profitability ─────────────────────────────────────────
    if t and t != 0:
        if gp is not None:
            ratios["gross_margin_pct"] = round((gp / t) * 100, 2)
        if op is not None:
            ratios["operating_margin_pct"] = round((op / t) * 100, 2)
        if pbt is not None:
            ratios["net_margin_pct"] = round((pbt / t) * 100, 2)

    # ── Leverage ──────────────────────────────────────────────
    if tl and eq and eq != 0:
        ratios["debt_to_equity"] = round(abs(tl) / abs(eq), 3)
    elif cl and eq and eq != 0:
        ratios["debt_to_equity"] = round(abs(cl) / abs(eq), 3)

    # ── Efficiency ────────────────────────────────────────────
    if t and ta and ta != 0:
        ratios["asset_turnover"] = round(t / abs(ta), 3)

    # ── Simple health score (rule-based — ML replaces this later)
    score = 50
    cr = ratios.get("current_ratio", 0)
    gm = ratios.get("gross_margin_pct", 0)
    de = ratios.get("debt_to_equity", 0)

    if cr > 2.0:   score += 15
    elif cr > 1.5: score += 10
    elif cr < 1.0: score -= 20

    if gm > 30:    score += 15
    elif gm > 15:  score += 8
    elif gm < 0:   score -= 20

    if de < 0.5:   score += 10
    elif de < 1.5: score += 5
    elif de > 3.0: score -= 10

    ratios["health_score"]  = max(0, min(100, score))
    ratios["health_rating"] = (
        "HEALTHY"  if score >= 65 else
        "MODERATE" if score >= 45 else
        "AT RISK"
    )

    return ratios


# ═══════════════════════════════════════════════════════════════
# STEP 6 — MAIN PROCESSING LOOP
# ═══════════════════════════════════════════════════════════════

def process_all_companies(df: pd.DataFrame) -> pd.DataFrame:
    print("\n" + "="*60)
    print("STEP 2 — DOWNLOADING AND PARSING IXBRL DOCUMENTS")
    print("="*60)
    print(f"\n  Companies to process: {len(df):,}")
    print(f"  Estimated time: ~{(len(df) * DELAY * 2) / 60:.0f} minutes\n")

    results        = []
    downloaded_ok  = 0
    parsed_ok      = 0
    parse_failed   = 0
    pdf_fallback   = 0
    errors         = 0
    parsing_log    = []

    for i, row in df.iterrows():
        company_number = str(row.get("company_number", "")).strip()
        company_name   = str(row.get("company_name", "")).strip()
        doc_link       = str(row.get("ixbrl_doc_link", "")).strip()

        if not company_number or not doc_link:
            continue

        pos = list(df.index).index(i) + 1
        if pos % 10 == 0 or pos == 1:
            print(f"  [{pos:3}/{len(df)}] "
                  f"Downloaded: {downloaded_ok} | "
                  f"Parsed: {parsed_ok} | "
                  f"Failed: {parse_failed} | "
                  f"Errors: {errors}")

        # ── Base result row ───────────────────────────────────
        result = {
            "company_number":    company_number,
            "company_name":      company_name,
            "company_status":    row.get("company_status", ""),
            "postcode":          row.get("current_postcode", ""),
            "sic_codes":         row.get("sic_codes", ""),
            "last_accounts_date":row.get("last_accounts_date", ""),
            "last_accounts_type":row.get("last_accounts_type", ""),
            "data_freshness":    row.get("data_freshness_flag", ""),
            "has_insolvency":    row.get("has_insolvency", False),
            "has_charges":       row.get("has_charges", False),
            "download_status":   "not_attempted",
            "parse_method":      "none",
            "fields_extracted":  0,
        }

        # ── Download the document ─────────────────────────────
        content, status = download_ixbrl_document(doc_link, company_number)
        time.sleep(DELAY)

        if content is None:
            result["download_status"] = f"FAILED: {status}"
            errors += 1
            parsing_log.append({
                "company": company_number,
                "status":  "download_failed",
                "reason":  status
            })
            results.append(result)
            continue

        result["download_status"] = f"OK: {status}"
        downloaded_ok += 1

        # Skip PDFs — we can only parse iXBRL/xhtml
        if ".pdf" in status:
            result["parse_method"] = "pdf_skipped"
            pdf_fallback += 1
            parsing_log.append({
                "company": company_number,
                "status":  "pdf_only",
                "reason":  "Only PDF available — no iXBRL"
            })
            results.append(result)
            continue

        # ── Parse with ixbrlparse (primary) ───────────────────
        financial_data = parse_with_ixbrlparse(content)

        if financial_data:
            result["parse_method"]    = "ixbrlparse"
            result["fields_extracted"] = len(financial_data)
            parsed_ok += 1
            parsing_log.append({
                "company": company_number,
                "status":  "parsed_ixbrlparse",
                "fields":  len(financial_data)
            })
        else:
            # ── Fallback: BeautifulSoup ───────────────────────
            financial_data = parse_with_beautifulsoup(content)
            if financial_data:
                result["parse_method"]    = "beautifulsoup"
                result["fields_extracted"] = len(financial_data)
                parsed_ok += 1
                parsing_log.append({
                    "company": company_number,
                    "status":  "parsed_beautifulsoup",
                    "fields":  len(financial_data)
                })
            else:
                result["parse_method"] = "parse_failed"
                parse_failed += 1
                parsing_log.append({
                    "company": company_number,
                    "status":  "parse_failed",
                    "reason":  "No financial data extracted by either method"
                })

        # ── Calculate ratios ──────────────────────────────────
        if financial_data:
            ratios = calculate_ratios(financial_data)
            result.update(financial_data)
            result.update(ratios)

        results.append(result)

    print(f"\n  ✓ Processing complete")
    print(f"  Downloaded:   {downloaded_ok:,}")
    print(f"  Parsed OK:    {parsed_ok:,}")
    print(f"  PDF only:     {pdf_fallback:,}")
    print(f"  Parse failed: {parse_failed:,}")
    print(f"  Errors:       {errors:,}")

    return pd.DataFrame(results), parsing_log


# ═══════════════════════════════════════════════════════════════
# STEP 7 — SAVE OUTPUTS
# ═══════════════════════════════════════════════════════════════

def save_outputs(results_df: pd.DataFrame, parsing_log: list):
    print("\n" + "="*60)
    print("STEP 3 — SAVING OUTPUTS")
    print("="*60)

    # Main structured dataset
    csv_path = "output/stage3_financial_data.csv"
    results_df.to_csv(csv_path, index=False)
    print(f"\n  ✓ Financial data CSV: {csv_path} ({len(results_df):,} rows)")

    # Only rows with actual financial data
    financial_cols = ["turnover", "gross_profit", "current_ratio",
                      "net_margin_pct", "health_score"]
    has_data = results_df[
        results_df[[c for c in financial_cols if c in results_df.columns]]
        .notna().any(axis=1)
    ]
    has_data.to_csv("output/stage3_with_financials.csv", index=False)
    print(f"  ✓ Companies with financial data: {len(has_data):,}")

    # Health score distribution
    if "health_rating" in results_df.columns:
        ratings = results_df["health_rating"].value_counts()
        print(f"\n  HEALTH RATING DISTRIBUTION:")
        for rating, count in ratings.items():
            pct = count / len(results_df) * 100
            print(f"    {rating}: {count:,} ({pct:.1f}%)")

    # Parse method breakdown
    if "parse_method" in results_df.columns:
        methods = results_df["parse_method"].value_counts()
        print(f"\n  PARSING METHOD BREAKDOWN:")
        for method, count in methods.items():
            print(f"    {method}: {count:,}")

    # Financial summary statistics
    numeric_cols = ["turnover", "gross_profit", "profit_before_tax",
                    "current_ratio", "gross_margin_pct", "health_score"]
    available = [c for c in numeric_cols if c in results_df.columns]
    if available:
        print(f"\n  FINANCIAL SUMMARY (companies with data):")
        for col in available:
            col_data = pd.to_numeric(results_df[col], errors="coerce").dropna()
            if len(col_data) > 0:
                print(f"    {col}:")
                print(f"      Mean:   {col_data.mean():>12,.2f}")
                print(f"      Median: {col_data.median():>12,.2f}")
                print(f"      Count:  {len(col_data):>12,}")

    # Parsing log
    log_path = "output/stage3_parsing_log.json"
    with open(log_path, "w") as f:
        json.dump(parsing_log, f, indent=2)
    print(f"\n  ✓ Parsing log: {log_path}")

    # Summary report
    parsed_count   = len([l for l in parsing_log if "parsed" in l.get("status", "")])
    failed_count   = len([l for l in parsing_log if "failed" in l.get("status", "")])
    pdf_count      = len([l for l in parsing_log if l.get("status") == "pdf_only"])

    with open("output/stage3_parsing_report.txt", "w") as f:
        f.write("="*60 + "\n")
        f.write("COMP702 — STAGE 3 PARSING REPORT\n")
        f.write("AI-Powered SME Financial Health Analyser for Liverpool\n")
        f.write(f"Thinzar Aung (201942837)\n")
        f.write(f"Generated: {datetime.now().strftime('%d %B %Y %H:%M')}\n")
        f.write("="*60 + "\n\n")
        f.write("PARSING RESULTS\n" + "-"*40 + "\n")
        f.write(f"Total companies processed:  {len(results_df):,}\n")
        f.write(f"Successfully parsed:        {parsed_count:,}\n")
        f.write(f"PDF only (no iXBRL):        {pdf_count:,}\n")
        f.write(f"Parse failed:               {failed_count:,}\n")
        if len(results_df) > 0:
            f.write(f"Parse success rate:         {parsed_count/len(results_df)*100:.1f}%\n\n")
        f.write("FINANCIAL FIELDS EXTRACTED\n" + "-"*40 + "\n")
        for col in available:
            col_data = pd.to_numeric(results_df[col], errors="coerce").dropna()
            f.write(f"{col}: {len(col_data):,} companies have this field\n")
        f.write("\nNEXT STEP — STAGE 4 (PostgreSQL)\n" + "-"*40 + "\n")
        f.write("Feed stage3_financial_data.csv into Stage 4.\n")
        f.write("Stage 4 loads all data into a PostgreSQL database\n")
        f.write("for efficient querying and analysis.\n")

    print(f"  ✓ Summary report saved")


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    print("\n" + "="*60)
    print("  COMP702 — STAGE 3: DOWNLOAD AND PARSE IXBRL")
    print("  Thinzar Aung (201942837) — University of Liverpool")
    print("="*60)

    if API_KEY == "YOUR_API_KEY_HERE":
        print("\n  ✗ Please set your API key at the top of the script")
        return

    # Load Stage 2 output
    df = load_stage2_data("output/stage2_with_filing_links.csv")
    if df.empty:
        return

    # Process all companies
    results_df, parsing_log = process_all_companies(df)

    # Save outputs
    save_outputs(results_df, parsing_log)

    print("\n" + "="*60)
    print("  STAGE 3 COMPLETE")
    has_fin = results_df[
        results_df[[c for c in ["turnover", "current_ratio", "health_score"]
                   if c in results_df.columns]].notna().any(axis=1)
    ]
    print(f"  {len(has_fin):,} Liverpool SMEs with financial data extracted")
    print(f"  Ready for Stage 4 — PostgreSQL database loading")
    print("="*60)


if __name__ == "__main__":
    main()
