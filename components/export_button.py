"""
components/export_button.py — CSV download button helper.
"""

from datetime import date as _date

import pandas as pd
import streamlit as st


def build_filename(base: str, platform: str = "", ext: str = "csv") -> str:
    """
    Build a download filename that includes the logged-in user's name and today's date.

    Example: build_filename("riipen_cleaned", "Instantly") → "riipen_cleaned_mike_2026-04-07_instantly.csv"
    """
    user  = st.session_state.get("user_name", "")
    today = _date.today().strftime("%Y-%m-%d")
    slug  = platform.lower().replace(" ", "_")
    parts = [p for p in [base, user, today, slug] if p]
    return "_".join(parts) + f".{ext}"


def render_export_button(
    df: pd.DataFrame,
    label: str = "Download CSV",
    file_name: str = "export.csv",
    key: str = "export_btn",
) -> None:
    """Render a styled CSV download button."""
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label=label,
        data=csv,
        file_name=file_name,
        mime="text/csv",
        key=key,
        use_container_width=True,
    )
