"""
tabs/terraboost.py — Terraboost data cleaner tab.
"""

import pandas as pd
import streamlit as st

from core.terraboost_cleaner import clean_terraboost_dataframe, TB_EXPORT_RENAME
from components.stat_cards import render_stat_cards
from components.export_button import render_export_button
from db.archive import append_to_archive
from db.platform_history import record_export
from db.client import is_configured

EXPORT_PLATFORMS = ["Instantly", "EmailBison", "Personal Bison"]


def _load_file(uploaded) -> pd.DataFrame:
    name = uploaded.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded, dtype=str, keep_default_na=False)
    return pd.read_excel(uploaded, dtype=str, keep_default_na=False)


def _find_email_col(df: pd.DataFrame):
    import re
    for col in df.columns:
        if re.search(r'^email$|^email[\s_]?address$', col, re.IGNORECASE):
            return col
    return None


def render():
    state = st.session_state.setdefault("terraboost", {
        "df_orig":    None,
        "df_kept":    None,
        "df_removed": None,
        "col_map":    {},
        "filename":   None,
    })

    st.subheader("Terraboost Cleaner")
    st.caption("Validates store names, star ratings, and business categories for Terraboost campaigns.")

    uploaded = st.file_uploader(
        "Upload CSV or Excel", type=["csv", "xlsx", "xls"], key="tb_upload"
    )

    if uploaded and uploaded.name != state.get("filename"):
        with st.spinner("Cleaning..."):
            try:
                df_orig = _load_file(uploaded)
                kept, removed, cm = clean_terraboost_dataframe(df_orig)
                state["df_orig"]    = df_orig
                state["df_kept"]    = kept
                state["df_removed"] = removed
                state["col_map"]    = cm
                state["filename"]   = uploaded.name
            except Exception as e:
                st.error(f"Error processing file: {e}")
                return

    if state["df_kept"] is None:
        st.info("Upload a CSV or Excel file to begin.")
        return

    df_orig    = state["df_orig"]
    df_kept    = state["df_kept"]
    df_removed = state["df_removed"]
    cm         = state["col_map"]

    # Stars cleaned count
    stars_fixed = 0
    if cm.get("google_stars"):
        orig_stars  = df_orig[cm["google_stars"]].fillna("")
        clean_stars = df_kept[cm["google_stars"]].fillna("") if cm["google_stars"] in df_kept.columns else orig_stars
        stars_fixed = int((orig_stars[:len(clean_stars)] != clean_stars).sum())

    render_stat_cards([
        {"label": "Total Rows",    "value": f"{len(df_orig):,}"},
        {"label": "Kept",          "value": f"{len(df_kept):,}"},
        {"label": "Removed",       "value": f"{len(df_removed):,}"},
        {"label": "Stars Cleaned", "value": stars_fixed},
    ])

    kept_tab, removed_tab = st.tabs(["Kept", "Removed"])

    with kept_tab:
        st.caption(f"{len(df_kept):,} rows kept")
        st.dataframe(df_kept, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("**Export**")
        platform = st.selectbox("Platform", EXPORT_PLATFORMS, key="tb_platform")

        col1, col2 = st.columns(2)
        with col1:
            render_export_button(
                df_kept,
                label=f"Download Kept — {platform}",
                file_name=f"terraboost_kept_{platform.lower().replace(' ','_')}.csv",
                key="tb_dl",
            )
        with col2:
            if st.button("Archive to Supabase", key="tb_archive"):
                if not is_configured():
                    st.warning("Supabase not configured — skipping archive.")
                else:
                    fname = state.get("filename", "unknown")
                    added, skipped = append_to_archive(df_kept, "Terraboost", fname)
                    ec = _find_email_col(df_kept)
                    if ec:
                        record_export(df_kept[ec].dropna().tolist(), platform, fname)
                    st.success(f"Archived: {added} added, {skipped} skipped.")

    with removed_tab:
        st.caption(f"{len(df_removed):,} rows removed")
        if df_removed.empty:
            st.info("No rows removed.")
        else:
            st.dataframe(df_removed, use_container_width=True, hide_index=True)
            render_export_button(
                df_removed,
                label="Download Removed",
                file_name="terraboost_removed.csv",
                key="tb_dl_removed",
            )
