"""
tabs/general.py — General-purpose cleaner tab.
"""

import pandas as pd
import streamlit as st

from core.general_cleaner import (
    clean_general_dataframe,
    ACTIONS,
    ACTIONS_NO_VALUE,
    ACTION_DESCRIPTIONS,
    _parse_quick_instructions,
)
from core.cleaner import compute_diff, build_summary
from components.stat_cards import render_stat_cards
from components.diff_viewer import render_diff_table
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


def _init_state():
    return st.session_state.setdefault("general", {
        "df_orig":    None,
        "df_kept":    None,
        "df_removed": None,
        "df_clean":   None,  # df_orig after universal clean (before rules)
        "changes":    [],
        "filename":   None,
        "rules":      [],    # list of {column, action, value}
        "headers":    [],
    })


def _rule_editor(headers: list) -> list:
    """Render a dynamic rule editor. Returns current list of rules."""
    state = st.session_state["general"]
    rules = state.get("rules", [])

    st.markdown("**Per-column rules**")

    # Quick instructions input
    with st.expander("Paste plain-English instructions (optional)"):
        instr_text = st.text_area(
            "One rule per line: `column name - instruction`",
            placeholder="City - no streets\nFirst Name - name clean\nRating - 1-5 only",
            key="general_instr",
            height=120,
        )
        if st.button("Parse instructions", key="general_parse"):
            parsed, warnings = _parse_quick_instructions(instr_text, headers)
            if warnings:
                for w in warnings:
                    st.warning(w)
            if parsed:
                rules = parsed
                state["rules"] = rules
                st.success(f"Parsed {len(parsed)} rule(s).")

    st.divider()
    st.caption("Or build rules manually:")

    if st.button("+ Add rule", key="general_add_rule"):
        rules.append({"column": headers[0] if headers else "", "action": ACTIONS[0], "value": ""})
        state["rules"] = rules

    to_delete = []
    for i, rule in enumerate(rules):
        cols = st.columns([3, 3, 3, 1])
        with cols[0]:
            rule["column"] = st.selectbox(
                "Column", headers, index=headers.index(rule["column"]) if rule["column"] in headers else 0,
                key=f"gen_col_{i}",
            )
        with cols[1]:
            rule["action"] = st.selectbox(
                "Action", ACTIONS, index=ACTIONS.index(rule["action"]) if rule["action"] in ACTIONS else 0,
                key=f"gen_act_{i}",
                help=ACTION_DESCRIPTIONS.get(rule["action"], ""),
            )
        with cols[2]:
            if rule["action"] not in ACTIONS_NO_VALUE:
                rule["value"] = st.text_input(
                    "Value", value=rule.get("value", ""), key=f"gen_val_{i}"
                )
            else:
                st.caption("(no value needed)")
        with cols[3]:
            if st.button("X", key=f"gen_del_{i}"):
                to_delete.append(i)

    for i in sorted(to_delete, reverse=True):
        rules.pop(i)
    state["rules"] = rules
    return rules


