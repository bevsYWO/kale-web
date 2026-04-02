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

if not st.session_state.authenticated:
    col_l, col_m, col_r = st.columns([1, 2, 1])
    with col_m:
        st.title("Kale Data Hub")
        st.caption("Internal team tool — please enter the team password to continue.")
        pwd = st.text_input("Team password", type="password", key="login_pwd")
        if st.button("Enter", use_container_width=True):
            try:
                if pwd == st.secrets["APP_PASSWORD"]:
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("Incorrect password")
            except Exception:
                st.error("APP_PASSWORD not configured in secrets.toml")
    st.stop()

# ==============================================================================
# MAIN APP — only shown when authenticated
# ==============================================================================

from tabs import riipen, n2, terraboost, n2_recruiting, general, archive as archive_tab

st.markdown(
    """
    <div style='display:flex; align-items:center; gap:10px; padding-bottom:6px;'>
        <span style='font-size:1.6rem; font-weight:700; color:#5C8B67;'>Kale</span>
        <span style='font-size:1.6rem; font-weight:300;'>Data Hub</span>
    </div>
    """,
    unsafe_allow_html=True,
)

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["Riipen", "N2", "Terraboost", "N2 Recruiting", "General", "Archive"]
)

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
