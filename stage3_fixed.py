"""
COMP702 — STAGE 3 FIXED: Download and Parse iXBRL Documents
============================================================
Author:  Thinzar Aung (201942837)

FIX: The previous version downloaded the metadata JSON instead
of the actual iXBRL content. This version correctly:
  1. Reads the metadata JSON to find the content URL
  2. Appends /content to get the actual iXBRL document
  3. Sends Accept: application/xhtml+xml header to get iXBRL not PDF

HOW TO RUN:
  python stage3_fixed.py
"""

import os, re, time, json, requests
import pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup

os.makedirs("output/ixbrl_documents", exist_ok=True)

API_KEY      = "Your_API_Key_Here"
DOC_BASE_URL = "https://document-api.company-information.service.gov.uk"
DELAY        = 0.8

try:
    from ixbrlparse import IXBRL
    IXBRLPARSE_OK = True
    print("✓ ixbrlparse available")
except ImportError:
    IXBRLPARSE_OK = False
    print("✗ ixbrlparse not available — using BeautifulSoup only")

# ── XBRL tag map ─────────────────────────────────────────────
XBRL_TAG_MAP = {
    "turnover":            ["turnover", "revenue", "turnovergrossoperatingrevenue"],
    "gross_profit":        ["grossprofitloss", "grossprofit"],
    "operating_profit":    ["operatingprofitloss", "profitlossfromoperations"],
    "profit_before_tax":   ["profitlossbeforetax", "profitlossonordinaryactivitiesbeforetax"],
    "profit_after_tax":    ["profitlossforperiod", "profitloss"],
    "total_assets":        ["assets", "totalassets"],
    "fixed_assets":        ["fixedassets", "totalfixedassets"],
    "current_assets":      ["currentassets"],
    "cash":                ["cashbankonhand", "cashatbankandinhand", "cashandcashequivalents"],
    "debtors":             ["debtors", "tradedebtors", "tradereceivables"],
    "current_liabilities": ["currentliabilities", "creditorsduewithinoneyear"],
    "long_term_liabilities":["noncurrentliabilities", "creditorsdueafteroneyear"],
    "total_liabilities":   ["liabilities", "totalliabilities"],
    "net_assets":          ["netassetsliabilities", "netassets"],
    "equity":              ["equity", "shareholdersequity", "capitalandreserves"],
    "employees":           ["averagenumberemployeesduringperiod"],
}

def clean_value(raw):
    if not raw or not isinstance(raw, str):
        return None
    val = raw.strip().replace(",", "").replace(" ", "").replace("\n", "")
    if not val:
        return None
    negative = val.startswith("(") and val.endswith(")")
    val = val.strip("()")
    try:
        num = float(val)
        return -num if negative else num
    except ValueError:
        return None


# ═══════════════════════════════════════════════════════════════
# FIXED DOWNLOAD FUNCTION
# ═══════════════════════════════════════════════════════════════

def download_ixbrl(doc_link: str, company_number: str) -> tuple:
    """
    FIXED VERSION — correctly fetches iXBRL content.

    Step 1: GET the metadata URL → get JSON with document links
    Step 2: Extract the content URL from the JSON
    Step 3: GET the content URL with Accept: application/xhtml+xml
    """
    # Build metadata URL
    if doc_link.startswith("http"):
        meta_url = doc_link
    else:
        meta_url = f"{DOC_BASE_URL}{doc_link}"

    try:
        # Step 1 — get metadata JSON
        meta_r = requests.get(meta_url, auth=(API_KEY, ""), timeout=15)
        if meta_r.status_code != 200:
            return None, f"metadata_http_{meta_r.status_code}"

        metadata = meta_r.json()

        # Step 2 — find the content URL
        # The metadata JSON contains a "links" section with a "document" URL
        # We append /content to get the actual file
        links = metadata.get("links", {})
        content_url = links.get("document", "")

        if not content_url:
            # Try building it from the self link
            self_link = links.get("self", "")
            if self_link:
                content_url = self_link + "/content"

        if not content_url:
            return None, "no_content_url_in_metadata"

        # Make sure URL is absolute
        if not content_url.startswith("http"):
            content_url = f"{DOC_BASE_URL}{content_url}"

        # Append /content if not already there
        if not content_url.endswith("/content"):
            content_url = content_url + "/content"

        # Check what formats are available
        resources = metadata.get("resources", {})
        has_ixbrl = "application/xhtml+xml" in resources
        has_pdf   = "application/pdf" in resources

        if not has_ixbrl and not has_pdf:
            return None, "no_formats_available"

        # Step 3 — download the actual iXBRL content
        if has_ixbrl:
            content_type = "application/xhtml+xml"
            ext = ".xhtml"
        else:
            content_type = "application/pdf"
            ext = ".pdf"

        doc_r = requests.get(
            content_url,
            auth=(API_KEY, ""),
            headers={"Accept": content_type},
            allow_redirects=True,
            timeout=30
        )

        if doc_r.status_code == 200:
            save_path = f"output/ixbrl_documents/{company_number}_fixed{ext}"
            with open(save_path, "wb") as f:
                f.write(doc_r.content)
            size_kb = len(doc_r.content) / 1024
            return doc_r.content, f"{ext} ({size_kb:.1f}KB)"
        else:
            return None, f"content_http_{doc_r.status_code}"

    except Exception as e:
        return None, f"error: {str(e)[:80]}"


