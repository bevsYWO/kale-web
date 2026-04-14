"""
tabs/terraboost.py — Terraboost data cleaner tab.
"""

import pandas as pd
import streamlit as st

from core.terraboost_cleaner import clean_terraboost_dataframe, TB_EXPORT_RENAME
from components.stat_cards import render_stat_cards
from components.export_button import render_export_button, build_filename
from db.archive import append_to_archive, check_dupes
from db.platform_history import record_export
from db.client import is_configured

EXPORT_PLATFORMS = ["Instantly", "EmailBison", "Personal Bison"]
FILTER_OPTIONS   = ["All", "New only", "Dupes only"]


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

    with st.expander("How to use this tab"):
        st.markdown("""
**What it does**
Cleans Terraboost grocery store contact data — validates store names, cleans star ratings, and removes rows with missing business categories.

**How to use it**
1. Upload your CSV or Excel file.
2. The tool cleans it automatically — review kept and removed rows in the tabs below.
3. Select a platform and download.

**What it checks**
- **Store name** — must be a known chain (Harris Teeter, HEB, Kroger, Jewel, Albertsons). Invalid names are removed.
- **Google Stars** — cleaned and normalized in place (must be 1.0–5.0). No rows removed for this.
- **Business Category** — rows with blank or placeholder categories are removed.
- **Cleaned Company Name** — special characters and control characters are removed; extra whitespace is collapsed. Rows where the name is blank or garbled after cleaning are removed.

Removed rows are visible in the **Removed** tab and can be downloaded separately.
        """)

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
                if is_configured():
                    ec_tmp = _find_email_col(kept)
                    if ec_tmp:
                        state["dupe_map"] = check_dupes(kept[ec_tmp].tolist(), "Terraboost")
                    user = st.session_state.get("user_name", "")
                    src  = f"{uploaded.name} ({user})" if user else uploaded.name
                    added, _ = append_to_archive(kept, "Terraboost", src)
                    st.info(f"Archive: {added} emails saved.")
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

    ec    = _find_email_col(df_kept)
    dupes = len(state.get("dupe_map") or {})

    render_stat_cards([
        {"label": "Total Rows",       "value": f"{len(df_orig):,}"},
        {"label": "Kept",             "value": f"{len(df_kept):,}"},
        {"label": "Removed",          "value": f"{len(df_removed):,}"},
        {"label": "New Leads",        "value": f"{len(df_kept) - dupes:,}"},
        {"label": "Dupes in Archive", "value": dupes},
        {"label": "Stars Cleaned",    "value": stars_fixed},
    ])

    if len(df_kept) > 0 and dupes / len(df_kept) > 0.5:
        st.warning(
            f"⚠️ **{dupes:,} of {len(df_kept):,} kept leads ({dupes/len(df_kept):.0%}) are already in the archive.** "
            "Consider using the New only filter before exporting."
        )

    kept_tab, removed_tab = st.tabs(["Kept", "Removed"])

    with kept_tab:
        st.caption(f"{len(df_kept):,} rows kept")
        st.dataframe(df_kept, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("**Export**")
        platform   = st.selectbox("Platform", EXPORT_PLATFORMS, key="tb_platform")
        filter_opt = st.selectbox("Filter", FILTER_OPTIONS, key="tb_filter")

        export_df = df_kept.copy()
        if ec and filter_opt != "All":
            dupe_map = state.get("dupe_map") or {}
            seen_set = set(dupe_map.keys())
            if filter_opt == "New only":
                export_df = export_df[~export_df[ec].str.lower().isin(seen_set)]
            elif filter_opt == "Dupes only":
                export_df = export_df[export_df[ec].str.lower().isin(seen_set)]

        st.caption(f"{len(export_df):,} rows ready for export")

        clicked = render_export_button(
            export_df,
            label=f"Download Kept — {platform}",
            file_name=build_filename("terraboost_kept", platform),
            key="tb_dl",
        )
        if clicked and is_configured() and ec:
            record_export(export_df[ec].dropna().tolist(), platform, state.get("filename", "unknown"))

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
