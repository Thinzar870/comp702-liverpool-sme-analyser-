"""
COMP702 — STAGE 4: Load Financial Data into SQLite Database
============================================================
Author:  Thinzar Aung (201942837)
Project: AI-Powered SME Financial Health Analyser for Liverpool City Region
Stage:   4 of 7 — Database loading

WHAT THIS SCRIPT DOES:
  Takes all output from Stages 1, 2 and 3 and loads everything
  into a structured SQLite database with proper relational tables.

WHY SQLITE NOW, POSTGRESQL LATER:
  SQLite requires zero installation — built into Python.
  It is ideal for prototyping and proposal stage demonstration.
  The schema is designed to be identical to PostgreSQL so migration
  is straightforward for the full dissertation phase.
  Using SQLite for prototyping → PostgreSQL for production is
  standard practice in professional data engineering.

DATABASE SCHEMA:
  companies        — company profile and metadata (from Stage 1 + 2)
  financial_data   — extracted iXBRL financial figures (from Stage 3)
  financial_ratios — calculated ratios and health scores (from Stage 3)
  pipeline_log     — processing log for methodology documentation

HOW TO RUN:
  python stage4_database.py

OUTPUT:
  output/liverpool_sme_analyser.db  — the SQLite database
  output/stage4_summary_report.txt  — database contents summary
"""

import os
import sqlite3
import pandas as pd
from datetime import datetime

os.makedirs("output", exist_ok=True)

DB_PATH = "output/liverpool_sme_analyser.db"


# ═══════════════════════════════════════════════════════════════
# STEP 1 — CREATE DATABASE AND TABLES
# ═══════════════════════════════════════════════════════════════

def create_database(db_path: str) -> sqlite3.Connection:
    """
    Creates the SQLite database and all tables.
    Schema is designed to match PostgreSQL for easy migration.
    """
    print("\n" + "="*60)
    print("STEP 1 — CREATING DATABASE AND TABLES")
    print("="*60)

    # Remove existing database for clean run
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"\n  Removed existing database")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # ── Table 1: companies ────────────────────────────────────
    # Core company profile — one row per company
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            company_number      TEXT PRIMARY KEY,
            company_name        TEXT,
            company_type        TEXT,
            company_status      TEXT,
            postcode            TEXT,
            postcode_district   TEXT,
            address_line1       TEXT,
            post_town           TEXT,
            sic_code_1          TEXT,
            sic_code_2          TEXT,
            incorporation_date  TEXT,
            company_age_years   REAL,
            has_insolvency      INTEGER DEFAULT 0,
            has_charges         INTEGER DEFAULT 0,
            last_accounts_date  TEXT,
            last_accounts_type  TEXT,
            data_freshness_flag TEXT,
            data_freshness_months REAL,
            api_verified        INTEGER DEFAULT 0,
            pipeline_stage      TEXT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Table 2: financial_data ───────────────────────────────
    # Raw extracted financial figures — one row per company filing
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS financial_data (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            company_number      TEXT NOT NULL,
            balance_sheet_date  TEXT,
            filing_type         TEXT,
            parse_method        TEXT,
            fields_extracted    INTEGER DEFAULT 0,

            -- Income statement
            turnover            REAL,
            gross_profit        REAL,
            operating_profit    REAL,
            profit_before_tax   REAL,
            profit_after_tax    REAL,

            -- Balance sheet assets
            total_assets        REAL,
            fixed_assets        REAL,
            current_assets      REAL,
            cash                REAL,
            debtors             REAL,

            -- Balance sheet liabilities
            current_liabilities  REAL,
            long_term_liabilities REAL,
            total_liabilities    REAL,

            -- Equity
            net_assets          REAL,
            equity              REAL,

            -- Other
            employees           REAL,

            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_number) REFERENCES companies(company_number)
        )
    """)

    # ── Table 3: financial_ratios ─────────────────────────────
    # Calculated ratios — one row per company
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS financial_ratios (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            company_number      TEXT NOT NULL,
            balance_sheet_date  TEXT,

            -- Liquidity
            current_ratio       REAL,
            quick_ratio         REAL,

            -- Profitability
            gross_margin_pct    REAL,
            operating_margin_pct REAL,
            net_margin_pct      REAL,

            -- Leverage
            debt_to_equity      REAL,

            -- Efficiency
            asset_turnover      REAL,

            -- Health score
            health_score        REAL,
            health_rating       TEXT,

            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_number) REFERENCES companies(company_number)
        )
    """)

    # ── Table 4: pipeline_log ─────────────────────────────────
    # Processing log for methodology documentation
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            stage           TEXT,
            action          TEXT,
            records_count   INTEGER,
            notes           TEXT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    print(f"\n  ✓ Database created: {db_path}")
    print(f"  ✓ Tables created: companies, financial_data, financial_ratios, pipeline_log")
    return conn


