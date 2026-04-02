"""
db/client.py — Supabase connection singleton.
"""

import streamlit as st
from supabase import create_client, Client


@st.cache_resource
def get_client() -> Client:
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"],
    )


def is_configured() -> bool:
    """Return True if Supabase secrets are present."""
    try:
        url = st.secrets.get("SUPABASE_URL", "")
        key = st.secrets.get("SUPABASE_KEY", "")
        return bool(url and key and "your-project" not in url)
    except Exception:
        return False
