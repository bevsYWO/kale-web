"""
components/export_button.py — CSV download button helper.
"""

from datetime import date as _date

import pandas as pd
import streamlit as st


def build_filename(base: str, platform: str = "", ext: str = "csv", filter_label: str = "") -> str:
    """
    Build a download filename: {base}-{platform}-{filter}-{date}.csv

    Example: build_filename("my_upload", "Instantly", filter_label="New only")
             → "my_upload-instantly-new-2026-04-23.csv"
    """
    today         = _date.today().strftime("%Y-%m-%d")
    platform_slug = platform.lower().replace(" ", "-") if platform else ""
    fl = filter_label.lower().strip()
    filter_slug   = fl.replace(" only", "").replace(" ", "-") if fl and fl != "all" else ""
    parts = [p for p in [base, platform_slug, filter_slug, today] if p]
    return "-".join(parts) + f".{ext}"


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