# ═══════════════════════════════════════════════════════════════
# STEP 2 — LOAD COMPANIES TABLE (Stage 1 + Stage 2 data)
# ═══════════════════════════════════════════════════════════════

def load_companies(conn: sqlite3.Connection) -> int:
    """
    Loads company profile data from Stage 1 and Stage 2 outputs
    into the companies table.

    Stage 1 gives us: postcode, SIC code, company type, status
    Stage 2 enriches with: API-verified status, filing dates,
                           insolvency flags, data freshness
    """
    print("\n" + "="*60)
    print("STEP 2 — LOADING COMPANIES TABLE")
    print("="*60)

    cursor = conn.cursor()
    loaded = 0

    # ── Load Stage 2 verified companies (richest data) ────────
    stage2_path = "output/stage2_verified_companies.csv"
    if os.path.exists(stage2_path):
        df2 = pd.read_csv(stage2_path, dtype=str)
        print(f"\n  Stage 2 data: {len(df2):,} companies")

        for _, row in df2.iterrows():
            company_number = str(row.get("company_number", "")).strip()
            if not company_number:
                continue

            # Extract postcode district (e.g. "L1" from "L14DS")
            postcode = str(row.get("current_postcode", "")).strip()
            postcode_district = postcode.split(" ")[0] if " " in postcode \
                else postcode[:3] if len(postcode) >= 3 else postcode

            # Calculate company age from creation date
            age_years = None
            creation_date = str(row.get("date_of_creation", "")).strip()
            if creation_date and creation_date != "nan":
                try:
                    created = datetime.strptime(creation_date, "%Y-%m-%d")
                    age_years = round(
                        (datetime.now() - created).days / 365.25, 1
                    )
                except ValueError:
                    pass

            cursor.execute("""
                INSERT OR REPLACE INTO companies (
                    company_number, company_name, company_type,
                    company_status, postcode, postcode_district,
                    sic_code_1, company_age_years,
                    has_insolvency, has_charges,
                    last_accounts_date, last_accounts_type,
                    data_freshness_flag, data_freshness_months,
                    api_verified, pipeline_stage
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                company_number,
                str(row.get("company_name", "")).strip(),
                str(row.get("company_type", "")).strip(),
                str(row.get("company_status", "")).strip(),
                postcode,
                postcode_district,
                str(row.get("sic_codes", "")).split("|")[0].strip(),
                age_years,
                1 if str(row.get("has_insolvency", "")).lower()
                    in ["true", "1", "yes"] else 0,
                1 if str(row.get("has_charges", "")).lower()
                    in ["true", "1", "yes"] else 0,
                str(row.get("last_accounts_date", "")).strip(),
                str(row.get("last_accounts_type", "")).strip(),
                str(row.get("data_freshness_flag", "")).strip(),
                _safe_float(row.get("data_freshness_months")),
                1 if str(row.get("api_verified", "")).lower()
                    in ["true", "1", "yes"] else 0,
                "stage2"
            ))
            loaded += 1

    # ── Also load Stage 1 companies not in Stage 2 ───────────
    stage1_path = "output/stage1_liverpool_smes.csv"
    if os.path.exists(stage1_path):
        df1 = pd.read_csv(stage1_path, dtype=str)
        print(f"  Stage 1 data: {len(df1):,} companies")

        # Get existing company numbers
        existing = {
            row[0] for row in
            cursor.execute("SELECT company_number FROM companies").fetchall()
        }

        extra = 0
        for _, row in df1.iterrows():
            uri = str(row.get("companies_house_uri", "")).strip()
            company_number = uri.split("/")[-1] if uri else ""
            if not company_number or company_number in existing:
                continue

            postcode = str(row.get("postcode", "")).strip()
            postcode_district = postcode.split(" ")[0] \
                if " " in postcode else postcode[:3]

            cursor.execute("""
                INSERT OR IGNORE INTO companies (
                    company_number, company_name, company_type,
                    company_status, postcode, postcode_district,
                    address_line1, post_town,
                    sic_code_1, sic_code_2,
                    incorporation_date, last_accounts_date,
                    last_accounts_type, pipeline_stage
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                company_number,
                str(row.get("company_name", "")).strip(),
                str(row.get("company_type", "")).strip(),
                str(row.get("company_status", "")).strip(),
                postcode, postcode_district,
                str(row.get("address_line1", "")).strip(),
                str(row.get("post_town", "")).strip(),
                str(row.get("sic_code_1", "")).strip(),
                str(row.get("sic_code_2", "")).strip(),
                str(row.get("incorporation_date", "")).strip(),
                str(row.get("last_accounts_date", "")).strip(),
                str(row.get("accounts_type", "")).strip(),
                "stage1"
            ))
            extra += 1

        print(f"  Added {extra:,} additional companies from Stage 1")

    conn.commit()
    total = cursor.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    print(f"\n  ✓ Companies table loaded: {total:,} total companies")

    cursor.execute("""
        INSERT INTO pipeline_log (stage, action, records_count, notes)
        VALUES (?, ?, ?, ?)
    """, ("Stage 1+2", "load_companies", total,
          "Company profiles from Stage 1 CSV and Stage 2 API verification"))
    conn.commit()
    return total


