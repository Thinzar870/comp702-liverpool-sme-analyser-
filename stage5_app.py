"""
COMP702 — STAGE 5: Liverpool SME Financial Health Analyser
===========================================================
Author:  Thinzar Aung (201942837)
Project: AI-Powered SME Financial Health Analyser for Liverpool City Region
Stage:   5 of 7 — Streamlit Web Interface

HOW TO RUN:
  python -m streamlit run stage5_app.py

Then open your browser at: http://localhost:8501
"""

import sqlite3
import pandas as pd
import streamlit as st

DB_PATH = "output/liverpool_sme_analyser.db"

# ── Page config ───────────────────────────────────────────────
st.set_page_config(
    page_title="Liverpool SME Financial Health Analyser",
    page_icon="🏙️",
    layout="wide"
)

# ── Custom CSS ────────────────────────────────────────────────
st.markdown("""
<style>
    .main-title {
        font-size: 2rem; font-weight: 700;
        color: #1F3864; margin-bottom: 0;
    }
    .sub-title {
        font-size: 1rem; color: #2E75B6;
        margin-bottom: 1.5rem;
    }
    .metric-box {
        background: #f8f9fa; border-radius: 8px;
        padding: 1rem; text-align: center;
        border: 1px solid #dee2e6;
    }
    .metric-value {
        font-size: 1.8rem; font-weight: 700;
        color: #1F3864;
    }
    .metric-label {
        font-size: 0.85rem; color: #666;
    }
    .healthy   { color: #0F6E56; font-weight: 700; font-size: 1.2rem; }
    .moderate  { color: #854F0B; font-weight: 700; font-size: 1.2rem; }
    .at-risk   { color: #993C1D; font-weight: 700; font-size: 1.2rem; }
    .section-header {
        font-size: 1.1rem; font-weight: 600;
        color: #1F3864; border-bottom: 2px solid #2E75B6;
        padding-bottom: 4px; margin: 1rem 0 0.5rem;
    }
    .freshness-fresh   { color: #0F6E56; }
    .freshness-caution { color: #854F0B; }
    .freshness-stale   { color: #993C1D; }
</style>
""", unsafe_allow_html=True)


# ── Database connection ───────────────────────────────────────
@st.cache_resource
def get_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


@st.cache_data
def get_database_stats():
    conn = get_connection()
    stats = {}
    stats["total_companies"] = pd.read_sql_query(
        "SELECT COUNT(*) as n FROM companies", conn
    ).iloc[0]["n"]
    stats["with_financials"] = pd.read_sql_query(
        "SELECT COUNT(*) as n FROM financial_data", conn
    ).iloc[0]["n"]
    stats["postcode_districts"] = pd.read_sql_query(
        """SELECT COUNT(DISTINCT postcode_district) as n
           FROM companies
           WHERE postcode_district IS NOT NULL
             AND postcode_district != 'nan'""", conn
    ).iloc[0]["n"]
    return stats


def search_companies(query: str) -> pd.DataFrame:
    conn = get_connection()
    return pd.read_sql_query("""
        SELECT
            company_number,
            company_name,
            company_type,
            postcode,
            sic_code_1,
            last_accounts_date,
            last_accounts_type,
            data_freshness_flag,
            CASE WHEN has_insolvency = 1
                THEN 'Yes' ELSE 'No' END as insolvency_history,
            CASE WHEN has_charges = 1
                THEN 'Yes' ELSE 'No' END as outstanding_charges,
            CASE WHEN api_verified = 1
                THEN 'Yes' ELSE 'No' END as api_verified
        FROM companies
        WHERE UPPER(company_name) LIKE UPPER(?)
           OR company_number LIKE ?
        ORDER BY company_name
        LIMIT 20
    """, conn, params=[f"%{query}%", f"%{query}%"])


def get_financial_profile(company_number: str) -> dict:
    conn = get_connection()

    company = pd.read_sql_query("""
        SELECT * FROM companies
        WHERE company_number = ?
    """, conn, params=[company_number])

    financials = pd.read_sql_query("""
        SELECT * FROM financial_data
        WHERE company_number = ?
    """, conn, params=[company_number])

    ratios = pd.read_sql_query("""
        SELECT * FROM financial_ratios
        WHERE company_number = ?
    """, conn, params=[company_number])

    return {
        "company":    company.iloc[0].to_dict() if len(company) > 0 else {},
        "financials": financials.iloc[0].to_dict() if len(financials) > 0 else {},
        "ratios":     ratios.iloc[0].to_dict() if len(ratios) > 0 else {},
    }


