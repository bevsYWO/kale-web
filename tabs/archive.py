"""
tabs/archive.py — Archive viewer tab backed by Supabase master_contacts.
"""

from datetime import date

import pandas as pd
import streamlit as st

from db.archive import load_archive, get_client_counts
from db.client import is_configured
from components.stat_cards import render_stat_cards
from components.export_button import render_export_button


def render():
    st.subheader("Archive")
    st.caption("Contacts stored across all clients in Supabase master_contacts.")

    with st.expander("How to use this tab"):
        st.markdown("""
**What it is**
A running master record of every contact ever processed through the Kale Data Hub. It builds automatically — no extra steps needed.

**How it works**
Every time you clean a file through any tab (Riipen, N2, N2 Recruiting, Terraboost, or General), new contacts are automatically added here. Contacts are deduplicated by email — the same email is never stored twice for the same client.

**How to use it**
- **Client filter** — see contacts from one tab or all combined
- **Search bar** — find a specific email or source file
- **From / To** — filter by when a contact was first seen
- **Export Filtered CSV** — download a CSV of whatever is currently showing
        """)

    if not is_configured():
        st.warning(
            "Supabase is not configured. Add your credentials to "
            "`.streamlit/secrets.toml` to enable the archive."
        )
        return

    # ── Refresh ───────────────────────────────────────────────────────────────
    if st.button("Refresh", key="archive_refresh"):
        load_archive.clear()
        get_client_counts.clear()
        st.rerun()

    # ── Filters ───────────────────────────────────────────────────────────────
    client_counts = get_client_counts()
    client_names  = ["All"] + sorted(client_counts.keys())

    col_a, col_b, col_c, col_d = st.columns([2, 2, 2, 2])
    with col_a:
        client_filter = st.selectbox("Client", client_names, key="archive_client")
    with col_b:
        search = st.text_input("Search email", placeholder="@domain.com", key="archive_search")
    with col_c:
        date_from = st.date_input("From", value=None, key="archive_from")
    with col_d:
        date_to   = st.date_input("To",   value=None, key="archive_to")

    df = load_archive(
        client_filter=client_filter if client_filter != "All" else None,
        search=search or None,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
    )

    # ── Stat cards ────────────────────────────────────────────────────────────
    total_unique   = len(df)
    multi_client   = 0
    if not df.empty and "clients" in df.columns:
        multi_client = int(df["clients"].apply(
            lambda c: len(c) > 1 if isinstance(c, list) else False
        ).sum())

    cards = [{"label": "Total Unique Emails", "value": f"{total_unique:,}"},
             {"label": "Multi-client",         "value": multi_client}]
    for client, count in sorted(client_counts.items(), key=lambda x: -x[1])[:4]:
        cards.append({"label": client, "value": count})

    render_stat_cards(cards[:6])  # cap at 6

    # ── Table ─────────────────────────────────────────────────────────────────
    if df.empty:
        st.info("No contacts found with the current filters.")
        return

    # Flatten array columns for display
    display_df = df.copy()
    for col in ["clients", "source_files"]:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(
                lambda v: ", ".join(v) if isinstance(v, list) else str(v)
            )

    st.dataframe(display_df, use_container_width=True, hide_index=True)

    # ── Export ────────────────────────────────────────────────────────────────
    render_export_button(
        display_df,
        label="Export Filtered CSV",
        file_name="kale_archive_export.csv",
        key="archive_dl",
    )