# ═══════════════════════════════════════════════════════════════
# STEP 3 — LOAD FINANCIAL DATA (Stage 3)
# ═══════════════════════════════════════════════════════════════

def load_financial_data(conn: sqlite3.Connection) -> tuple:
    """
    Loads extracted iXBRL financial figures from Stage 3 into
    the financial_data and financial_ratios tables.
    """
    print("\n" + "="*60)
    print("STEP 3 — LOADING FINANCIAL DATA")
    print("="*60)

    cursor = conn.cursor()

    stage3_path = "output/stage3_financial_data.csv"
    if not os.path.exists(stage3_path):
        print(f"  ✗ File not found: {stage3_path}")
        return 0, 0

    df = pd.read_csv(stage3_path, dtype=str)
    print(f"\n  Stage 3 data: {len(df):,} rows")

    financial_loaded = 0
    ratios_loaded    = 0

    for _, row in df.iterrows():
        company_number = str(row.get("company_number", "")).strip()
        if not company_number:
            continue

        parse_method = str(row.get("parse_method", "")).strip()

        # Only load rows that were actually parsed
        if parse_method in ["none", "pdf_skipped",
                            "parse_failed", "not_attempted"]:
            continue

        # ── Insert financial data ─────────────────────────────
        cursor.execute("""
            INSERT INTO financial_data (
                company_number, balance_sheet_date, parse_method,
                fields_extracted,
                turnover, gross_profit, operating_profit,
                profit_before_tax, profit_after_tax,
                total_assets, fixed_assets, current_assets,
                cash, debtors,
                current_liabilities, long_term_liabilities,
                total_liabilities, net_assets, equity, employees
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            company_number,
            str(row.get("balance_sheet_date", "")).strip(),
            parse_method,
            _safe_int(row.get("fields_extracted")),
            _safe_float(row.get("turnover")),
            _safe_float(row.get("gross_profit")),
            _safe_float(row.get("operating_profit")),
            _safe_float(row.get("profit_before_tax")),
            _safe_float(row.get("profit_after_tax")),
            _safe_float(row.get("total_assets")),
            _safe_float(row.get("fixed_assets")),
            _safe_float(row.get("current_assets")),
            _safe_float(row.get("cash")),
            _safe_float(row.get("debtors")),
            _safe_float(row.get("current_liabilities")),
            _safe_float(row.get("long_term_liabilities")),
            _safe_float(row.get("total_liabilities")),
            _safe_float(row.get("net_assets")),
            _safe_float(row.get("equity")),
            _safe_float(row.get("employees")),
        ))
        financial_loaded += 1

        # ── Insert ratios ─────────────────────────────────────
        has_ratios = any(
            _safe_float(row.get(c)) is not None
            for c in ["current_ratio", "gross_margin_pct",
                      "health_score"]
        )
        if has_ratios:
            cursor.execute("""
                INSERT INTO financial_ratios (
                    company_number, balance_sheet_date,
                    current_ratio, quick_ratio,
                    gross_margin_pct, operating_margin_pct,
                    net_margin_pct, debt_to_equity,
                    asset_turnover, health_score, health_rating
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                company_number,
                str(row.get("balance_sheet_date", "")).strip(),
                _safe_float(row.get("current_ratio")),
                _safe_float(row.get("quick_ratio")),
                _safe_float(row.get("gross_margin_pct")),
                _safe_float(row.get("operating_margin_pct")),
                _safe_float(row.get("net_margin_pct")),
                _safe_float(row.get("debt_to_equity")),
                _safe_float(row.get("asset_turnover")),
                _safe_float(row.get("health_score")),
                str(row.get("health_rating", "")).strip(),
            ))
            ratios_loaded += 1

    conn.commit()

    print(f"\n  ✓ Financial data records loaded: {financial_loaded:,}")
    print(f"  ✓ Financial ratio records loaded: {ratios_loaded:,}")

    cursor.execute("""
        INSERT INTO pipeline_log (stage, action, records_count, notes)
        VALUES (?, ?, ?, ?)
    """, ("Stage 3", "load_financial_data", financial_loaded,
          "iXBRL extracted financial figures and calculated ratios"))
    conn.commit()
    return financial_loaded, ratios_loaded


