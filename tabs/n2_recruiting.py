"""
tabs/n2_recruiting.py — N2 Recruiting data cleaner tab.
"""

import os

import pandas as pd
import streamlit as st

from core.recruiting_cleaner import clean_recruiting_dataframe, N2R_EXPORT_RENAME
from core.cleaner import compute_diff, build_summary, build_hotspots
from components.stat_cards import render_stat_cards
from components.diff_viewer import render_diff_table
from components.export_button import render_export_button, build_filename
from db.archive import append_to_archive, check_dupes
from db.platform_history import get_platforms_for_emails, record_export
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

    with st.expander("How to use this tab"):
        st.markdown("""
**What it does**
Cleans N2 Recruiting contact exports — fixes encoding issues, garbled first lines, and invalid city values.

**How to use it**
1. Upload your CSV or Excel file.
2. The tool cleans it automatically — review results in the tabs below.
3. In **Review & Edit**, check the *In Clients* column to see if a contact has been seen before.
4. Select a platform and download.

**What it fixes**
- Garbled characters and mojibake (common in First Line values)
- Invalid city values — inferred from address or zip code if city is blank/invalid
- Encoding issues across all columns
- First names with ~~ prefixes (~~Kumer → Kumer)
- Placeholder first names (N/A, unknown, etc. → *there*)

**Duplicate detection**
Each contact is automatically checked against the master archive. The *In Clients* column shows where an email has been seen before.
        """)

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
        if is_configured():
            with st.spinner("Checking archive..."):
                try:
                    ec_tmp = _find_email_col(state["df_clean"])
                    if ec_tmp:
                        state["dupe_map"] = check_dupes(state["df_clean"][ec_tmp].tolist(), "N2 Recruiting")
                    user = st.session_state.get("user_name", "")
                    src  = f"{uploaded.name} ({user})" if user else uploaded.name
                    added, skipped = append_to_archive(state["df_clean"], "N2 Recruiting", src)
                    st.info(f"Archive: {added} rows written, {skipped} skipped.")
                except Exception as e:
                    st.warning(f"Archive write failed: {e}")

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

    ec    = _find_email_col(df_clean)
    dupes = len(state.get("dupe_map") or {})

    render_stat_cards([
        {"label": "Total Rows",       "value": f"{total_rows:,}"},
        {"label": "New Leads",        "value": f"{total_rows - dupes:,}"},
        {"label": "Dupes in Archive", "value": dupes},
        {"label": "Cells Changed",    "value": f"{cells_changed:,}"},
    ])

    if total_rows > 0 and dupes / total_rows > 0.5:
        st.warning(
            f"⚠️ **{dupes:,} of {total_rows:,} leads ({dupes/total_rows:.0%}) are already in the archive.** "
            "Consider reviewing before exporting."
        )

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
            dupe_map     = state.get("dupe_map") or {}
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

        platform   = st.selectbox("Platform", EXPORT_PLATFORMS, key="n2r_platform")
        filter_opt = st.selectbox("Filter", FILTER_OPTIONS, key="n2r_filter")

        export_df = state["df_clean"].copy()
        ec_export = _find_email_col(export_df)
        if ec_export and filter_opt != "All":
            dupe_map = state.get("dupe_map") or {}
            seen_set = set(dupe_map.keys())
            if filter_opt == "New only":
                export_df = export_df[~export_df[ec_export].str.lower().isin(seen_set)]
            elif filter_opt == "Dupes only":
                export_df = export_df[export_df[ec_export].str.lower().isin(seen_set)]

        st.caption(f"{len(export_df):,} rows ready for export")

        orig_base = os.path.splitext(state.get("filename", "n2_recruiting"))[0]
        clicked = render_export_button(
            export_df,
            label=f"Download for {platform}",
            file_name=build_filename(orig_base, platform, filter_label=filter_opt),
            key="n2r_dl",
        )
        if clicked and is_configured() and ec_export:
            record_export(export_df[ec_export].dropna().tolist(), platform, state.get("filename", "unknown"))

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
