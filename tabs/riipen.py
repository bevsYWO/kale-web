"""
tabs/riipen.py — Riipen data cleaner tab.
"""

import io
import os

import pandas as pd
import streamlit as st

from core.cleaner import (
    clean_dataframe,
    compute_diff,
    build_summary,
    build_hotspots,
    filter_dataframe,
    drop_validation_columns,
    flag_suspicious,
)
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
        raw = uploaded.read()
        for enc in ('utf-8-sig', 'utf-8', 'cp1252', 'latin-1'):
            try:
                return pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False, encoding=enc)
            except (UnicodeDecodeError, pd.errors.ParserError):
                continue
        return pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False, encoding='latin-1', errors='replace')
    return pd.read_excel(uploaded, dtype=str, keep_default_na=False)


def _email_col(df: pd.DataFrame):
    import re
    for col in df.columns:
        if re.search(r'^email$|^email[\s_]?address$', col, re.IGNORECASE):
            return col
    return None


def _first_name_col(df: pd.DataFrame):
    import re
    for col in df.columns:
        if re.search(r'^first.?name$', col, re.IGNORECASE):
            return col
    return None


def render():
    state = st.session_state.setdefault("riipen", {
        "df_orig":     None,
        "df_filtered": None,
        "df_clean":    None,
        "df_removed":  None,
        "df_flagged":  None,
        "changes":     [],
        "filename":    None,
        "fn_mode_used": "clean",
    })

    st.subheader("Riipen Data Cleaner")
    st.caption("Fixes encoding, names, company slash variants, and city subject-line values.")

    with st.expander("How to use this tab"):
        st.markdown("""
**What it does**
Cleans contact data exported from Clay before it goes into email campaigns.

**Processing order**
1. **Filter rows** — removes leads with blocked mx_records/domain keywords, non-Canadian schools, US regions, and US cities (confirmed by region)
2. **Drop validation columns** — removes email-validation metadata columns
3. **Clean cells** — fixes encoding, names, company names, subject line city, first lines
4. **Flag for review** — marks suspicious company names and unrecognized first lines

**How to use it**
1. Choose a First Name mode, then upload your CSV or Excel file.
2. Review what was removed in **Removed Rows** and what was flagged in **Flagged**.
3. Check the **Review & Edit** tab — the *In Clients* column shows prior exposure.
4. Select a platform and filter, then download.

**What it fixes**
- Garbled characters (MontrÃ©al → Montreal), Excel errors, emojis, HTML entities
- First names: encoding fixes, placeholder removal, slash-merged names
- First Name AI Ark: strips quoted nicknames (Ryan "Skip" → Ryan)
- Subject line city: strips addresses, postal codes, metro area labels
- Company names: slash variants, SENCRL abbreviations, stock tickers, trailing dots
- First lines: double slashes, stray special chars, double periods, missing trailing period

**Duplicate detection**
Each contact is checked against the master archive. The *In Clients* column shows prior exposure.
Use the **Filter** dropdown to export New only or Dupes only.
        """)

    # ── First Name mode ───────────────────────────────────────────────────────
    fn_mode_label = st.radio(
        "First Name treatment",
        options=["Clean only", "Replace all with 'there'"],
        index=0,
        horizontal=True,
        key="riipen_fn_mode",
        help=(
            "**Clean only** — fixes garbled characters and obvious placeholders, keeps real names.  \n"
            "**Replace all with 'there'** — sets every First Name to *there* regardless of content. "
            "First Name AI Ark is always cleaned regardless of this setting."
        ),
    )
    first_name_mode = 'there' if "Replace all" in fn_mode_label else 'clean'

    # ── File upload ──────────────────────────────────────────────────────────
    uploaded = st.file_uploader(
        "Upload CSV or Excel", type=["csv", "xlsx", "xls"], key="riipen_upload"
    )

    if uploaded and uploaded.name != state.get("filename"):
        with st.spinner("Filtering and cleaning..."):
            try:
                df_orig = _load_file(uploaded)

                # Steps 1–3, 7–9: filter rows
                df_filtered, df_removed = filter_dataframe(df_orig)

                # Step 4: drop validation columns
                df_filtered = drop_validation_columns(df_filtered)

                # Steps 5–13: clean cells
                df_clean = clean_dataframe(df_filtered, first_name_mode=first_name_mode)

                # Step 14: flag suspicious rows
                df_with_flags = flag_suspicious(df_clean)
                df_flagged = df_with_flags[df_with_flags['_review_flag'] != ''].copy()

                # Diff against filtered (not orig) so column counts match
                changes = compute_diff(df_filtered, df_clean)

                state.update({
                    "df_orig":      df_orig,
                    "df_filtered":  df_filtered,
                    "df_clean":     df_clean,
                    "df_removed":   df_removed,
                    "df_flagged":   df_flagged,
                    "changes":      changes,
                    "filename":     uploaded.name,
                    "fn_mode_used": first_name_mode,
                    "dupe_map":     {},
                })
            except Exception as e:
                st.error(f"Error processing file: {e}")
                return

        if is_configured():
            with st.spinner("Checking archive..."):
                try:
                    ec_tmp = _email_col(state["df_clean"])
                    if ec_tmp:
                        state["dupe_map"] = check_dupes(
                            state["df_clean"][ec_tmp].tolist(), "Riipen"
                        )
                    user = st.session_state.get("user_name", "")
                    src  = f"{uploaded.name} ({user})" if user else uploaded.name
                    added, _ = append_to_archive(state["df_clean"], "Riipen", src)
                    st.info(f"Archive: {added} emails saved.")
                except Exception as e:
                    st.warning(f"Archive write failed: {e}")

    if state["df_clean"] is None:
        st.info("Upload a CSV or Excel file to begin cleaning.")
        return

    df_orig     = state["df_orig"]
    df_filtered = state["df_filtered"]
    df_clean    = state["df_clean"]
    df_removed  = state["df_removed"] if state["df_removed"] is not None else pd.DataFrame()
    df_flagged  = state["df_flagged"] if state["df_flagged"] is not None else pd.DataFrame()
    changes     = state["changes"]

    ec    = _email_col(df_clean)
    dupes = len(state.get("dupe_map") or {})

    input_rows   = len(df_orig)
    removed_rows = len(df_removed)
    output_rows  = len(df_clean)

    render_stat_cards([
        {"label": "Input Rows",       "value": f"{input_rows:,}"},
        {"label": "Rows Removed",     "value": f"{removed_rows:,}"},
        {"label": "Output Rows",      "value": f"{output_rows:,}"},
        {"label": "New Leads",        "value": f"{output_rows - dupes:,}"},
        {"label": "Dupes in Archive", "value": dupes},
        {"label": "Cells Changed",    "value": f"{len(changes):,}"},
    ])

    if output_rows > 0 and dupes / output_rows > 0.5:
        st.warning(
            f"⚠️ **{dupes:,} of {output_rows:,} leads ({dupes/output_rows:.0%}) are already in the archive.** "
            "Consider using the **New only** filter before exporting."
        )

    tab_labels = ["Summary", "All Changes", "Review & Edit", "Hotspots", "Removed Rows", "Flagged"]
    tabs = st.tabs(tab_labels)

    # ── Summary ───────────────────────────────────────────────────────────────
    with tabs[0]:
        by_col, by_type = build_summary(changes, output_rows)

        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Changes by Column**")
            if by_col:
                col_df = pd.DataFrame(
                    sorted(by_col.items(), key=lambda x: -x[1]),
                    columns=["Column", "Count"],
                )
                st.dataframe(col_df, use_container_width=True, hide_index=True)
            else:
                st.info("No changes.")

        with col_b:
            st.markdown("**Changes by Type**")
            if by_type:
                type_df = pd.DataFrame(
                    sorted(by_type.items(), key=lambda x: -x[1]),
                    columns=["Change Type", "Count"],
                )
                st.dataframe(type_df, use_container_width=True, hide_index=True)
            else:
                st.info("No changes.")

    # ── All Changes ───────────────────────────────────────────────────────────
    with tabs[1]:
        search = st.text_input(
            "Search changes",
            placeholder="Filter by column, before, or after...",
            key="riipen_search",
        )
        render_diff_table(changes, search=search)

    # ── Review & Edit ─────────────────────────────────────────────────────────
    with tabs[2]:
        display_df = df_clean.copy()

        # Apply current fn_mode display (mode may have changed since upload)
        fn_col = _first_name_col(display_df)
        current_mode = 'there' if "Replace all" in st.session_state.get("riipen_fn_mode", "") else 'clean'
        if fn_col and current_mode == 'there' and state.get("fn_mode_used") == 'clean':
            display_df[fn_col] = 'there'

        if is_configured() and ec:
            emails = display_df[ec].tolist()
            dupe_map     = state.get("dupe_map") or {}
            platform_map = get_platforms_for_emails(emails)
            display_df["In Clients"] = display_df[ec].map(
                lambda e: ", ".join(dupe_map.get(e.lower(), [])) or "-"
            )
            display_df["Exported To"] = display_df[ec].map(
                lambda e: ", ".join(platform_map.get(e.lower(), [])) or "-"
            )

        edited = st.data_editor(
            display_df,
            use_container_width=True,
            num_rows="fixed",
            key="riipen_editor",
        )
        if st.button("Save edits", key="riipen_save_edits"):
            core_cols = [c for c in edited.columns if c not in ("In Clients", "Exported To")]
            state["df_clean"] = edited[core_cols].copy()
            st.success("Edits saved.")

        st.divider()
        st.markdown("**Export**")

        # First name override at export time
        export_fn_label = st.radio(
            "First Name in exported file",
            options=["Clean only", "Replace all with 'there'"],
            index=0 if state.get("fn_mode_used") == 'clean' else 1,
            horizontal=True,
            key="riipen_export_fn_mode",
            help="Override what goes in the downloaded file. Does not affect the preview above.",
        )
        export_fn_mode = 'there' if "Replace all" in export_fn_label else 'clean'

        if export_fn_mode == 'clean' and state.get("fn_mode_used") == 'there':
            st.caption("First names were replaced with 'there' during processing and cannot be recovered.")

        platform   = st.selectbox("Platform", EXPORT_PLATFORMS, key="riipen_platform")
        filter_opt = st.selectbox("Filter", FILTER_OPTIONS, key="riipen_filter")

        export_df = state["df_clean"].copy()
        if ec and filter_opt != "All":
            dupe_map = state.get("dupe_map") or {}
            seen_set = set(dupe_map.keys())
            if filter_opt == "New only":
                export_df = export_df[~export_df[ec].str.lower().isin(seen_set)]
            elif filter_opt == "Dupes only":
                export_df = export_df[export_df[ec].str.lower().isin(seen_set)]

        # Apply export-time first name mode
        export_fn_col = _first_name_col(export_df)
        if export_fn_col:
            if export_fn_mode == 'there':
                export_df = export_df.copy()
                export_df[export_fn_col] = 'there'

        st.caption(f"{len(export_df):,} rows ready for export")

        orig_base = os.path.splitext(state.get("filename", "riipen"))[0]
        clicked = render_export_button(
            export_df,
            label=f"Download for {platform}",
            file_name=build_filename(orig_base, platform, filter_label=filter_opt if ec else ""),
            key="riipen_dl",
        )
        if clicked and is_configured() and ec:
            record_export(export_df[ec].dropna().tolist(), platform, state.get("filename", "unknown"))

    # ── Hotspots ──────────────────────────────────────────────────────────────
    with tabs[3]:
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

    # ── Removed Rows ──────────────────────────────────────────────────────────
    with tabs[4]:
        if df_removed.empty:
            st.info("No rows were removed.")
        else:
            reason_counts = df_removed["_removed_reason"].value_counts().reset_index()
            reason_counts.columns = ["Reason", "Count"]

            st.markdown(f"**{len(df_removed):,} rows removed** across {len(reason_counts)} rule(s)")
            st.dataframe(reason_counts, use_container_width=True, hide_index=True)
            st.divider()
            st.markdown("**Removed rows**")
            st.dataframe(df_removed, use_container_width=True, hide_index=True)

    # ── Flagged ───────────────────────────────────────────────────────────────
    with tabs[5]:
        if df_flagged.empty:
            st.info("No rows flagged for review.")
        else:
            flag_counts = df_flagged["_review_flag"].value_counts().reset_index()
            flag_counts.columns = ["Flag reason", "Count"]

            st.markdown(f"**{len(df_flagged):,} rows flagged** for manual review")
            st.dataframe(flag_counts, use_container_width=True, hide_index=True)
            st.divider()
            st.markdown("**Flagged rows** — review before sending")
            st.dataframe(df_flagged, use_container_width=True, hide_index=True)
