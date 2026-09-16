"""
COMP702 — Database Viewer
==========================
Author:  Thinzar Aung (201942837)
Project: AI-Powered SME Financial Health Analyser for Liverpool

Shows the contents of the liverpool_sme_analyser.db database
in a clear, readable format suitable for showing to supervisor.

HOW TO RUN:
  python database_viewer.py
"""

import sqlite3
import pandas as pd
from datetime import datetime

DB_PATH = "output/liverpool_sme_analyser.db"


def view_database():
    print("\n" + "="*70)
    print("  LIVERPOOL SME FINANCIAL HEALTH ANALYSER — DATABASE VIEWER")
    print("  Thinzar Aung (201942837) — University of Liverpool")
    print(f"  Generated: {datetime.now().strftime('%d %B %Y %H:%M')}")
    print("="*70)

    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # ── DATABASE OVERVIEW ─────────────────────────────────────
    print("\n1. DATABASE OVERVIEW")
    print("-"*70)
    tables = ["companies", "financial_data", "financial_ratios"]
    for table in tables:
        count = cursor.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]
        print(f"   Table '{table}': {count:,} records")

    import os
    size_mb = os.path.getsize(DB_PATH) / (1024*1024)
    print(f"   Database file size: {size_mb:.2f} MB")
    print(f"   Database engine: SQLite 3 (prototype)")
    print(f"   PostgreSQL migration: planned for dissertation phase")

    # ── COMPANIES TABLE SAMPLE ────────────────────────────────
    print("\n2. COMPANIES TABLE — Sample of 10 Liverpool SMEs")
    print("-"*70)
    df = pd.read_sql_query("""
        SELECT
            company_number,
            company_name,
            company_type,
            postcode,
            sic_code_1,
            last_accounts_date,
            last_accounts_type,
            data_freshness_flag,
            CASE WHEN api_verified = 1 THEN 'Yes' ELSE 'No' END as api_verified
        FROM companies
        WHERE postcode IS NOT NULL
          AND postcode != ''
          AND postcode != 'nan'
        LIMIT 10
    """, conn)
    print(df.to_string(index=False))

    # ── FINANCIAL DATA TABLE SAMPLE ───────────────────────────
    print("\n3. FINANCIAL DATA TABLE — Sample of 10 companies with figures")
    print("-"*70)
    df2 = pd.read_sql_query("""
        SELECT
            f.company_number,
            c.company_name,
            f.parse_method,
            f.fields_extracted,
            ROUND(f.turnover, 0)            as turnover_gbp,
            ROUND(f.gross_profit, 0)        as gross_profit_gbp,
            ROUND(f.profit_before_tax, 0)   as profit_before_tax_gbp,
            ROUND(f.current_assets, 0)      as current_assets_gbp,
            ROUND(f.current_liabilities, 0) as current_liabilities_gbp,
            ROUND(f.net_assets, 0)          as net_assets_gbp
        FROM financial_data f
        LEFT JOIN companies c
            ON f.company_number = c.company_number
        WHERE f.fields_extracted > 0
        LIMIT 10
    """, conn)
    print(df2.to_string(index=False))

    # ── FINANCIAL RATIOS TABLE SAMPLE ─────────────────────────
    print("\n4. FINANCIAL RATIOS TABLE — Sample of 10 companies")
    print("-"*70)
    df3 = pd.read_sql_query("""
        SELECT
            r.company_number,
            c.company_name,
            ROUND(r.current_ratio, 2)       as current_ratio,
            ROUND(r.gross_margin_pct, 1)    as gross_margin_pct,
            ROUND(r.net_margin_pct, 1)      as net_margin_pct,
            ROUND(r.debt_to_equity, 2)      as debt_to_equity,
            ROUND(r.health_score, 0)        as health_score,
            r.health_rating
        FROM financial_ratios r
        LEFT JOIN companies c
            ON r.company_number = c.company_number
        LIMIT 10
    """, conn)
    print(df3.to_string(index=False))

    # ── POSTCODE BREAKDOWN ────────────────────────────────────
    print("\n5. LIVERPOOL SMEs BY POSTCODE DISTRICT (top 15)")
    print("-"*70)
    df4 = pd.read_sql_query("""
        SELECT
            postcode_district,
            COUNT(*) as total_companies,
            SUM(CASE WHEN api_verified = 1
                THEN 1 ELSE 0 END) as api_verified
        FROM companies
        WHERE postcode_district IS NOT NULL
          AND postcode_district != ''
          AND postcode_district != 'nan'
        GROUP BY postcode_district
        ORDER BY total_companies DESC
        LIMIT 15
    """, conn)
    print(df4.to_string(index=False))

    # ── SIC CODE BREAKDOWN ────────────────────────────────────
    print("\n6. TOP 10 INDUSTRIES (by SIC code)")
    print("-"*70)
    df5 = pd.read_sql_query("""
        SELECT
            sic_code_1,
            COUNT(*) as company_count
        FROM companies
        WHERE sic_code_1 IS NOT NULL
          AND sic_code_1 != ''
          AND sic_code_1 != 'nan'
        GROUP BY sic_code_1
        ORDER BY company_count DESC
        LIMIT 10
    """, conn)
    print(df5.to_string(index=False))

    # ── DATA FRESHNESS ────────────────────────────────────────
    print("\n7. DATA FRESHNESS OF FILINGS")
    print("-"*70)
    df6 = pd.read_sql_query("""
        SELECT
            data_freshness_flag,
            COUNT(*) as company_count
        FROM companies
        WHERE data_freshness_flag IS NOT NULL
          AND data_freshness_flag != ''
          AND data_freshness_flag != 'nan'
        GROUP BY data_freshness_flag
        ORDER BY company_count DESC
    """, conn)
    print(df6.to_string(index=False))

    # ── ACCOUNTS TYPE BREAKDOWN ───────────────────────────────
    print("\n8. ACCOUNTS TYPE BREAKDOWN")
    print("-"*70)
    df7 = pd.read_sql_query("""
        SELECT
            last_accounts_type,
            COUNT(*) as company_count
        FROM companies
        WHERE last_accounts_type IS NOT NULL
          AND last_accounts_type != ''
          AND last_accounts_type != 'nan'
        GROUP BY last_accounts_type
        ORDER BY company_count DESC
        LIMIT 10
    """, conn)
    print(df7.to_string(index=False))

    # ── EXAMPLE FULL COMPANY PROFILE ─────────────────────────
    print("\n9. EXAMPLE FULL COMPANY PROFILE")
    print("   (What the tool will show for one Liverpool SME)")
    print("-"*70)
    result = cursor.execute("""
        SELECT
            c.company_number,
            c.company_name,
            c.company_type,
            c.postcode,
            c.sic_code_1,
            c.last_accounts_date,
            c.last_accounts_type,
            c.data_freshness_flag,
            c.has_insolvency,
            c.has_charges,
            f.turnover,
            f.gross_profit,
            f.profit_before_tax,
            f.current_assets,
            f.current_liabilities,
            f.net_assets,
            f.employees,
            r.current_ratio,
            r.gross_margin_pct,
            r.net_margin_pct,
            r.debt_to_equity,
            r.health_score,
            r.health_rating
        FROM companies c
        JOIN financial_data f
            ON c.company_number = f.company_number
        JOIN financial_ratios r
            ON c.company_number = r.company_number
        WHERE f.fields_extracted > 2
        LIMIT 1
    """).fetchone()

    if result:
        labels = [
            "Company number",       "Company name",
            "Company type",         "Postcode",
            "SIC code",             "Last accounts date",
            "Accounts type",        "Data freshness",
            "Has insolvency",       "Has charges",
            "Turnover (£)",         "Gross profit (£)",
            "Profit before tax (£)","Current assets (£)",
            "Current liabilities (£)","Net assets (£)",
            "Employees",            "Current ratio",
            "Gross margin %",       "Net margin %",
            "Debt to equity",       "Health score (/100)",
            "Health rating"
        ]
        print()
        for label, value in zip(labels, result):
            if isinstance(value, float) and abs(value) > 1000:
                print(f"   {label:30} £{value:>15,.0f}")
            elif isinstance(value, float):
                print(f"   {label:30}  {value:>15.2f}")
            else:
                print(f"   {label:30}  {str(value)}")
    else:
        print("   No complete company profile found yet")

    # ── PIPELINE SUMMARY ──────────────────────────────────────
    print("\n10. PIPELINE SUMMARY")
    print("-"*70)
    log = pd.read_sql_query("""
        SELECT stage, action, records_count, notes, created_at
        FROM pipeline_log
        ORDER BY id
    """, conn)
    print(log.to_string(index=False))

    print("\n" + "="*70)
    print("  END OF DATABASE REPORT")
    print("  This database is the output of the COMP702 pipeline")
    print("  Stages 1-4: company discovery, API verification,")
    print("  iXBRL parsing, and database loading.")
    print("  Stage 5 next: Streamlit web interface")
    print("="*70)

    conn.close()


if __name__ == "__main__":
    view_database()