# ═══════════════════════════════════════════════════════════════
# PARSING FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def parse_with_ixbrlparse(content: bytes) -> dict:
    if not IXBRLPARSE_OK:
        return {}
    try:
        from io import StringIO
        text   = content.decode("utf-8", errors="replace")
        parser = IXBRL(StringIO(text))
        facts  = parser.facts
        extracted = {}
        for fact in facts:
            name  = getattr(fact, "name", "").lower()
            value = getattr(fact, "value", None)
            if value is None:
                continue
            for field, keywords in XBRL_TAG_MAP.items():
                if field not in extracted:
                    if any(kw in name for kw in keywords):
                        try:
                            extracted[field] = float(
                                str(value).replace(",", "")
                            )
                        except (ValueError, TypeError):
                            pass
                        break
        return extracted
    except Exception:
        return {}


def parse_with_beautifulsoup(content: bytes) -> dict:
    try:
        text = content.decode("utf-8", errors="replace")
        soup = BeautifulSoup(text, "lxml")

        # Find all ix:nonFraction tags
        tags = soup.find_all(re.compile(r"ix:nonfraction", re.IGNORECASE))

        tag_values = {}
        for tag in tags:
            name = tag.get("name", "").lower()
            # Remove namespace prefix for matching
            name_clean = name.split(":")[-1] if ":" in name else name
            raw  = tag.get_text(strip=True)
            val  = clean_value(raw)
            if name_clean and val is not None and name_clean not in tag_values:
                tag_values[name_clean] = val

        extracted = {}
        for field, keywords in XBRL_TAG_MAP.items():
            for kw in keywords:
                if kw in tag_values:
                    extracted[field] = tag_values[kw]
                    break

        # Get balance sheet date
        ctx = soup.find_all(
            re.compile(r"xbrli:instant|xbrli:enddate", re.IGNORECASE)
        )
        dates = [t.get_text(strip=True) for t in ctx
                 if re.match(r"\d{4}-\d{2}-\d{2}", t.get_text(strip=True))]
        if dates:
            extracted["balance_sheet_date"] = max(dates)

        return extracted
    except Exception:
        return {}


