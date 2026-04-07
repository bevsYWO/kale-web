"""
app.py — Kale Data Hub web app entry point.

Run with:
    streamlit run app.py
"""

import streamlit as st

st.set_page_config(
    page_title="Kale Data Hub",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ==============================================================================
# LOGIN GATE
# ==============================================================================

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_name" not in st.session_state:
    st.session_state.user_name = ""

if not st.session_state.authenticated:
    col_l, col_m, col_r = st.columns([1, 2, 1])
    with col_m:
        st.markdown(
            "<div style='text-align:center;padding:2rem 0 1rem;'>"
            "<span style='font-size:2rem;font-weight:700;color:#5C8B67;'>🌿 Kale</span>"
            "<span style='font-size:2rem;font-weight:300;'> Data Hub</span>"
            "</div>",
            unsafe_allow_html=True,
        )
        st.caption("Internal team tool — enter your name and the team password to continue.")
        st.markdown("")

        name = st.text_input("Your name", placeholder="e.g. Mike", key="login_name")
        pwd  = st.text_input("Team password", type="password", key="login_pwd")

        if st.button("Enter", use_container_width=True, type="primary"):
            if not name.strip():
                st.error("Please enter your name.")
            else:
                try:
                    if pwd == st.secrets["APP_PASSWORD"]:
                        st.session_state.authenticated = True
                        st.session_state.user_name = name.strip()
                        st.rerun()
                    else:
                        st.error("Incorrect password.")
                except Exception:
                    st.error("APP_PASSWORD not configured in secrets.toml")
    st.stop()

# ==============================================================================
# MAIN APP — only shown when authenticated
# ==============================================================================

from db.client import is_configured
from tabs import riipen, n2, terraboost, n2_recruiting, general, archive as archive_tab
from tabs import home as home_tab

# ── Header bar ────────────────────────────────────────────────────────────────
col_logo, col_fill, col_meta = st.columns([4, 5, 4])

with col_logo:
    st.markdown(
        "<span style='font-size:1.4rem;font-weight:700;color:#5C8B67;'>🌿 Kale</span>"
        "<span style='font-size:1.4rem;font-weight:300;'> Data Hub</span>",
        unsafe_allow_html=True,
    )

with col_meta:
    db_status = "🟢 Archive connected" if is_configured() else "🔴 Archive offline"
    user_name = st.session_state.get("user_name", "")
    st.markdown(
        f"<div style='text-align:right;font-size:0.82rem;color:#5C7471;line-height:1.8;'>"
        f"{db_status} &nbsp;|&nbsp; 👤 <strong>{user_name}</strong>"
        f"</div>",
        unsafe_allow_html=True,
    )

# Logout sits in its own tiny column so it doesn't fight the markdown
col_lg1, col_lg2 = st.columns([11, 2])
with col_lg2:
    if st.button("Log out", key="logout"):
        st.session_state.authenticated = False
        st.session_state.user_name = ""
        st.rerun()

st.markdown("<hr style='margin:0 0 0.5rem;border-color:#D6D3CB;'>", unsafe_allow_html=True)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab0, tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["Home", "Riipen", "N2", "Terraboost", "N2 Recruiting", "General", "Archive"]
)

with tab0:
    home_tab.render()

with tab1:
    riipen.render()

with tab2:
    n2.render()

with tab3:
    terraboost.render()

with tab4:
    n2_recruiting.render()

with tab5:
    general.render()

with tab6:
    archive_tab.render()