# ═══════════════════════════════════════════════════════════════
# STEP 4 — RUN EXAMPLE QUERIES
# ═══════════════════════════════════════════════════════════════

def run_example_queries(conn: sqlite3.Connection):
    """
    Runs example SQL queries to demonstrate the database works
    and to produce initial findings for the proposal.

    These queries show what the final tool will produce —
    financial health insights about Liverpool SMEs.
    """
    print("\n" + "="*60)
    print("STEP 4 — EXAMPLE DATABASE QUERIES")
    print("="*60)
    cursor = conn.cursor()

    # Query 1 — total database contents
    print("\n  QUERY 1: Database contents")
    print("  " + "-"*45)
    for table in ["companies", "financial_data", "financial_ratios"]:
        count = cursor.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]
        print(f"  {table}: {count:,} records")

    # Query 2 — companies by postcode district
    print("\n  QUERY 2: Top 10 Liverpool postcode districts by company count")
    print("  " + "-"*45)
    results = cursor.execute("""
        SELECT postcode_district, COUNT(*) as company_count
        FROM companies
        WHERE postcode_district IS NOT NULL
          AND postcode_district != ''
          AND postcode_district != 'nan'
        GROUP BY postcode_district
        ORDER BY company_count DESC
        LIMIT 10
    """).fetchall()
    for district, count in results:
        print(f"  {district:10} {count:,} companies")

    # Query 3 — financial health distribution
    print("\n  QUERY 3: Financial health rating distribution")
    print("  " + "-"*45)
    results = cursor.execute("""
        SELECT health_rating, COUNT(*) as count
        FROM financial_ratios
        WHERE health_rating IS NOT NULL AND health_rating != ''
        GROUP BY health_rating
        ORDER BY count DESC
    """).fetchall()
    if results:
        for rating, count in results:
            print(f"  {rating:15} {count:,} companies")
    else:
        print("  No health ratings yet — will improve in Stage 6")

    # Query 4 — companies with turnover data
    print("\n  QUERY 4: Turnover statistics for Liverpool SMEs")
    print("  " + "-"*45)
    results = cursor.execute("""
        SELECT
            COUNT(*) as companies_with_turnover,
            ROUND(AVG(turnover), 0) as avg_turnover,
            ROUND(MIN(turnover), 0) as min_turnover,
            ROUND(MAX(turnover), 0) as max_turnover
        FROM financial_data
        WHERE turnover IS NOT NULL AND turnover > 0
    """).fetchone()
    if results and results[0]:
        print(f"  Companies with turnover:  {results[0]:,}")
        print(f"  Average turnover:         £{results[1]:>12,.0f}")
        print(f"  Minimum turnover:         £{results[2]:>12,.0f}")
        print(f"  Maximum turnover:         £{results[3]:>12,.0f}")
    else:
        print("  No turnover data yet")

    # Query 5 — data freshness breakdown
    print("\n  QUERY 5: Data freshness of Liverpool SME filings")
    print("  " + "-"*45)
    results = cursor.execute("""
        SELECT data_freshness_flag, COUNT(*) as count
        FROM companies
        WHERE data_freshness_flag IS NOT NULL
          AND data_freshness_flag != ''
          AND data_freshness_flag != 'nan'
        GROUP BY data_freshness_flag
        ORDER BY count DESC
    """).fetchall()
    for flag, count in results:
        print(f"  {flag:35} {count:,}")

    # Query 6 — accounts type breakdown
    print("\n  QUERY 6: Accounts type breakdown")
    print("  " + "-"*45)
    results = cursor.execute("""
        SELECT last_accounts_type, COUNT(*) as count
        FROM companies
        WHERE last_accounts_type IS NOT NULL
          AND last_accounts_type != ''
          AND last_accounts_type != 'nan'
        GROUP BY last_accounts_type
        ORDER BY count DESC
        LIMIT 8
    """).fetchall()
    for acct_type, count in results:
        print(f"  {str(acct_type):30} {count:,}")

    # Query 7 — example of what the tool will show for one company
    print("\n  QUERY 7: Example company financial profile")
    print("  " + "-"*45)
    result = cursor.execute("""
        SELECT
            c.company_name,
            c.company_number,
            c.postcode,
            c.sic_code_1,
            c.last_accounts_date,
            c.data_freshness_flag,
            f.turnover,
            f.gross_profit,
            f.profit_before_tax,
            f.current_assets,
            f.current_liabilities,
            f.net_assets,
            r.current_ratio,
            r.gross_margin_pct,
            r.health_score,
            r.health_rating
        FROM companies c
        JOIN financial_data f ON c.company_number = f.company_number
        JOIN financial_ratios r ON c.company_number = r.company_number
        WHERE f.turnover IS NOT NULL AND f.turnover > 0
        LIMIT 1
    """).fetchone()

    if result:
        labels = [
            "Company name", "Company number", "Postcode", "SIC code",
            "Last accounts", "Data freshness",
            "Turnover", "Gross profit", "Profit before tax",
            "Current assets", "Current liabilities", "Net assets",
            "Current ratio", "Gross margin %",
            "Health score", "Health rating"
        ]
        for label, value in zip(labels, result):
            if isinstance(value, float) and abs(value) > 100:
                print(f"  {label:25} £{value:>15,.0f}")
            else:
                print(f"  {label:25} {str(value):>15}")
    else:
        print("  No complete company profile available yet")


# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def _safe_float(val) -> float:
    if val is None:
        return None
    try:
        s = str(val).strip()
        if s in ("", "nan", "None", "NaN"):
            return None
        return float(s)
    except (ValueError, TypeError):
        return None

def _safe_int(val) -> int:
    f = _safe_float(val)
    return int(f) if f is not None else None


# ═══════════════════════════════════════════════════════════════
# STEP 5 — SAVE SUMMARY REPORT
# ═══════════════════════════════════════════════════════════════

def save_report(conn: sqlite3.Connection):
    cursor = conn.cursor()
    companies_count = cursor.execute(
        "SELECT COUNT(*) FROM companies"
    ).fetchone()[0]
    financial_count = cursor.execute(
        "SELECT COUNT(*) FROM financial_data"
    ).fetchone()[0]
    ratios_count = cursor.execute(
        "SELECT COUNT(*) FROM financial_ratios"
    ).fetchone()[0]
    turnover_count = cursor.execute(
        "SELECT COUNT(*) FROM financial_data WHERE turnover IS NOT NULL"
    ).fetchone()[0]

    db_size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)

    with open("output/stage4_summary_report.txt", "w") as f:
        f.write("="*60 + "\n")
        f.write("COMP702 — STAGE 4 SUMMARY REPORT\n")
        f.write("AI-Powered SME Financial Health Analyser for Liverpool\n")
        f.write(f"Thinzar Aung (201942837)\n")
        f.write(f"Generated: {datetime.now().strftime('%d %B %Y %H:%M')}\n")
        f.write("="*60 + "\n\n")
        f.write("DATABASE\n" + "-"*40 + "\n")
        f.write(f"Engine:       SQLite 3 (prototype)\n")
        f.write(f"              PostgreSQL planned for full dissertation\n")
        f.write(f"Location:     {DB_PATH}\n")
        f.write(f"Size:         {db_size_mb:.2f} MB\n\n")
        f.write("TABLES\n" + "-"*40 + "\n")
        f.write(f"companies:       {companies_count:,} records\n")
        f.write(f"financial_data:  {financial_count:,} records\n")
        f.write(f"financial_ratios:{ratios_count:,} records\n\n")
        f.write("KEY FINDINGS\n" + "-"*40 + "\n")
        f.write(f"Liverpool SMEs in database:   {companies_count:,}\n")
        f.write(f"With financial data:          {financial_count:,}\n")
        f.write(f"With turnover extracted:      {turnover_count:,}\n\n")
        f.write("NEXT STEP — STAGE 5\n" + "-"*40 + "\n")
        f.write("Build the Streamlit web interface to query this\n")
        f.write("database and display financial health profiles.\n")
        f.write("Migrate to PostgreSQL for full dissertation phase.\n")

    print(f"\n  ✓ Summary report saved")
    print(f"  Database size: {db_size_mb:.2f} MB")


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    print("\n" + "="*60)
    print("  COMP702 — STAGE 4: DATABASE LOADING")
    print("  Thinzar Aung (201942837) — University of Liverpool")
    print("  Database: SQLite (prototype) → PostgreSQL (dissertation)")
    print("="*60)

    conn             = create_database(DB_PATH)
    companies_loaded = load_companies(conn)
    fin_loaded, rat_loaded = load_financial_data(conn)
    run_example_queries(conn)
    save_report(conn)
    conn.close()

    print("\n" + "="*60)
    print("  STAGE 4 COMPLETE")
    print(f"  Database: {DB_PATH}")
    print(f"  Companies:      {companies_loaded:,}")
    print(f"  Financial data: {fin_loaded:,}")
    print(f"  Ratios:         {rat_loaded:,}")
    print("  Ready for Stage 5 — Streamlit web interface")
    print("="*60)


if __name__ == "__main__":
    main()