def calculate_ratios(d: dict) -> dict:
    r  = {}
    ca = d.get("current_assets")
    cl = d.get("current_liabilities")
    t  = d.get("turnover")
    gp = d.get("gross_profit")
    pbt= d.get("profit_before_tax")
    ta = d.get("total_assets")
    eq = d.get("equity") or d.get("net_assets")
    tl = d.get("total_liabilities")
    cash=d.get("cash", 0) or 0
    deb= d.get("debtors", 0) or 0

    if ca and cl and cl != 0:
        r["current_ratio"] = round(ca / abs(cl), 3)
    if cl and cl != 0:
        r["quick_ratio"] = round((cash + deb) / abs(cl), 3)
    if t and t != 0:
        if gp  is not None: r["gross_margin_pct"]     = round(gp  / t * 100, 2)
        if pbt is not None: r["net_margin_pct"]        = round(pbt / t * 100, 2)
    if tl and eq and eq != 0:
        r["debt_to_equity"] = round(abs(tl) / abs(eq), 3)
    if t and ta and ta != 0:
        r["asset_turnover"] = round(t / abs(ta), 3)

    score = 50
    cr = r.get("current_ratio", 0)
    gm = r.get("gross_margin_pct", 0)
    de = r.get("debt_to_equity", 0)
    if cr > 2.0:   score += 15
    elif cr > 1.5: score += 10
    elif cr < 1.0: score -= 20
    if gm > 30:    score += 15
    elif gm > 15:  score += 8
    elif gm < 0:   score -= 20
    if de < 0.5:   score += 10
    elif de < 1.5: score += 5
    elif de > 3.0: score -= 10

    r["health_score"]  = max(0, min(100, score))
    r["health_rating"] = (
        "HEALTHY"  if score >= 65 else
        "MODERATE" if score >= 45 else
        "AT RISK"
    )
    return r


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    print("\n" + "="*60)
    print("  COMP702 — STAGE 3 FIXED: DOWNLOAD AND PARSE IXBRL")
    print("  Thinzar Aung (201942837) — University of Liverpool")
    print("="*60)

    if API_KEY == "YOUR_API_KEY_HERE":
        print("\n  ✗ Please set your API key at the top of the script")
        return

    # Load Stage 2 data
    csv_path = "output/stage2_with_filing_links.csv"
    if not os.path.exists(csv_path):
        print(f"  ✗ File not found: {csv_path}")
        return

    df = pd.read_csv(csv_path, dtype=str)
    df = df[df["ixbrl_doc_link"].notna() & (df["ixbrl_doc_link"] != "")]
    print(f"\n  Companies to process: {len(df):,}")
    print(f"  Estimated time: ~{(len(df) * DELAY * 2) / 60:.0f} minutes\n")

    results      = []
    downloaded   = 0
    parsed       = 0
    pdf_only     = 0
    failed       = 0
    parsing_log  = []

    for i, row in df.iterrows():
        company_number = str(row.get("company_number", "")).strip()
        doc_link       = str(row.get("ixbrl_doc_link", "")).strip()
        pos = list(df.index).index(i) + 1

        if pos % 10 == 0 or pos == 1:
            print(f"  [{pos:3}/{len(df)}] "
                  f"Downloaded: {downloaded} | "
                  f"Parsed: {parsed} | "
                  f"PDF only: {pdf_only} | "
                  f"Failed: {failed}")

        result = {
            "company_number":     company_number,
            "company_name":       row.get("company_name", ""),
            "company_status":     row.get("company_status", ""),
            "postcode":           row.get("current_postcode", ""),
            "sic_codes":          row.get("sic_codes", ""),
            "last_accounts_date": row.get("last_accounts_date", ""),
            "last_accounts_type": row.get("last_accounts_type", ""),
            "data_freshness":     row.get("data_freshness_flag", ""),
            "has_insolvency":     row.get("has_insolvency", False),
            "has_charges":        row.get("has_charges", False),
            "download_status":    "not_attempted",
            "parse_method":       "none",
            "fields_extracted":   0,
        }

        # Download
        content, status = download_ixbrl(doc_link, company_number)
        time.sleep(DELAY)

        if content is None:
            result["download_status"] = f"FAILED: {status}"
            failed += 1
            parsing_log.append({"company": company_number, "status": "failed", "reason": status})
            results.append(result)
            continue

        result["download_status"] = f"OK: {status}"
        downloaded += 1

        # Skip PDFs
        if ".pdf" in status:
            result["parse_method"] = "pdf_skipped"
            pdf_only += 1
            parsing_log.append({"company": company_number, "status": "pdf_only"})
            results.append(result)
            continue

        # Parse — ixbrlparse first, BeautifulSoup fallback
        financial_data = parse_with_ixbrlparse(content)
        if financial_data:
            result["parse_method"]    = "ixbrlparse"
            result["fields_extracted"] = len(financial_data)
            parsed += 1
            parsing_log.append({"company": company_number, "status": "parsed_ixbrlparse", "fields": len(financial_data)})
        else:
            financial_data = parse_with_beautifulsoup(content)
            if financial_data:
                result["parse_method"]    = "beautifulsoup"
                result["fields_extracted"] = len(financial_data)
                parsed += 1
                parsing_log.append({"company": company_number, "status": "parsed_bs4", "fields": len(financial_data)})
            else:
                result["parse_method"] = "parse_failed"
                failed += 1
                parsing_log.append({"company": company_number, "status": "parse_failed"})

        if financial_data:
            ratios = calculate_ratios(financial_data)
            result.update(financial_data)
            result.update(ratios)

        results.append(result)

    # Save outputs
    results_df = pd.DataFrame(results)
    results_df.to_csv("output/stage3_financial_data.csv", index=False)

    has_fin = results_df[
        results_df[[c for c in ["turnover","current_ratio","health_score"]
                   if c in results_df.columns]].notna().any(axis=1)
    ] if any(c in results_df.columns for c in ["turnover","current_ratio","health_score"]) \
      else pd.DataFrame()

    has_fin.to_csv("output/stage3_with_financials.csv", index=False)

    with open("output/stage3_parsing_log.json", "w") as f:
        json.dump(parsing_log, f, indent=2)

    print(f"\n  ✓ Complete")
    print(f"  Downloaded:   {downloaded:,}")
    print(f"  Parsed:       {parsed:,}")
    print(f"  PDF only:     {pdf_only:,}")
    print(f"  Failed:       {failed:,}")

    if "health_rating" in results_df.columns:
        print(f"\n  HEALTH RATINGS:")
        for r, c in results_df["health_rating"].value_counts().items():
            print(f"    {r}: {c:,}")

    print("\n" + "="*60)
    print(f"  STAGE 3 COMPLETE — {len(has_fin):,} companies with financial data")
    print("="*60)


if __name__ == "__main__":
    main()
