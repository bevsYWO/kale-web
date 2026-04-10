"""
tabs/n2.py — N2 Tier Mapper tab.
"""

import random
import re

import pandas as pd
import streamlit as st

from core.tier_mapper import get_tier, TIER_MAP, BUSINESS_TYPE_EXCLUDE
from components.stat_cards import render_stat_cards
from components.export_button import render_export_button, build_filename
from db.archive import append_to_archive, check_dupes
from db.platform_history import get_platforms_for_emails, record_export
from db.client import is_configured

EXPORT_PLATFORMS = ["Instantly", "EmailBison", "Personal Bison"]
TIER_COLORS      = {"1": "#32704B", "2": "#5C8B67", "3": "#C7B39C",
                    "Do not email": "#A84F44", "Unknown": "#7A9180"}


def _load_file(uploaded) -> pd.DataFrame:
    name = uploaded.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded, dtype=str, keep_default_na=False)
    return pd.read_excel(uploaded, dtype=str, keep_default_na=False)


def _find_keyword_col(df: pd.DataFrame):
    # Prefer explicit keyword columns; avoid matching tier columns (e.g. "Tier Category")
    for col in df.columns:
        if re.search(r'keyword', col, re.IGNORECASE):
            return col
    for col in df.columns:
        if re.search(r'^business[\s_]?type$', col, re.IGNORECASE):
            return col
    return None


def _find_business_type_col(df: pd.DataFrame):
    """Find a dedicated Business Type column for exclusion filtering."""
    for col in df.columns:
        if re.search(r'^business[\s_]?type$', col, re.IGNORECASE):
            return col
    return None


def _find_email_col(df: pd.DataFrame):
    for col in df.columns:
        if re.search(r'^email$|^email[\s_]?address$', col, re.IGNORECASE):
            return col
    return None


def _find_neighborhood_col(df: pd.DataFrame):
    for col in df.columns:
        if re.search(r'neighborhood|neighbourhood|area|suburb', col, re.IGNORECASE):
            return col
    return None


def _find_tier_col(df: pd.DataFrame):
    for col in df.columns:
        if re.search(r'^tier$|^tier[\s_]?categor', col, re.IGNORECASE):
            return col
    return None


def _randomize_tiers(df: pd.DataFrame, tier_col: str) -> pd.DataFrame:
    """Interleave T1 -> T2 -> T3 rows so tiers are spread evenly."""
    t1 = df[df[tier_col] == "1"].copy()
    t2 = df[df[tier_col] == "2"].copy()
    t3 = df[df[tier_col] == "3"].copy()
    other = df[~df[tier_col].isin(["1", "2", "3"])].copy()

    random.shuffle(t1.values.tolist()) if len(t1) else None
    random.shuffle(t2.values.tolist()) if len(t2) else None
    random.shuffle(t3.values.tolist()) if len(t3) else None

    interleaved = []
    i1 = i2 = i3 = 0
    while i1 < len(t1) or i2 < len(t2) or i3 < len(t3):
        if i1 < len(t1):
            interleaved.append(t1.iloc[i1])
            i1 += 1
        if i2 < len(t2):
            interleaved.append(t2.iloc[i2])
            i2 += 1
        if i3 < len(t3):
            interleaved.append(t3.iloc[i3])
            i3 += 1

    if interleaved:
        return pd.concat([pd.DataFrame(interleaved), other], ignore_index=True)
    return df


