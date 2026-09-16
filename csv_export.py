"""
COMP702 — Clean CSV Export from Database
==========================================
Author:  Thinzar Aung (201942837)
Project: AI-Powered SME Financial Health Analyser for Liverpool City Region

PURPOSE:
  Exports clean, well-structured CSV files from the SQLite database.
  These CSVs are the verified intermediate outputs that will be loaded
  into PostgreSQL during the full dissertation phase.

  As advised by supervisor Dr Olga Anosova, structured CSV files
  should be produced and validated before database migration.

OUTPUT FILES:
  output/csv_export/01_companies.csv          — all 90,707 Liverpool SMEs
  output/csv_export/02_companies_verified.csv — 500 API verified companies
  output/csv_export/03_financial_data.csv     — 317 companies with figures
  output/csv_export/04_financial_ratios.csv   — 317 companies with ratios
  output/csv_export/05_complete_profiles.csv  — joined view of all data
  output/csv_export/06_data_quality_report.csv— data quality findings

HOW TO RUN:
  python csv_export.py
"""

import os
import sqlite3
import pandas as pd
from datetime import datetime

os.makedirs("output/csv_export", exist_ok=True)

DB_PATH = "output/liverpool_sme_analyser.db"


def export_all_csvs():
    print("\n" + "="*65)
    print("  COMP702 — CLEAN CSV EXPORT FROM DATABASE")
    print("  Thinzar Aung (201942837) — University of Liverpool")
    print(f"  Generated: {datetime.now().strftime('%d %B %Y %H:%M')}")
    print("="*65)

    conn = sqlite3.connect(DB_PATH)

    # ── CSV 1: All Liverpool SMEs ─────────────────────────────
    print("\n  Exporting CSV 1: All Liverpool SMEs...")
    df1 = pd.read_sql_query("""
        SELECT
            company_number,
            company_name,
            company_type,
            company_status,
            postcode,
            postcode_district,
            address_line1,
            post_town,
            sic_code_1,
            sic_code_2,
            incorporation_date,
            company_age_years,
            CASE WHEN has_insolvency = 1
                THEN 'Yes' ELSE 'No' END as has_insolvency_history,
            CASE WHEN has_charges = 1
                THEN 'Yes' ELSE 'No' END as has_outstanding_charges,
            last_accounts_date,
            last_accounts_type,
            data_freshness_flag,
            data_freshness_months,
            CASE WHEN api_verified = 1
                THEN 'Yes' ELSE 'No' END as api_verified,
            pipeline_stage,
            created_at
        FROM companies
        ORDER BY postcode_district, company_name
    """, conn)
    path1 = "output/csv_export/01_all_liverpool_smes.csv"
    df1.to_csv(path1, index=False)
    print(f"  ✓ {path1} — {len(df1):,} rows")

    # ── CSV 2: API Verified Companies ─────────────────────────
    print("\n  Exporting CSV 2: API Verified companies...")
    df2 = pd.read_sql_query("""
        SELECT
            company_number,
            company_name,
            company_type,
            company_status,
            postcode,
            postcode_district,
            sic_code_1,
            company_age_years,
            CASE WHEN has_insolvency = 1
                THEN 'Yes' ELSE 'No' END as has_insolvency_history,
            CASE WHEN has_charges = 1
                THEN 'Yes' ELSE 'No' END as has_outstanding_charges,
            last_accounts_date,
            last_accounts_type,
            data_freshness_flag,
            data_freshness_months
        FROM companies
        WHERE api_verified = 1
        ORDER BY postcode_district, company_name
    """, conn)
    path2 = "output/csv_export/02_api_verified_companies.csv"
    df2.to_csv(path2, index=False)
    print(f"  ✓ {path2} — {len(df2):,} rows")

    # ── CSV 3: Financial Data ─────────────────────────────────
    print("\n  Exporting CSV 3: Extracted financial figures...")
    df3 = pd.read_sql_query("""
        SELECT
            f.company_number,
            c.company_name,
            c.postcode,
            c.postcode_district,
            c.sic_code_1,
            c.last_accounts_type,
            c.data_freshness_flag,
            f.balance_sheet_date,
            f.parse_method,
            f.fields_extracted,
            f.turnover,
            f.gross_profit,
            f.operating_profit,
            f.profit_before_tax,
            f.profit_after_tax,
            f.total_assets,
            f.fixed_assets,
            f.current_assets,
            f.cash,
            f.debtors,
            f.current_liabilities,
            f.long_term_liabilities,
            f.total_liabilities,
            f.net_assets,
            f.equity,
            f.employees
        FROM financial_data f
        LEFT JOIN companies c
            ON f.company_number = c.company_number
        ORDER BY c.postcode_district, c.company_name
    """, conn)
    path3 = "output/csv_export/03_financial_data.csv"
    df3.to_csv(path3, index=False)
    print(f"  ✓ {path3} — {len(df3):,} rows")

    # ── CSV 4: Financial Ratios ───────────────────────────────
    print("\n  Exporting CSV 4: Calculated financial ratios...")
    df4 = pd.read_sql_query("""
        SELECT
            r.company_number,
            c.company_name,
            c.postcode,
            c.postcode_district,
            c.sic_code_1,
            r.balance_sheet_date,
            r.current_ratio,
            r.quick_ratio,
            r.gross_margin_pct,
            r.operating_margin_pct,
            r.net_margin_pct,
            r.debt_to_equity,
            r.asset_turnover,
            r.health_score,
            r.health_rating
        FROM financial_ratios r
        LEFT JOIN companies c
            ON r.company_number = c.company_number
        ORDER BY r.health_score DESC
    """, conn)
    path4 = "output/csv_export/04_financial_ratios.csv"
    df4.to_csv(path4, index=False)
    print(f"  ✓ {path4} — {len(df4):,} rows")

    # ── CSV 5: Complete Profiles (joined view) ────────────────
    print("\n  Exporting CSV 5: Complete company financial profiles...")
    df5 = pd.read_sql_query("""
        SELECT
            c.company_number,
            c.company_name,
            c.company_type,
            c.company_status,
            c.postcode,
            c.postcode_district,
            c.sic_code_1,
            c.company_age_years,
            CASE WHEN c.has_insolvency = 1
                THEN 'Yes' ELSE 'No' END as has_insolvency_history,
            CASE WHEN c.has_charges = 1
                THEN 'Yes' ELSE 'No' END as has_outstanding_charges,
            c.last_accounts_date,
            c.last_accounts_type,
            c.data_freshness_flag,
            c.data_freshness_months,
            f.balance_sheet_date,
            f.parse_method,
            f.fields_extracted,
            f.turnover,
            f.gross_profit,
            f.operating_profit,
            f.profit_before_tax,
            f.total_assets,
            f.current_assets,
            f.current_liabilities,
            f.net_assets,
            f.equity,
            f.employees,
            r.current_ratio,
            r.quick_ratio,
            r.gross_margin_pct,
            r.net_margin_pct,
            r.debt_to_equity,
            r.asset_turnover,
            r.health_score,
            r.health_rating
        FROM companies c
        JOIN financial_data f
            ON c.company_number = f.company_number
        JOIN financial_ratios r
            ON c.company_number = r.company_number
        ORDER BY r.health_score DESC, c.company_name
    """, conn)
    path5 = "output/csv_export/05_complete_profiles.csv"
    df5.to_csv(path5, index=False)
    print(f"  ✓ {path5} — {len(df5):,} rows")

    # ── CSV 6: Data Quality Report ────────────────────────────
    print("\n  Exporting CSV 6: Data quality findings...")

    quality_rows = []

    # Coverage
    total = len(df1)
    api_verified = len(df2)
    with_financials = len(df3)
    with_all_fields = len(df5)

    quality_rows.append({
        "metric": "Total Liverpool City Region SMEs identified",
        "count": total,
        "percentage": "100%",
        "notes": "From Companies House Free Company Data Product June 2026"
    })
    quality_rows.append({
        "metric": "API verified (current status confirmed)",
        "count": api_verified,
        "percentage": f"{api_verified/total*100:.1f}%",
        "notes": "Sample verified via Companies House REST API"
    })
    quality_rows.append({
        "metric": "iXBRL documents downloaded",
        "count": 363,
        "percentage": f"{363/api_verified*100:.1f}% of verified sample",
        "notes": "Via Companies House Document API"
    })
    quality_rows.append({
        "metric": "Successfully parsed with financial data",
        "count": with_financials,
        "percentage": f"{with_financials/363*100:.1f}% of downloaded",
        "notes": "Parsed using ixbrlparse and BeautifulSoup"
    })
    quality_rows.append({
        "metric": "PDF only (no iXBRL available)",
        "count": 20,
        "percentage": f"{20/363*100:.1f}% of downloaded",
        "notes": "These companies filed PDF accounts only"
    })
    quality_rows.append({
        "metric": "Parse failed (data quality issues)",
        "count": 26,
        "percentage": f"{26/363*100:.1f}% of downloaded",
        "notes": "iXBRL tag inconsistency or missing fields"
    })
    quality_rows.append({
        "metric": "Complete profiles (all data joined)",
        "count": with_all_fields,
        "percentage": f"{with_all_fields/363*100:.1f}% of downloaded",
        "notes": "Company + financial + ratios all present"
    })

    # Freshness breakdown
    freshness = df1["data_freshness_flag"].value_counts()
    for flag, count in freshness.items():
        if flag and flag != "nan":
            quality_rows.append({
                "metric": f"Data freshness: {flag}",
                "count": count,
                "percentage": f"{count/total*100:.1f}%",
                "notes": "Based on last accounts filing date"
            })

    # Accounts type breakdown
    acct_types = df1["last_accounts_type"].value_counts()
    for acct_type, count in acct_types.head(6).items():
        if acct_type and acct_type != "nan":
            quality_rows.append({
                "metric": f"Accounts type: {acct_type}",
                "count": count,
                "percentage": f"{count/total*100:.2f}%",
                "notes": "From Companies House filing metadata"
            })

    df6 = pd.DataFrame(quality_rows)
    path6 = "output/csv_export/06_data_quality_report.csv"
    df6.to_csv(path6, index=False)
    print(f"  ✓ {path6} — {len(df6):,} rows")

    conn.close()

    # ── PRINT SUMMARY ─────────────────────────────────────────
    print("\n" + "="*65)
    print("  CSV EXPORT COMPLETE")
    print("="*65)
    print(f"""
  Files saved to: output/csv_export/

  01_all_liverpool_smes.csv       {len(df1):>8,} Liverpool SMEs
  02_api_verified_companies.csv   {len(df2):>8,} API verified
  03_financial_data.csv           {len(df3):>8,} with financial figures
  04_financial_ratios.csv         {len(df4):>8,} with calculated ratios
  05_complete_profiles.csv        {len(df5):>8,} complete profiles
  06_data_quality_report.csv      {len(df6):>8,} quality metrics

  NOTES FOR SUPERVISOR:
  - These CSVs are the structured intermediate outputs of the pipeline
  - They will be loaded into PostgreSQL for the dissertation phase
  - 05_complete_profiles.csv is the main deliverable — it joins
    company metadata, financial figures, and ratios in one table
  - 06_data_quality_report.csv documents all pipeline coverage
    and quality metrics honestly
    """)


if __name__ == "__main__":
    export_all_csvs()
