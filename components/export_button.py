"""
components/export_button.py — CSV download button helper.
"""

from datetime import date as _date

import pandas as pd
import streamlit as st


def build_filename(base: str, platform: str = "", ext: str = "csv", filter_label: str = "") -> str:
    """
    Build a download filename that includes the logged-in user's name, today's date,
    the platform, and an optional filter label.

    Example: build_filename("leads_export", "Instantly", filter_label="New only")
             → "leads_export_mike_2026-04-07_instantly_new-only.csv"
    """
    user         = st.session_state.get("user_name", "")
    today        = _date.today().strftime("%Y-%m-%d")
    platform_slug = platform.lower().replace(" ", "_")
    filter_slug   = filter_label.lower().replace(" ", "-") if filter_label and filter_label.lower() != "all" else ""
    parts = [p for p in [base, user, today, platform_slug, filter_slug] if p]
    return "_".join(parts) + f".{ext}"


def render_export_button(
    df: pd.DataFrame,
    label: str = "Download CSV",
    file_name: str = "export.csv",
    key: str = "export_btn",
) -> bool:
    """Render a styled CSV download button. Returns True when clicked."""
    csv = df.to_csv(index=False).encode("utf-8")
    return st.download_button(
        label=label,
        data=csv,
        file_name=file_name,
        mime="text/csv",
        key=key,
        use_container_width=True,
    )
