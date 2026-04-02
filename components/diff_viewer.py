"""
components/diff_viewer.py — Before/After diff display using st.dataframe.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st


def render_diff_table(changes: list, search: str = "") -> None:
    """
    Display a searchable before-after diff table.

    changes: list of (row_num, col, before, after, change_type)
    search : optional filter string (matches col, before, or after)
    """
    if not changes:
        st.info("No changes detected — the file is already clean.")
        return

    df = pd.DataFrame(changes, columns=["Row", "Column", "Before", "After", "Type"])

    if search:
        mask = (
            df["Column"].str.contains(search, case=False, na=False)
            | df["Before"].str.contains(search, case=False, na=False)
            | df["After"].str.contains(search, case=False, na=False)
        )
        df = df[mask]

    if df.empty:
        st.info("No changes match your search.")
        return

    st.dataframe(
        df,
        use_container_width=True,
        column_config={
            "Row":    st.column_config.NumberColumn("Row #", width="small"),
            "Column": st.column_config.TextColumn("Column"),
            "Before": st.column_config.TextColumn("Before", width="medium"),
            "After":  st.column_config.TextColumn("After",  width="medium"),
            "Type":   st.column_config.TextColumn("Change Type", width="medium"),
        },
        hide_index=True,
    )
    st.caption(f"{len(df):,} change(s) shown")