def render():
    state = _init_state()

    st.subheader("General Cleaner")
    st.caption(
        "Universal encoding fix on every cell, plus optional per-column rules "
        "(remove rows, replace values, case transforms, etc.)."
    )

    with st.expander("How to use this tab"):
        st.markdown("""
**What it does**
A universal cleaner for any CSV. Always fixes encoding issues on every cell. Optionally lets you add per-column rules for filtering, replacing, or transforming values.

**How to use it**
1. Upload your CSV or Excel file.
2. Optionally add per-column rules (or paste plain-English instructions).
3. Click **Clean**.
4. Review results in the Kept, Removed, and Diff View tabs.
5. Select a platform and download.

**Available rules**
- **Remove rows containing** — removes rows with certain keywords
- **Keep only rows containing** — keeps only rows with certain keywords
- **Replace value** — replaces an exact value with another (format: `old → new`)
- **Title Case / UPPERCASE / lowercase** — changes text case
- **Apply city clean** — fixes invalid city values
- **Apply name clean** — fixes placeholder first names
- **Remove row if blank** — removes empty rows
- **N/A → blank** — clears N/A, none, unknown, -- placeholders
- **Keep only numeric range** — keeps rows within a number range (e.g. 1–5)

**Tip:** Use the *Paste plain-English instructions* box to describe rules in plain text instead of building them manually. Example: `City - no streets` or `Rating - 1-5 only`.
        """)

    uploaded = st.file_uploader(
        "Upload CSV or Excel", type=["csv", "xlsx", "xls"], key="general_upload"
    )

    if uploaded and uploaded.name != state.get("filename"):
        with st.spinner("Loading file..."):
            try:
                df = _load_file(uploaded)
                state["df_orig"]  = df
                state["df_kept"]  = None
                state["filename"] = uploaded.name
                state["headers"]  = df.columns.tolist()
                state["rules"]    = []
            except Exception as e:
                st.error(f"Error loading file: {e}")
                return

    if state["df_orig"] is None:
        st.info("Upload a CSV or Excel file to begin.")
        return

    headers = state["headers"]
    rules   = _rule_editor(headers)

    if st.button("Clean", type="primary", key="general_clean"):
        with st.spinner("Cleaning..."):
            try:
                kept, removed = clean_general_dataframe(state["df_orig"], rules)
                changes       = compute_diff(state["df_orig"], kept)
                state["df_kept"]    = kept
                state["df_removed"] = removed
                state["changes"]    = changes
                if is_configured():
                    ec_tmp = _find_email_col(kept)
                    if ec_tmp:
                        state["dupe_map"] = check_dupes(kept[ec_tmp].tolist(), "General")
                    user = st.session_state.get("user_name", "")
                    src  = f"{state.get('filename', 'unknown')} ({user})" if user else state.get("filename", "unknown")
                    added, _ = append_to_archive(kept, "General", src)
                    st.info(f"Archive: {added} emails saved.")
            except Exception as e:
                st.error(f"Error during cleaning: {e}")
                return

    if state.get("df_kept") is None:
        return

    df_kept    = state["df_kept"]
    df_removed = state["df_removed"]
    changes    = state["changes"]

    ec    = _find_email_col(df_kept)
    dupes = len(state.get("dupe_map") or {})

    render_stat_cards([
        {"label": "Total Rows",        "value": f"{len(state['df_orig']):,}"},
        {"label": "Kept",              "value": f"{len(df_kept):,}"},
        {"label": "Removed",           "value": f"{len(df_removed):,}"},
        {"label": "New Leads",         "value": f"{len(df_kept) - dupes:,}"},
        {"label": "Dupes in Archive",  "value": dupes},
        {"label": "Cells Fixed",       "value": f"{len(changes):,}"},
    ])

    if len(df_kept) > 0 and dupes / len(df_kept) > 0.5:
        st.warning(
            f"⚠️ **{dupes:,} of {len(df_kept):,} kept leads ({dupes/len(df_kept):.0%}) are already in the archive.** "
            "Consider using the New only filter before exporting."
        )

    kept_tab, removed_tab, diff_tab = st.tabs(["Kept", "Removed", "Diff View"])

    with kept_tab:
        st.caption(f"{len(df_kept):,} rows")
        st.dataframe(df_kept, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("**Export**")
        platform   = st.selectbox("Platform", EXPORT_PLATFORMS, key="gen_platform")
        filter_opt = st.selectbox("Filter", FILTER_OPTIONS, key="gen_filter")

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
            file_name=build_filename("general_kept", platform),
            key="gen_dl",
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
                file_name="general_removed.csv",
                key="gen_dl_removed",
            )

    with diff_tab:
        search = st.text_input(
            "Search changes", placeholder="Filter by column, before, or after...",
            key="gen_search"
        )
        render_diff_table(changes, search=search)
