"""
tabs/home.py — Home / dashboard tab.
"""

import streamlit as st

from db.archive import get_client_counts, get_total_contact_count
from db.client import is_configured
from components.stat_cards import render_stat_cards


_TAB_GUIDE = [
    {
        "name": "Riipen",
        "desc": (
            "Clean Clay contact exports before email campaigns. "
            "Fixes encoding, placeholder names, and city values. "
            "Detects duplicates against the master archive."
        ),
    },
    {
        "name": "N2",
        "desc": (
            "Assign Tier 1 / 2 / 3 to N2 leads by business type. "
            "Automatically removes churches, non-profits, agencies, and unknowns. "
            "Supports neighbourhood filtering and tier interleaving."
        ),
    },
    {
        "name": "N2 Recruiting",
        "desc": (
            "Clean N2 Recruiting contact exports — fixes first names, "
            "garbled company lines, and invalid city values. "
            "Shows which contacts are already in the archive."
        ),
    },
    {
        "name": "Terraboost",
        "desc": (
            "Validate Terraboost grocery store leads. "
            "Checks chain names (Kroger, HEB, etc.), normalises star ratings, "
            "and removes rows with missing business categories."
        ),
    },
    {
        "name": "General",
        "desc": (
            "Universal cleaner for any CSV or Excel file. "
            "Add custom per-column rules — remove/keep rows by keyword, "
            "replace values, fix case, and more. "
            "Supports plain-English instructions."
        ),
    },
    {
        "name": "Archive",
        "desc": (
            "Master record of every contact ever processed. "
            "Filter by client, email, or date range. "
            "Export a clean CSV at any time."
        ),
    },
]


def render():
    user_name = st.session_state.get("user_name", "there")

    st.markdown(f"## Welcome back, {user_name}!")
    st.caption("Kale Data Hub — internal team tool for data cleaning and outreach prep.")

    st.divider()

    # ── Archive stats ─────────────────────────────────────────────────────────
    if is_configured():
        col_title, col_btn = st.columns([8, 1])
        with col_title:
            st.markdown("#### Team Archive")
        with col_btn:
            if st.button("Refresh", key="home_refresh"):
                get_client_counts.clear()
                get_total_contact_count.clear()
                st.rerun()
        try:
            counts = get_client_counts()
            total  = get_total_contact_count()
            cards  = [{"label": "Total Contacts Archived", "value": f"{total:,}"}]
            for client, count in sorted(counts.items(), key=lambda x: -x[1]):
                cards.append({"label": client, "value": f"{count:,}"})
            render_stat_cards(cards[:6])
        except Exception:
            st.info("Archive stats unavailable right now.")
    else:
        st.info("Archive not connected — add Supabase credentials to secrets.toml to enable team tracking.")

    st.divider()

    # ── Tab quick guide ────────────────────────────────────────────────────────
    st.markdown("#### What each tab does")

    col1, col2, col3 = st.columns(3)
    cols = [col1, col2, col3, col1, col2, col3]

    for guide, col in zip(_TAB_GUIDE, cols):
        with col:
            with st.container(border=True):
                st.markdown(f"**{guide['name']}**")
                st.caption(guide["desc"])
