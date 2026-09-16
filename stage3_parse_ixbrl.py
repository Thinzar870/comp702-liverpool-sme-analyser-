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
API_KEY      = "c02ce0f2-b2be-4be4-a768-d3c98fa12621"
DOC_BASE_URL = "https://document-api.company-information.service.gov.uk"
DELAY        = 0.6   # seconds between API calls

# ── DEMO SAMPLE TOGGLE ──────────────────────────────────────────
# Set to an integer (e.g. 3000) to run a fast, small subset for the
# video presentation, biased toward the OLDEST-incorporated companies
# so the demo actually shows off multi-year filing history rather
# than a mix of companies that only have 1-2 years of accounts.
# Set to None for the real full-scale run against all 88,671
# companies (the actual dissertation dataset).
#
# Because resume logic works at the individual-company level, running
# the demo first and the full run afterwards costs NOTHING extra:
# the full run will see these demo companies already in
# output/stage3_progress.csv and skip them, then continue with
# everyone else. No wasted API calls, no duplicated work.
DEMO_SAMPLE_SIZE = None

# ── DEMO FILING CAP ──────────────────────────────────────────────
# The demo sample is deliberately biased toward the OLDEST companies
# to guarantee multi-year history — but this means it also fetches
# their ENTIRE historical archive (some 100+ year old companies have
# 30+ filings), which is far more than needed for a trend chart and
# is the main reason the demo run is slow.
#
# get_all_accounts_filings() returns filings MOST-RECENT-FIRST (this
# is how the Companies House filing-history API orders results), so
# capping to the first N keeps the N most recent years — plenty for
# a year-on-year trend demo — while skipping the deep archive.
#
# This applies to BOTH the demo run AND the full dissertation run —
# kept active even when DEMO_SAMPLE_SIZE = None, since a small number
# of very old companies can otherwise have 30+ historical filings each,
# making total runtime unpredictable at full scale. Capping to 8 still
# fully supports the R11 multi-year trend requirement.
DEMO_MAX_FILINGS_PER_COMPANY = 8

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
        # core / uk-gaap (your original tags)
        "core:turnover",
        "uk-gaap:turnover",
        "uk-gaap:turnoverrevenue",
        "uk-gaap:turnovergrossoperatingrevenue",
        "bus:turnover",
        "frs-bus:turnover",
        "core:revenue",
        "uk-gaap:revenue",
        # NEW — uk-bus namespace (FRS 102 small company filers)
        "uk-bus:turnover",
        "uk-bus:revenue",
        "uk-bus:turnoverrevenue",
        # NEW — uk-core namespace
        "uk-core:turnover",
        "uk-core:revenue",
        # NEW — dpl namespace (common in accountancy software output)
        "dpl:turnover",
        "dpl:revenue",
        # NEW — plain name variants (some filers omit namespace)
        "turnoverrevenue",
        "turnover",
        "revenue",
        # NEW — Companies House inline XBRL variants
        "ch:turnover",
        "ch:revenue",
        "core:turnovergrossoperatingrevenue",
    ],
 
    "gross_profit": [
        "core:grossprofitloss",
        "uk-gaap:grossprofitloss",
        "uk-gaap:grossprofit",
        # NEW
        "uk-bus:grossprofitloss",
        "uk-core:grossprofitloss",
        "dpl:grossprofitloss",
        "grossprofitloss",
        "grossprofit",
    ],
 
    "operating_profit": [
        "core:operatingprofitloss",
        "uk-gaap:operatingprofitloss",
        "uk-gaap:profitlossfromoperations",
        # NEW
        "uk-bus:operatingprofitloss",
        "uk-core:operatingprofitloss",
        "dpl:operatingprofitloss",
        "operatingprofitloss",
    ],
 
    "profit_before_tax": [
        "core:profitlossbeforetax",
        "uk-gaap:profitlossbeforetax",
        "uk-gaap:profitlossonordinaryactivitiesbeforetax",
        "bus:profitlossbeforetax",
        # NEW
        "uk-bus:profitlossbeforetax",
        "uk-core:profitlossbeforetax",
        "dpl:profitlossbeforetax",
        "profitlossbeforetax",
        "profitlossonordinaryactivitiesbeforetax",
    ],
 
    "profit_after_tax": [
        "core:profitlossforperiod",
        "uk-gaap:profitloss",
        "uk-gaap:profitlossforperiod",
        # NEW
        "uk-bus:profitlossforperiod",
        "uk-core:profitlossforperiod",
        "dpl:profitlossforperiod",
        "profitlossforperiod",
        "profitloss",
    ],
 
    # ── Balance sheet — assets ────────────────────────────────
    "total_assets": [
        "core:assets",
        "uk-gaap:assets",
        "uk-gaap:totalassets",
        # NEW
        "uk-bus:assets",
        "uk-bus:totalassets",
        "uk-core:assets",
        "uk-core:totalassets",
        "dpl:assets",
        "dpl:totalassets",
        "assets",
        "totalassets",
        # NEW — FRS 105 specific tag
        "core:totalassets",
        "uk-gaap:fixedandcurrentassets",
    ],
 
    "fixed_assets": [
        "core:fixedassets",
        "uk-gaap:fixedassets",
        "uk-gaap:totalfixedassets",
        # NEW
        "uk-bus:fixedassets",
        "uk-core:fixedassets",
        "dpl:fixedassets",
        "fixedassets",
        "totalfixedassets",
        "core:noncurrentassets",
        "uk-gaap:noncurrentassets",
    ],
 
    "current_assets": [
        "core:currentassets",
        "uk-gaap:currentassets",
        "bus:currentassets",
        # NEW
        "uk-bus:currentassets",
        "uk-core:currentassets",
        "dpl:currentassets",
        "currentassets",
    ],
 
    "cash": [
        "core:cashbankonhand",
        "uk-gaap:cashatbankandinhand",
        "uk-gaap:cashbankonhand",
        # NEW
        "uk-bus:cashatbankandinhand",
        "uk-bus:cashbankonhand",
        "uk-core:cashatbankandinhand",
        "dpl:cashatbankandinhand",
        "cashatbankandinhand",
        "cashbankonhand",
        # NEW — cash equivalents variants
        "uk-gaap:cashandcashequivalents",
        "core:cashandcashequivalents",
        "uk-bus:cashandcashequivalents",
    ],
 
    "debtors": [
        "core:debtors",
        "uk-gaap:debtors",
        "uk-gaap:tradedebtors",
        # NEW
        "uk-bus:debtors",
        "uk-bus:tradedebtors",
        "uk-core:debtors",
        "dpl:debtors",
        "debtors",
        "tradedebtors",
        "uk-gaap:tradereceivables",
        "core:tradereceivables",
    ],
 
    # ── Balance sheet — liabilities ───────────────────────────
    "current_liabilities": [
        "core:currentliabilities",
        "uk-gaap:currentliabilities",
        "uk-gaap:creditorsduewithinoneyear",
        "bus:currentliabilities",
        # NEW
        "uk-bus:currentliabilities",
        "uk-bus:creditorsduewithinoneyear",
        "uk-core:currentliabilities",
        "dpl:currentliabilities",
        "currentliabilities",
        "creditorsduewithinoneyear",
        # NEW — FRS 105 specific
        "core:creditorsduewithinoneyear",
    ],
 
    "long_term_liabilities": [
        "core:noncurrentliabilities",
        "uk-gaap:creditorsdueafteroneyear",
        "uk-gaap:noncurrentliabilities",
        # NEW
        "uk-bus:noncurrentliabilities",
        "uk-bus:creditorsdueafteroneyear",
        "uk-core:noncurrentliabilities",
        "dpl:noncurrentliabilities",
        "noncurrentliabilities",
        "creditorsdueafteroneyear",
    ],
 
    "total_liabilities": [
        "core:liabilities",
        "uk-gaap:liabilities",
        "uk-gaap:totalliabilities",
        # NEW
        "uk-bus:liabilities",
        "uk-bus:totalliabilities",
        "uk-core:liabilities",
        "dpl:liabilities",
        "liabilities",
        "totalliabilities",
    ],
 
    # ── Equity ────────────────────────────────────────────────
    "net_assets": [
        "core:netassetsliabilities",
        "uk-gaap:netassets",
        "uk-gaap:netassetsliabilities",
        "bus:netassetsliabilities",
        # NEW
        "uk-bus:netassetsliabilities",
        "uk-bus:netassets",
        "uk-core:netassetsliabilities",
        "dpl:netassetsliabilities",
        "netassetsliabilities",
        "netassets",
    ],
 
    "equity": [
        "core:equity",
        "uk-gaap:equity",
        "uk-gaap:shareholdersequity",
        "uk-gaap:capitalandreserves",
        # NEW
        "uk-bus:equity",
        "uk-bus:shareholdersequity",
        "uk-bus:capitalandreserves",
        "uk-core:equity",
        "dpl:equity",
        "equity",
        "shareholdersequity",
        "capitalandreserves",
        # NEW — retained earnings as equity proxy
        "uk-gaap:retainedearnings",
        "core:retainedearnings",
        "uk-bus:retainedearnings",
    ],
 
    # ── Other ─────────────────────────────────────────────────
    "employees": [
        "core:averagenumberemployeesduringperiod",
        "uk-gaap:averagenumberemployeesduringperiod",
        "bus:averagenumberemployeesduringperiod",
        # NEW
        "uk-bus:averagenumberemployeesduringperiod",
        "uk-core:averagenumberemployeesduringperiod",
        "dpl:averagenumberemployeesduringperiod",
        "averagenumberemployeesduringperiod",
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

    # ── DEMO SAMPLE: bias toward oldest-incorporated companies ──
    # Older companies are far more likely to have several years of
    # historical accounts filings, which is what actually makes a
    # "full multi-year history" demo look impressive. A random 3,000
    # would mix in recently-incorporated companies with only 1 filing.
    if DEMO_SAMPLE_SIZE is not None:
        date_col = None
        for candidate in ["incorporation_date", "date_of_creation"]:
            if candidate in df.columns:
                date_col = candidate
                break

        if date_col:
            df["_inc_date_parsed"] = pd.to_datetime(df[date_col], errors="coerce")
            before = len(df)
            df = df.dropna(subset=["_inc_date_parsed"])
            dropped = before - len(df)
            if dropped:
                print(f"  ⚠ Dropped {dropped:,} companies with missing/unparseable {date_col}")
            df = df.sort_values("_inc_date_parsed", ascending=True)
            oldest_date = df["_inc_date_parsed"].iloc[0].strftime("%Y-%m-%d") if len(df) else "n/a"
            df = df.drop(columns=["_inc_date_parsed"])
        else:
            print(f"  ⚠ No incorporation date column found — cannot bias toward older "
                  f"companies. Using file order instead (demo will show a mix of filing "
                  f"history depths).")
            oldest_date = "n/a"

        df = df.head(DEMO_SAMPLE_SIZE).reset_index(drop=True)
        print(f"\n  ✓ DEMO MODE — sampled {len(df):,} companies "
              f"(oldest incorporated: {oldest_date})")
        print(f"    This gives the richest multi-year filing history for the video demo.")
        print(f"    Set DEMO_SAMPLE_SIZE = None and rerun for the real full dissertation")
        print(f"    dataset — resume logic will skip these {len(df):,} and continue with")
        print(f"    the remaining companies automatically.\n")
    # ──────────────────────────────────────────────────────────────

    return df.reset_index(drop=True)


# ═══════════════════════════════════════════════════════════════
# STEP 2 — DOWNLOAD IXBRL DOCUMENT
# ═══════════════════════════════════════════════════════════════

def download_ixbrl_document(doc_link: str, company_number: str) -> tuple:
    if doc_link.startswith("http"):
        metadata_url = doc_link
    else:
        metadata_url = f"{DOC_BASE_URL}{doc_link}"

    try:
        # Step 1 — get metadata
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

        # Step 2 — pick format and get the correct document URL
        if "application/xhtml+xml" in resources:
            content_type = "application/xhtml+xml"
            ext = ".xhtml"
            
        elif "application/pdf" in resources:
            content_type = "application/pdf"
            ext = ".pdf"
            
        else:
            return None, f"no_usable_format: {available}"

        doc_url = metadata.get("links", {}).get("document")
        if not doc_url:
            return None, "no_document_link_in_metadata"

        # Handle relative URLs
        if not doc_url.startswith("http"):
            doc_url = f"{DOC_BASE_URL}{doc_url}"

        # Step 3 — download the actual document using doc_url
        doc_r = requests.get(
            doc_url,
            auth=(API_KEY, ""),
            headers={"Accept": content_type},
            allow_redirects=True,
            timeout=30
        )

        if doc_r.status_code == 200:
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
    Health score only uses ratios that were actually calculable —
    missing ratios are excluded from scoring rather than defaulted to 0,
    and companies with too little data are flagged INSUFFICIENT DATA
    instead of being scored at all.
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
    # Only score on ratios that were ACTUALLY calculated.
    # Missing ratios are skipped entirely, not defaulted to 0.
    score = 50
    fields_used = 0

    if "current_ratio" in ratios:
        cr = ratios["current_ratio"]
        fields_used += 1
        if cr > 2.0:   score += 15
        elif cr > 1.5: score += 10
        elif cr < 1.0: score -= 20

    if "gross_margin_pct" in ratios:
        gm = ratios["gross_margin_pct"]
        fields_used += 1
        if gm > 30:    score += 15
        elif gm > 15:  score += 8
        elif gm < 0:   score -= 20

    if "debt_to_equity" in ratios:
        de = ratios["debt_to_equity"]
        fields_used += 1
        if de < 0.5:   score += 10
        elif de < 1.5: score += 5
        elif de > 3.0: score -= 10

    ratios["health_score_fields_used"] = fields_used

    # Require at least 2 of the 3 core scoring ratios to give a real rating.
    # Companies with 0-1 usable fields don't have enough data for a fair score.
    if fields_used < 2:
        ratios["health_score"]  = None
        ratios["health_rating"] = "INSUFFICIENT DATA"
    else:
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
def get_all_accounts_filings(company_number: str) -> tuple:
    """
    Calls the filing-history API fresh and returns ALL accounts filings
    for this company (not just the latest), each with its filing date
    and document_metadata link. This enables year-on-year trend analysis
    (dissertation requirement R11) by giving Stage 3 every historical
    filing to download and parse, not just the most recent one.

    Companies House returns up to 100 items per page; most SMEs have
    far fewer accounts filings than that, so one page is normally enough.
    """
    filing_url = f"https://api.company-information.service.gov.uk/company/{company_number}/filing-history"
    try:
        r = requests.get(
            filing_url,
            auth=(API_KEY, ""),
            params={"category": "accounts", "items_per_page": 100},
            timeout=15,
        )
    except requests.RequestException as e:
        return [], f"filing_history_error: {str(e)[:50]}"

    if r.status_code != 200:
        return [], f"filing_history_http_{r.status_code}"

    items = [i for i in r.json().get("items", []) if i.get("category") == "accounts"]
    if not items:
        return [], "no_accounts_filings"

    filings = []
    for item in items:
        doc_link = item.get("links", {}).get("document_metadata")
        if doc_link:
            filings.append({
                "filing_date": item.get("date"),
                "filing_description": item.get("description"),
                "document_metadata_link": doc_link,
            })

    if not filings:
        return [], "no_document_metadata_links"

    # Sort newest first, for consistent ordering
    filings.sort(key=lambda f: f["filing_date"], reverse=True)
    return filings, None

def process_all_companies(df: pd.DataFrame) -> pd.DataFrame:
    """
    RESUME SUPPORT: if output/stage3_progress.csv already exists from
    a previous (interrupted) run, already-processed companies are
    loaded and skipped, so restarting after a crash or disconnect
    continues from where it left off instead of starting over.
    Resume works at the whole-company level: a company only counts
    as "done" once every one of its historical filings has been
    processed, since each company can produce several output rows
    (one per filing year).
    """
    print("\n" + "="*60)
    print("STEP 2 — DOWNLOADING AND PARSING IXBRL DOCUMENTS")
    print("="*60)
    print(f"\n  Companies to process: {len(df):,}")
    print(f"  Estimated time: ~{(len(df) * DELAY * 2) / 60:.0f} minutes\n")

    progress_path = "output/stage3_progress.csv"
    results       = []
    parsing_log   = []
    already_done  = set()
    downloaded_ok = 0
    parsed_ok     = 0
    parse_failed  = 0
    pdf_fallback  = 0
    errors        = 0

    # ── Resume from checkpoint if it exists ─────────────────────
    if os.path.exists(progress_path):
        prior_df = pd.read_csv(progress_path, dtype={"company_number": str})
        results = prior_df.to_dict("records")
        already_done = set(prior_df["company_number"].str.zfill(8))
        print(f"  ↻ Found existing progress file — resuming.")
        print(f"  Already processed: {len(already_done):,} companies — these will be skipped.\n")

        # Recompute running counters from the resumed data so the
        # progress display stays accurate rather than resetting to 0.
        downloaded_ok = sum(1 for r in results if str(r.get("download_status", "")).startswith("OK"))
        parsed_ok     = sum(1 for r in results if r.get("parse_method") in ("ixbrlparse", "beautifulsoup"))
        parse_failed  = sum(1 for r in results if r.get("parse_method") == "parse_failed")
        pdf_fallback  = sum(1 for r in results if r.get("parse_method") == "pdf_skipped")
        errors        = sum(1 for r in results if str(r.get("download_status", "")).startswith("FAILED"))
    # ─────────────────────────────────────────────────────────────

    companies_done_this_run = 0

    for i, row in df.iterrows():
        company_number = str(row.get("company_number", "")).strip().zfill(8)
        company_name    = str(row.get("company_name", "")).strip()

        if not company_number:
            continue

        # ── Skip companies already fully processed in a previous run ──
        if company_number in already_done:
            continue
        # ────────────────────────────────────────────────────────────

        # ── Get ALL historical accounts filings for this company ──
        filings, link_err = get_all_accounts_filings(company_number)
        time.sleep(DELAY)

        # Cap to the most recent N filings in demo mode — the API
        # returns filings most-recent-first, so this keeps recent
        # years (enough for a trend chart) and skips deep archives
        # from very old companies. No effect on the full run.
        if DEMO_MAX_FILINGS_PER_COMPANY is not None and filings:
            filings = filings[:DEMO_MAX_FILINGS_PER_COMPANY]

        pos = list(df.index).index(i) + 1
        if pos % 10 == 0 or pos == 1:
            print(f"  [{pos:3}/{len(df)}] "
                  f"Downloaded: {downloaded_ok} | "
                  f"Parsed: {parsed_ok} | "
                  f"Failed: {parse_failed} | "
                  f"Errors: {errors}")

        if not filings:
            parsing_log.append({
                "company": company_number,
                "status": "download_failed",
                "reason": link_err or "no_filings"
            })
            results.append({"company_number": company_number, "company_name": company_name,
                             "download_status": "failed", "reason": link_err})

            already_done.add(company_number)
            companies_done_this_run += 1
            if companies_done_this_run % 20 == 0:
                pd.DataFrame(results).to_csv(progress_path, index=False)
            continue

        # ── Loop through EVERY historical filing for this company ──
        for filing in filings:
            filing_date = filing.get("filing_date", "")
            filing_year = filing_date[:4] if filing_date else "unknown"

            result = {
                "company_number":      company_number,
                "company_name":        company_name,
                "company_status":      row.get("company_status", ""),
                "postcode":            row.get("current_postcode", ""),
                "sic_codes":           row.get("sic_codes", ""),
                "filing_date":         filing_date,
                "filing_year":         filing_year,
                "filing_description":  filing.get("filing_description", ""),
                "last_accounts_type":  row.get("last_accounts_type", ""),
                "data_freshness":      row.get("data_freshness_flag", ""),
                "has_insolvency":      row.get("has_insolvency", False),
                "has_charges":         row.get("has_charges", False),
                "download_status":    "not_attempted",
                "parse_method":       "none",
                "fields_extracted":   0,
            }

            content, status = download_ixbrl_document(filing["document_metadata_link"], company_number)
            time.sleep(DELAY)

            if content is None:
                result["download_status"] = f"FAILED: {status}"
                errors += 1
                parsing_log.append({
                    "company": company_number,
                    "filing_year": filing_year,
                    "status": "download_failed",
                    "reason": status
                })
                results.append(result)
                continue

            result["download_status"] = f"OK: {status}"
            downloaded_ok += 1

            if ".pdf" in str(status):
                result["parse_method"] = "pdf_skipped"
                pdf_fallback += 1
                parsing_log.append({
                    "company": company_number,
                    "filing_year": filing_year,
                    "status": "pdf_only",
                    "reason": "Only PDF available — no iXBRL"
                })
                results.append(result)
                continue

            financial_data = parse_with_ixbrlparse(content)

            if financial_data:
                result["parse_method"]     = "ixbrlparse"
                result["fields_extracted"] = len(financial_data)
                parsed_ok += 1
                parsing_log.append({
                    "company": company_number,
                    "filing_year": filing_year,
                    "status": "parsed_ixbrlparse",
                    "fields": len(financial_data)
                })
            else:
                financial_data = parse_with_beautifulsoup(content)
                if financial_data:
                    result["parse_method"]     = "beautifulsoup"
                    result["fields_extracted"] = len(financial_data)
                    parsed_ok += 1
                    parsing_log.append({
                        "company": company_number,
                        "filing_year": filing_year,
                        "status": "parsed_beautifulsoup",
                        "fields": len(financial_data)
                    })
                else:
                    result["parse_method"] = "parse_failed"
                    parse_failed += 1
                    parsing_log.append({
                        "company": company_number,
                        "filing_year": filing_year,
                        "status": "parse_failed",
                        "reason": "No financial data extracted by either method"
                    })

            if financial_data:
                ratios = calculate_ratios(financial_data)
                result.update(financial_data)
                result.update(ratios)

            results.append(result)

        # ── Whole company finished (all its filings processed) ──
        already_done.add(company_number)
        companies_done_this_run += 1
        if companies_done_this_run % 20 == 0:
            pd.DataFrame(results).to_csv(progress_path, index=False)
            print(f"  ↻ Checkpoint saved: {len(already_done):,} companies done so far")
        # ─────────────────────────────────────────────────────────

    # ── Final save so the last partial batch isn't lost ──────────
    pd.DataFrame(results).to_csv(progress_path, index=False)
    # ───────────────────────────────────────────────────────────

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