def fmt_currency(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "Not available"
    try:
        v = float(val)
        if abs(v) >= 1_000_000:
            return f"£{v/1_000_000:.2f}M"
        elif abs(v) >= 1_000:
            return f"£{v/1_000:.1f}K"
        else:
            return f"£{v:,.0f}"
    except (ValueError, TypeError):
        return "Not available"


def fmt_ratio(val, decimals=2):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "Not available"
    try:
        return f"{float(val):.{decimals}f}"
    except (ValueError, TypeError):
        return "Not available"


def fmt_pct(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "Not available"
    try:
        return f"{float(val):.1f}%"
    except (ValueError, TypeError):
        return "Not available"


def health_colour(rating: str) -> str:
    if not rating or rating == "nan":
        return "moderate"
    r = rating.upper()
    if "HEALTHY" in r:
        return "healthy"
    elif "RISK" in r:
        return "at-risk"
    return "moderate"


# ═══════════════════════════════════════════════════════════════
# MAIN APP
# ═══════════════════════════════════════════════════════════════

def main():

    # ── Header ────────────────────────────────────────────────
    col_logo, col_title = st.columns([1, 8])
    with col_title:
        st.markdown(
            '<p class="main-title">🏙️ Liverpool SME Financial Health Analyser</p>',
            unsafe_allow_html=True
        )
        st.markdown(
            '<p class="sub-title">AI-Powered Financial Health Assessment for '
            'Liverpool City Region Small and Medium Enterprises</p>',
            unsafe_allow_html=True
        )

    st.markdown(
        "_COMP702 MSc Dissertation Project · Thinzar Aung (201942837) · "
        "University of Liverpool · Supervisor: Dr Olga Anosova_"
    )
    st.divider()

    # ── Database stats ────────────────────────────────────────
    stats = get_database_stats()
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f"""
        <div class="metric-box">
            <div class="metric-value">{stats['total_companies']:,}</div>
            <div class="metric-label">Liverpool City Region SMEs</div>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <div class="metric-box">
            <div class="metric-value">{stats['with_financials']:,}</div>
            <div class="metric-label">With Financial Data</div>
        </div>""", unsafe_allow_html=True)
    with c3:
        st.markdown(f"""
        <div class="metric-box">
            <div class="metric-value">{stats['postcode_districts']}</div>
            <div class="metric-label">Postcode Districts Covered</div>
        </div>""", unsafe_allow_html=True)
    with c4:
        st.markdown(f"""
        <div class="metric-box">
            <div class="metric-value">Free</div>
            <div class="metric-label">Data Source (Companies House)</div>
        </div>""", unsafe_allow_html=True)

    st.divider()

    # ── Tabs ──────────────────────────────────────────────────
    tab1, tab2, tab3 = st.tabs([
        "🔍 Search Company",
        "📊 Liverpool Overview",
        "ℹ️ About This Tool"
    ])

    # ── TAB 1: SEARCH ─────────────────────────────────────────
    with tab1:
        st.markdown("### Search for a Liverpool Company")
        st.markdown(
            "Enter a company name or Companies House number to view "
            "their financial health profile."
        )

        query = st.text_input(
            "Company name or number",
            placeholder="e.g. Baltic Creative, Mill House Hotel, 07588791",
            label_visibility="collapsed"
        )

        if query and len(query) >= 2:
            results = search_companies(query)

            if len(results) == 0:
                st.warning(
                    "No companies found. Try a different name or number."
                )
            else:
                st.success(f"Found {len(results)} matching companies")

                # Show results table
                display_cols = [
                    "company_number", "company_name",
                    "postcode", "last_accounts_type",
                    "data_freshness_flag"
                ]
                st.dataframe(
                    results[display_cols].rename(columns={
                        "company_number":    "Number",
                        "company_name":      "Company Name",
                        "postcode":          "Postcode",
                        "last_accounts_type":"Accounts Type",
                        "data_freshness_flag":"Data Freshness"
                    }),
                    use_container_width=True,
                    hide_index=True
                )

                # Select company to view profile
                company_options = {
                    f"{row['company_name']} ({row['company_number']})":
                    row["company_number"]
                    for _, row in results.iterrows()
                }
                selected = st.selectbox(
                    "Select a company to view full financial profile:",
                    options=list(company_options.keys())
                )

                if selected:
                    company_number = company_options[selected]
                    profile = get_financial_profile(company_number)
                    company   = profile["company"]
                    financials= profile["financials"]
                    ratios    = profile["ratios"]

                    st.divider()

                    # ── Company header ─────────────────────────
                    name   = company.get("company_name", "Unknown")
                    rating = str(ratios.get("health_rating", ""))
                    score  = ratios.get("health_score")
                    colour = health_colour(rating)

                    col_name, col_score = st.columns([3, 1])
                    with col_name:
                        st.markdown(f"## {name}")
                        st.markdown(
                            f"**{company.get('company_number')}** · "
                            f"{company.get('postcode', '')} · "
                            f"{company.get('company_type', '')}"
                        )
                    with col_score:
                        if rating and rating != "nan" and score:
                            st.markdown(
                                f'<div class="metric-box">'
                                f'<div class="metric-value">'
                                f'{float(score):.0f}/100</div>'
                                f'<div class="{colour}">{rating}</div>'
                                f'</div>',
                                unsafe_allow_html=True
                            )
                        else:
                            st.markdown(
                                '<div class="metric-box">'
                                '<div class="metric-value">N/A</div>'
                                '<div class="metric-label">'
                                'No financial data</div></div>',
                                unsafe_allow_html=True
                            )

                    # ── Company details ────────────────────────
                    st.markdown(
                        '<p class="section-header">'
                        'Company Information</p>',
                        unsafe_allow_html=True
                    )
                    d1, d2, d3 = st.columns(3)
                    with d1:
                        st.metric("SIC Code",
                                  company.get("sic_code_1", "N/A") or "N/A")
                        st.metric("Insolvency History",
                                  "Yes" if company.get("has_insolvency") == 1
                                  else "No")
                    with d2:
                        st.metric("Last Accounts",
                                  company.get("last_accounts_date", "N/A")
                                  or "N/A")
                        st.metric("Outstanding Charges",
                                  "Yes" if company.get("has_charges") == 1
                                  else "No")
                    with d3:
                        st.metric("Accounts Type",
                                  company.get("last_accounts_type", "N/A")
                                  or "N/A")
                        freshness = str(
                            company.get("data_freshness_flag", "Unknown")
                        )
                        st.metric("Data Freshness", freshness)

                    # ── Financial figures ──────────────────────
                    if financials:
                        st.markdown(
                            '<p class="section-header">'
                            'Financial Figures</p>',
                            unsafe_allow_html=True
                        )
                        f1, f2, f3 = st.columns(3)
                        with f1:
                            st.metric("Turnover",
                                      fmt_currency(
                                          financials.get("turnover")))
                            st.metric("Current Assets",
                                      fmt_currency(
                                          financials.get("current_assets")))
                            st.metric("Total Assets",
                                      fmt_currency(
                                          financials.get("total_assets")))
                        with f2:
                            st.metric("Gross Profit",
                                      fmt_currency(
                                          financials.get("gross_profit")))
                            st.metric("Current Liabilities",
                                      fmt_currency(
                                          financials.get(
                                              "current_liabilities")))
                            st.metric("Total Liabilities",
                                      fmt_currency(
                                          financials.get(
                                              "total_liabilities")))
                        with f3:
                            st.metric("Profit Before Tax",
                                      fmt_currency(
                                          financials.get(
                                              "profit_before_tax")))
                            st.metric("Net Assets",
                                      fmt_currency(
                                          financials.get("net_assets")))
                            st.metric("Employees",
                                      fmt_ratio(
                                          financials.get("employees"), 0))

                        # ── Ratios ────────────────────────────
                        st.markdown(
                            '<p class="section-header">'
                            'Financial Ratios</p>',
                            unsafe_allow_html=True
                        )
                        r1, r2, r3 = st.columns(3)
                        with r1:
                            st.metric(
                                "Current Ratio",
                                fmt_ratio(ratios.get("current_ratio")),
                                help="Above 1.5 = healthy liquidity"
                            )
                            st.metric(
                                "Gross Margin",
                                fmt_pct(ratios.get("gross_margin_pct")),
                                help="Higher is better"
                            )
                        with r2:
                            st.metric(
                                "Net Margin",
                                fmt_pct(ratios.get("net_margin_pct")),
                                help="Higher is better"
                            )
                            st.metric(
                                "Debt to Equity",
                                fmt_ratio(ratios.get("debt_to_equity")),
                                help="Below 1.5 = manageable leverage"
                            )
                        with r3:
                            st.metric(
                                "Asset Turnover",
                                fmt_ratio(ratios.get("asset_turnover")),
                                help="Higher = more efficient use of assets"
                            )
                            st.metric(
                                "Quick Ratio",
                                fmt_ratio(ratios.get("quick_ratio")),
                                help="Above 1.0 = can cover short-term debts"
                            )

                        # ── Plain English summary ──────────────
                        st.markdown(
                            '<p class="section-header">'
                            'Plain-English Summary</p>',
                            unsafe_allow_html=True
                        )
                        summary = generate_summary(
                            name, company, financials, ratios
                        )
                        st.info(summary)

                        st.caption(
                            "⚠️ Data freshness: "
                            f"{company.get('data_freshness_flag', 'Unknown')}. "
                            "Financial data sourced from publicly filed "
                            "Companies House accounts. This tool is for "
                            "research purposes only and does not constitute "
                            "financial advice."
                        )
                    else:
                        st.info(
                            "No iXBRL financial data available for this "
                            "company. They may have filed PDF accounts only, "
                            "or their accounts may not yet be in the database."
                        )

    # ── TAB 2: OVERVIEW ───────────────────────────────────────
    with tab2:
        st.markdown("### Liverpool City Region SME Overview")
        conn = get_connection()

        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown("**Top 10 Postcode Districts by Company Count**")
            df_post = pd.read_sql_query("""
                SELECT postcode_district, COUNT(*) as companies
                FROM companies
                WHERE postcode_district IS NOT NULL
                  AND postcode_district != ''
                  AND postcode_district != 'nan'
                GROUP BY postcode_district
                ORDER BY companies DESC
                LIMIT 10
            """, conn)
            st.bar_chart(
                df_post.set_index("postcode_district")["companies"]
            )

        with col_b:
            st.markdown("**Accounts Type Breakdown**")
            df_acct = pd.read_sql_query("""
                SELECT last_accounts_type, COUNT(*) as count
                FROM companies
                WHERE last_accounts_type IS NOT NULL
                  AND last_accounts_type != ''
                  AND last_accounts_type != 'nan'
                GROUP BY last_accounts_type
                ORDER BY count DESC
                LIMIT 8
            """, conn)
            st.bar_chart(
                df_acct.set_index("last_accounts_type")["count"]
            )

        st.markdown("**Data Freshness of Liverpool SME Filings**")
        df_fresh = pd.read_sql_query("""
            SELECT data_freshness_flag, COUNT(*) as count
            FROM companies
            WHERE data_freshness_flag IS NOT NULL
              AND data_freshness_flag != ''
              AND data_freshness_flag != 'nan'
            GROUP BY data_freshness_flag
            ORDER BY count DESC
        """, conn)
        if len(df_fresh) > 0:
            st.dataframe(
                df_fresh.rename(columns={
                    "data_freshness_flag": "Freshness Status",
                    "count": "Number of Companies"
                }),
                use_container_width=True,
                hide_index=True
            )

        st.markdown("**Top 10 Industries in Liverpool City Region**")
        df_sic = pd.read_sql_query("""
            SELECT sic_code_1, COUNT(*) as companies
            FROM companies
            WHERE sic_code_1 IS NOT NULL
              AND sic_code_1 != ''
              AND sic_code_1 != 'nan'
            GROUP BY sic_code_1
            ORDER BY companies DESC
            LIMIT 10
        """, conn)
        st.dataframe(
            df_sic.rename(columns={
                "sic_code_1": "SIC Code / Industry",
                "companies":  "Number of Companies"
            }),
            use_container_width=True,
            hide_index=True
        )

    # ── TAB 3: ABOUT ──────────────────────────────────────────
    with tab3:
        st.markdown("### About This Tool")
        st.markdown("""
This tool is a prototype built as part of a COMP702 MSc dissertation project
at the University of Liverpool.

**Project:** AI-Powered SME Financial Health Analyser for the Liverpool City Region

**Student:** Thinzar Aung (201942837)

**Supervisor:** Dr Olga Anosova — School of Computer Science and Informatics

---

#### How It Works

The tool uses a 5-stage pipeline:

1. **Stage 1 — Company Discovery:** Downloads the Companies House Free Company
   Data Product and filters to Liverpool City Region SMEs by postcode
2. **Stage 2 — API Verification:** Calls the Companies House REST API to verify
   current company status and retrieve filing document links
3. **Stage 3 — iXBRL Parsing:** Downloads and parses iXBRL financial accounts
   documents to extract financial figures
4. **Stage 4 — Database Loading:** Loads all structured data into a relational
   database (SQLite prototype → PostgreSQL for full dissertation)
5. **Stage 5 — Web Interface:** This Streamlit application queries the database
   and displays financial health profiles

---

#### Data Sources

- **Companies House Free Company Data Product** — official UK Government data
- **Companies House Public Data REST API** — live company verification
- **Companies House Document API** — iXBRL financial accounts documents

All data is publicly available under the Open Government Licence v3.0.

---

#### Limitations

- Financial data is based on the most recent filed accounts which may be
  up to 9 months after the company's financial year end
- Approximately 26% of companies file paper accounts not available as iXBRL
- Health scores are rule-based at this prototype stage — ML model planned
- This tool is for research purposes only and does not constitute
  financial or investment advice
        """)


# ═══════════════════════════════════════════════════════════════
# PLAIN ENGLISH SUMMARY GENERATOR
# ═══════════════════════════════════════════════════════════════

def generate_summary(name, company, financials, ratios) -> str:
    """
    Generates a plain-English financial health summary.
    Rule-based approach as advised by Dr Anosova —
    avoids LLM hallucination risk at prototype stage.
    """
    parts = []

    # Overall rating
    rating = str(ratios.get("health_rating", ""))
    score  = ratios.get("health_score")
    if rating and rating != "nan" and score:
        parts.append(
            f"{name} receives a financial health score of "
            f"{float(score):.0f}/100, rated as {rating}."
        )

    # Liquidity
    cr = ratios.get("current_ratio")
    if cr and not pd.isna(cr):
        cr = float(cr)
        if cr > 2.0:
            parts.append(
                f"The company has strong liquidity with a current ratio "
                f"of {cr:.2f}, well above the healthy threshold of 1.5."
            )
        elif cr > 1.5:
            parts.append(
                f"Liquidity is healthy — current ratio of {cr:.2f} "
                f"indicates the company can meet its short-term obligations."
            )
        elif cr > 1.0:
            parts.append(
                f"Liquidity is adequate but tight — current ratio "
                f"of {cr:.2f}. Worth monitoring."
            )
        else:
            parts.append(
                f"Liquidity is a concern — current ratio of {cr:.2f} "
                f"suggests potential difficulty meeting short-term debts."
            )

    # Profitability
    gm = ratios.get("gross_margin_pct")
    if gm and not pd.isna(gm):
        gm = float(gm)
        if gm > 30:
            parts.append(
                f"Profitability is strong with a gross margin of "
                f"{gm:.1f}%."
            )
        elif gm > 15:
            parts.append(
                f"Profitability is acceptable with a gross margin "
                f"of {gm:.1f}%."
            )
        elif gm > 0:
            parts.append(
                f"Profitability is low — gross margin of {gm:.1f}%. "
                f"Cost management may need attention."
            )
        else:
            parts.append(
                f"The company is operating at a gross loss "
                f"(margin: {gm:.1f}%). This is a significant concern."
            )

    # Risk flags
    if company.get("has_insolvency") == 1:
        parts.append(
            "⚠️ This company has a history of insolvency proceedings."
        )
    if company.get("has_charges") == 1:
        parts.append(
            "⚠️ This company has outstanding charges registered "
            "against it."
        )

    # Data freshness
    freshness = str(company.get("data_freshness_flag", ""))
    if "STALE" in freshness:
        parts.append(
            "Note: Financial data is over 18 months old — "
            "treat this assessment with caution."
        )
    elif "CAUTION" in freshness:
        parts.append(
            "Note: Financial data is 9-18 months old. "
            "The company may have filed more recent accounts."
        )

    if not parts:
        return (
            "Financial data is limited for this company. "
            "They may have filed micro-entity accounts with "
            "restricted disclosure, or their iXBRL data could "
            "not be fully parsed."
        )

    return " ".join(parts)


if __name__ == "__main__":
    main()