def render():
    state = st.session_state.setdefault("n2", {
        "df_orig":    None,
        "df_tiered":  None,
        "df_removed": None,
        "filename":   None,
        "tier_col":   None,
    })

    st.subheader("N2 Tier Mapper")
    st.caption("Assigns Tier 1 / 2 / 3 / Do not email based on business type keyword.")

    with st.expander("How to use this tab"):
        st.markdown("""
**What it does**
Reads N2 lead lists and assigns each lead a Tier 1, 2, or 3 based on their business type — so the outreach team knows who to contact first.

**How to use it**
1. Upload your leads file.
2. The tool assigns tiers automatically. Tier 1 = highest priority.
3. If the file already has a Tier column, choose to keep it or re-map from keyword.
4. Optionally filter by neighborhood and use **Randomize** to interleave T1→T2→T3 for balanced outreach.
5. Select a platform and download.

**Tiers**
- **Tier 1** — Best converters (HVAC, plumbers, roofers, dentists)
- **Tier 2** — Good fit (auto repair, hair salons, lawyers, gyms)
- **Tier 3** — Lower priority (restaurants, barbers, gift shops)
- **Do not email** — Skipped entirely (churches, non-profits, agencies)
- **Unknown** — Business type not in the tier map; always removed from export

Both *Do not email* and *Unknown* rows are filtered out and never exported — they appear in the **Removed** tab.
        """)

    uploaded = st.file_uploader(
        "Upload CSV or Excel", type=["csv", "xlsx", "xls"], key="n2_upload"
    )

    if uploaded and uploaded.name != state.get("filename"):
        with st.spinner("Loading file..."):
            try:
                df = _load_file(uploaded)
                state["df_orig"]   = df
                state["df_tiered"] = None
                state["filename"]  = uploaded.name
            except Exception as e:
                st.error(f"Error loading file: {e}")
                return

    if state["df_orig"] is None:
        st.info("Upload a CSV or Excel file to begin.")
        return

    df_orig      = state["df_orig"]
    keyword_col  = _find_keyword_col(df_orig)
    existing_tier_col = _find_tier_col(df_orig)

    # ── Tier mapping options ─────────────────────────────────────────────────
    remap_mode = "Re-map"
    if existing_tier_col:
        st.info(f"File already has a **{existing_tier_col}** column.")
        remap_mode = st.radio(
            "Tier column action",
            ["Use Existing", "Re-map"],
            horizontal=True,
            key="n2_remap_mode",
        )

    if keyword_col:
        st.caption(f"Keyword column detected: **{keyword_col}**")
    else:
        keyword_col = st.selectbox(
            "Select the keyword / business type column",
            df_orig.columns.tolist(),
            key="n2_kw_col",
        )

    if st.button("Apply Tier Map", key="n2_apply"):
        with st.spinner("Mapping tiers..."):
            df = df_orig.copy()

            if existing_tier_col and remap_mode == "Use Existing":
                tier_col = existing_tier_col
            else:
                tier_col = "Tier"
                if keyword_col:
                    df[tier_col] = df[keyword_col].apply(get_tier)
                else:
                    df[tier_col] = "Unknown"

            # Split kept / removed
            removed_mask = df[tier_col].str.strip().str.lower().isin(
                ["do not email", "unknown"]
            )
            exclude_mask = pd.Series([False] * len(df), index=df.index)
            for _excol in [keyword_col, _find_business_type_col(df)]:
                if _excol and _excol in df.columns:
                    _kw = df[_excol].fillna("").str.lower()
                    exclude_mask |= _kw.apply(
                        lambda v: any(ex in v for ex in BUSINESS_TYPE_EXCLUDE)
                    )

            full_remove = removed_mask | exclude_mask
            df_kept    = df[~full_remove].copy()
            df_removed = df[full_remove].copy()

            # Add removal reason column
            def _reason(idx):
                if exclude_mask.get(idx, False):
                    return f"Excluded business type"
                return df.at[idx, tier_col]
            df_removed.insert(0, "Removal Reason", df_removed.index.map(_reason))

            state["df_tiered"]  = df_kept
            state["df_removed"] = df_removed
            state["tier_col"]   = tier_col
            if is_configured():
                ec_auto = _find_email_col(df_kept)
                if ec_auto:
                    state["dupe_map"] = check_dupes(df_kept[ec_auto].tolist(), "N2")
                try:
                    user = st.session_state.get("user_name", "")
                    src  = f"{state.get('filename', 'unknown')} ({user})" if user else state.get("filename", "unknown")
                    added, _ = append_to_archive(df_kept, "N2", src)
                    st.info(f"Archive: {added} emails saved.")
                except Exception as e:
                    st.warning(f"Archive write failed: {e}")
                if ec_auto:
                    record_export(df_kept[ec_auto].dropna().tolist(), "N2", state.get("filename", "unknown"))

    if state["df_tiered"] is None:
        return

    df_kept    = state["df_tiered"]
    df_removed = state["df_removed"]
    tier_col   = state["tier_col"]

    # ── Stat bar ─────────────────────────────────────────────────────────────
    t1 = int((df_kept[tier_col] == "1").sum())
    t2 = int((df_kept[tier_col] == "2").sum())
    t3 = int((df_kept[tier_col] == "3").sum())
    unk = int((df_kept[tier_col] == "Unknown").sum())

    ec    = _find_email_col(df_kept)
    dupes = len(state.get("dupe_map") or {})

    render_stat_cards([
        {"label": "Tier 1", "value": t1},
        {"label": "Tier 2", "value": t2},
        {"label": "Tier 3", "value": t3},
        {"label": "Unknown", "value": unk},
        {"label": "Do Not Email", "value": len(df_removed)},
        {"label": "Dupes in Archive", "value": dupes},
        {"label": "New Leads", "value": len(df_kept) - dupes},
    ])

    _total_kept = len(df_kept)
    if _total_kept > 0 and dupes / _total_kept > 0.5:
        st.warning(
            f"⚠️ **{dupes:,} of {_total_kept:,} leads ({dupes/_total_kept:.0%}) are already in the archive.** "
            "These contacts have been seen before — review before sending."
        )

    # ── Neighborhood filter ───────────────────────────────────────────────────
    nb_col = _find_neighborhood_col(df_kept)
    display_df = df_kept.copy()
    if nb_col:
        neighborhoods = sorted(df_kept[nb_col].dropna().unique().tolist())
        selected_nb   = st.multiselect(
            "Filter by Neighborhood", neighborhoods, key="n2_nb_filter"
        )
        if selected_nb:
            display_df = display_df[display_df[nb_col].isin(selected_nb)]

    # ── Randomize ─────────────────────────────────────────────────────────────
    if st.button("Randomize (interleave T1/T2/T3)", key="n2_randomize"):
        display_df = _randomize_tiers(display_df, tier_col)
        state["df_tiered"] = display_df

    # ── Kept / Removed tabs ──────────────────────────────────────────────────
    kept_tab, removed_tab = st.tabs(["Kept", "Removed"])

    with kept_tab:
        st.caption(f"{len(display_df):,} rows kept")
        st.dataframe(display_df, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("**Export Kept**")
        platform = st.selectbox("Platform", EXPORT_PLATFORMS, key="n2_platform")

        available_tiers = sorted(display_df[tier_col].dropna().unique().tolist())
        default_tiers   = [t for t in available_tiers if t in ("1", "2", "3")]
        selected_tiers  = st.multiselect(
            "Export tiers", available_tiers, default=default_tiers, key="n2_tier_export_filter"
        )
        filter_opt = st.selectbox(
            "Filter", ["All", "New only", "Dupes only"], key="n2_lead_filter"
        )

        export_df = display_df[display_df[tier_col].isin(selected_tiers)] if selected_tiers else display_df
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
            label=f"Download for {platform}",
            file_name=build_filename("n2_tiered", platform),
            key="n2_dl",
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
                file_name="n2_removed.csv",
                key="n2_dl_removed",
            )
