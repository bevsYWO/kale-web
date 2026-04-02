"""
components/export_button.py — CSV download button helper.
"""

import streamlit as st
import pandas as pd


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
