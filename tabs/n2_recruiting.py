"""
tabs/n2_recruiting.py — N2 Recruiting data cleaner tab.
"""

import pandas as pd
import streamlit as st

from core.recruiting_cleaner import clean_recruiting_dataframe, N2R_EXPORT_RENAME
from core.cleaner import compute_diff, build_summary, build_hotspots
from components.stat_cards import render_stat_cards
from components.diff_viewer import render_diff_table
from components.export_button import render_export_button
from db.archive import append_to_archive, check_dupes
from db.platform_history import get_platforms_for_emails, record_export
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
    state = st.session_state.setdefault("n2_recruiting", {
        "df_orig":  None,
        "df_clean": None,
        "col_map":  {},
        "changes":  [],
        "filename": None,
    })

    st.subheader("N2 Recruiting Cleaner")
    st.caption(
        "Fixes first names, first-line (company) values, and city fields "
        "for N2 Recruiting campaign imports."
    )

    uploaded = st.file_uploader(
        "Upload CSV or Excel", type=["csv", "xlsx", "xls"], key="n2r_upload"
    )

    if uploaded and uploaded.name != state.get("filename"):
        with st.spinner("Cleaning..."):
            try:
                df_orig          = _load_file(uploaded)
                df_clean, col_map = clean_recruiting_dataframe(df_orig)
                changes          = compute_diff(df_orig, df_clean)
                state["df_orig"]  = df_orig
                state["df_clean"] = df_clean
                state["col_map"]  = col_map
                state["changes"]  = changes
                state["filename"] = uploaded.name
            except Exception as e:
                st.error(f"Error processing file: {e}")
                return

    if state["df_clean"] is None:
        st.info("Upload a CSV or Excel file to begin cleaning.")
        return

    df_orig  = state["df_orig"]
    df_clean = state["df_clean"]
    changes  = state["changes"]

    total_rows    = len(df_orig)
    cells_changed = len(changes)
    cols_affected = len(set(c[1] for c in changes))
    pct_affected  = round(cells_changed / max(total_rows, 1) * 100, 1)

    render_stat_cards([
        {"label": "Total Rows",       "value": f"{total_rows:,}"},
        {"label": "Cells Changed",    "value": f"{cells_changed:,}"},
        {"label": "% Rows Affected",  "value": f"{pct_affected}%"},
        {"label": "Columns Affected", "value": cols_affected},
    ])

    inner_tab1, inner_tab2, inner_tab3, inner_tab4 = st.tabs(
        ["Summary", "All Changes", "Review & Edit", "Hotspots"]
    )

    # ── Summary ──────────────────────────────────────────────────────────────
    with inner_tab1:
        by_col, by_type = build_summary(changes, total_rows)
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Changes by Column**")
            if by_col:
                st.dataframe(
                    pd.DataFrame(sorted(by_col.items(), key=lambda x: -x[1]),
                                 columns=["Column", "Count"]),
                    use_container_width=True, hide_index=True,
                )
            else:
                st.info("No changes.")
        with col_b:
            st.markdown("**Changes by Type**")
            if by_type:
                st.dataframe(
                    pd.DataFrame(sorted(by_type.items(), key=lambda x: -x[1]),
                                 columns=["Change Type", "Count"]),
                    use_container_width=True, hide_index=True,
                )
            else:
                st.info("No changes.")

    # ── All Changes ──────────────────────────────────────────────────────────
    with inner_tab2:
        search = st.text_input(
            "Search changes", placeholder="Filter by column, before, or after...",
            key="n2r_search"
        )
        render_diff_table(changes, search=search)

    # ── Review & Edit ────────────────────────────────────────────────────────
    with inner_tab3:
        ec = _find_email_col(df_clean)
        display_df = df_clean.copy()

        if is_configured() and ec:
            emails       = display_df[ec].tolist()
            dupe_map     = check_dupes(emails, "N2 Recruiting")
            platform_map = get_platforms_for_emails(emails)
            display_df["In Clients"]  = display_df[ec].map(
                lambda e: ", ".join(dupe_map.get(e.lower(), [])) or "-"
            )
            display_df["Exported To"] = display_df[ec].map(
                lambda e: ", ".join(platform_map.get(e.lower(), [])) or "-"
            )

        edited = st.data_editor(
            display_df,
            use_container_width=True,
            num_rows="fixed",
            key="n2r_editor",
        )
        if st.button("Save edits", key="n2r_save_edits"):
            core_cols = [c for c in edited.columns if c not in ("In Clients", "Exported To")]
            state["df_clean"] = edited[core_cols].copy()
            st.success("Edits saved.")

        st.divider()
        st.markdown("**Export**")
        platform = st.selectbox("Platform", EXPORT_PLATFORMS, key="n2r_platform")

        col1, col2 = st.columns(2)
        with col1:
            render_export_button(
                state["df_clean"],
                label=f"Download for {platform}",
                file_name=f"n2_recruiting_{platform.lower().replace(' ','_')}.csv",
                key="n2r_dl",
            )
        with col2:
            if st.button("Archive to Supabase", key="n2r_archive"):
                if not is_configured():
                    st.warning("Supabase not configured — skipping archive.")
                else:
                    fname = state.get("filename", "unknown")
                    added, skipped = append_to_archive(
                        state["df_clean"], "N2 Recruiting", fname
                    )
                    if ec:
                        emails = state["df_clean"][ec].dropna().tolist()
                        record_export(emails, platform, fname)
                    st.success(f"Archived: {added} added, {skipped} skipped.")

    # ── Hotspots ──────────────────────────────────────────────────────────────
    with inner_tab4:
        hotspots = build_hotspots(changes)
        if not hotspots:
            st.info("No hotspot rows.")
        else:
            hs_rows = []
            for row_num, data in hotspots[:50]:
                hs_rows.append({
                    "Row #":   row_num,
                    "Changes": data["count"],
                    "Columns": ", ".join(sorted(data["cols"])),
                    "Types":   ", ".join(sorted(data["types"])),
                })
            st.dataframe(pd.DataFrame(hs_rows), use_container_width=True, hide_index=True)
