"""
app.py  —  EMIZA WMS Phase 2: Login + Dashboard
Run:  streamlit run app.py
"""
from __future__ import annotations
import base64
from pathlib import Path
import streamlit as st
from auth import sign_in, sign_out, restore_session
from page_modules.create_po import render_create_po
from page_modules.gate_in import render_gate_in
from page_modules.create_so import render_create_so
from page_modules.sales_order import render_sales_order
from page_modules.gate_out import render_gate_out
from page_modules.material_check import render_material_check
from page_modules.home_dashboard import render_home_dashboard
from page_modules.reports import render_reports
from page_modules.picking import render_picking
from page_modules.packing import render_packing
from page_modules.dispatch import render_dispatch

st.set_page_config(
    page_title="L2 | Warehouse Management System",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)

BG_IMAGE = Path(__file__).parent / "assets" / "bg.jpg"


def _get_bg() -> str:
    if BG_IMAGE.exists():
        data = base64.b64encode(BG_IMAGE.read_bytes()).decode()
        return f"url('data:image/jpeg;base64,{data}') center center / cover no-repeat fixed"
    return "linear-gradient(135deg,#0a0d15 0%,#1a2340 100%)"


if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username      = None
    st.session_state.session       = None

if "current_page" not in st.session_state:
    st.session_state.current_page = "Home"

# ── REFRESH FIX ───────────────────────────────────────────
if not st.session_state.authenticated:
    restore_session()
# ─────────────────────────────────────────────────────────


# ── LOGIN CSS ─────────────────────────────────────────────────────────────
def inject_css(bg: str) -> None:
    st.markdown(f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

#MainMenu, header, footer,
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
[data-testid="stSidebarCollapsedControl"] {{ display:none !important; }}

html, body {{ margin:0; padding:0; font-family:'Inter',sans-serif; }}

.stApp {{
    background: {bg};
    animation: kb 30s ease-in-out infinite alternate;
    min-height: 100vh;
}}

[data-testid="stAppViewContainer"]::before {{
    content: '';
    position: fixed;
    inset: 0;
    background: rgba(4,8,20,0.62);
    z-index: 0;
    pointer-events: none;
}}

[data-testid="stAppViewContainer"],
[data-testid="stMain"],
.main {{ background: transparent !important; }}

.block-container {{
    padding: 0 !important;
    max-width: 100% !important;
    position: relative;
    z-index: 1;
}}

@keyframes kb {{
    0%   {{ background-size: 100% auto; }}
    100% {{ background-size: 115% auto; }}
}}

/* ── CARD ── */
div[data-testid="stForm"] {{
    background: rgba(12,18,35,0.88) !important;
    backdrop-filter: blur(22px) !important;
    -webkit-backdrop-filter: blur(22px) !important;
    border: 1px solid rgba(255,255,255,0.11) !important;
    border-radius: 18px !important;
    padding: 2.4rem 2rem 2rem !important;
    width: 360px !important;
    box-shadow: 0 40px 100px rgba(0,0,0,0.82) !important;
    margin: 0 auto !important;
    position: relative !important;
    z-index: 2 !important;
}}

div[data-testid="stForm"] label p {{
    color: rgba(255,255,255,0.52) !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    font-family: 'Inter',sans-serif !important;
}}

/* ── INPUT ── */
div[data-testid="stForm"] input,
div[data-testid="stForm"] [data-baseweb="input"],
div[data-testid="stForm"] [data-baseweb="base-input"] {{
    background: rgba(255,255,255,0.10) !important;
    background-color: rgba(255,255,255,0.10) !important;
}}
div[data-testid="stForm"] [data-baseweb="input"] {{
    border: 1px solid rgba(255,255,255,0.25) !important;
    border-radius: 10px !important;
    transition: border-color 0.2s, box-shadow 0.2s !important;
}}
div[data-testid="stForm"] input {{
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
    caret-color: #ffffff !important;
    font-size: 0.95rem !important;
    font-family: 'Inter',sans-serif !important;
    padding: 0.72rem 1rem !important;
    border: none !important;
}}
div[data-testid="stForm"] input::placeholder {{
    color: rgba(255,255,255,0.45) !important;
    -webkit-text-fill-color: rgba(255,255,255,0.45) !important;
}}
div[data-testid="stForm"] [data-baseweb="input"]:focus-within {{
    border-color: #3d7aed !important;
    box-shadow: 0 0 0 3px rgba(61,122,237,0.25) !important;
}}

/* ── AUTOFILL FIX (browser ka white/yellow background rokta hai) ── */
div[data-testid="stForm"] input:-webkit-autofill,
div[data-testid="stForm"] input:-webkit-autofill:hover,
div[data-testid="stForm"] input:-webkit-autofill:focus,
div[data-testid="stForm"] input:-webkit-autofill:active {{
    -webkit-box-shadow: 0 0 0 1000px #1c2540 inset !important;
    box-shadow: 0 0 0 1000px #1c2540 inset !important;
    -webkit-text-fill-color: #ffffff !important;
    caret-color: #ffffff !important;
    transition: background-color 9999s ease-in-out 0s !important;
}}

/* password eye icon ka color */
div[data-testid="stForm"] [data-baseweb="input"] svg {{
    fill: rgba(255,255,255,0.7) !important;
    color: rgba(255,255,255,0.7) !important;
}}

/* ── SUBMIT BUTTON ── */
div[data-testid="stForm"] button[kind="primaryFormSubmit"] {{
    width: 100% !important;
    background: linear-gradient(135deg,#2750a0,#4080f0) !important;
    color: #fff !important;
    -webkit-text-fill-color: #fff !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-size: 0.95rem !important;
    font-family: 'Inter',sans-serif !important;
    padding: 0.72rem !important;
    margin-top: 0.4rem !important;
    letter-spacing: 0.04em !important;
    box-shadow: 0 6px 22px rgba(40,80,200,0.45) !important;
    transition: opacity 0.2s, transform 0.15s !important;
    cursor: pointer !important;
}}
div[data-testid="stForm"] button[kind="primaryFormSubmit"]:hover {{
    opacity: 0.88 !important;
    transform: translateY(-1px) !important;
}}

/* ── ERROR ── */
div[data-testid="stAlert"] {{
    max-width: 360px !important;
    margin: 0.6rem auto 0 !important;
    background: rgba(180,30,30,0.22) !important;
    border: 1px solid rgba(255,80,80,0.3) !important;
    border-radius: 10px !important;
    color: #ff9090 !important;
    position: relative !important;
    z-index: 2 !important;
}}

[data-testid="stButton"] > button {{
    background: rgba(255,255,255,0.08) !important;
    color: #fff !important;
    -webkit-text-fill-color: #fff !important;
    border: 1px solid rgba(255,255,255,0.18) !important;
    border-radius: 10px !important;
    font-weight: 500 !important;
}}
[data-testid="stButton"] > button:hover {{
    background: rgba(255,255,255,0.15) !important;
}}
</style>""", unsafe_allow_html=True)


# ── DASHBOARD CSS ─────────────────────────────────────────────────────────
def inject_dashboard_css() -> None:
    st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

#MainMenu, header, footer,
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="stSidebarCollapseButton"],
button[title="Collapse sidebar"],
button[title="Expand sidebar"],
button[aria-label="Close sidebar"],
button[aria-label="Open sidebar"] { display:none !important; }

html, body, .stApp {
    margin: 0; padding: 0;
    font-family: 'Inter', sans-serif;
    background: #f0f2f6 !important;
}

/* ── SIDEBAR ── */
[data-testid="stSidebar"] {
    background: #1e2a45 !important;
    border-right: 1px solid #2d3d5c !important;
    padding-top: 0 !important;
    min-width: 220px !important;
    max-width: 220px !important;
    width: 220px !important;
    transform: none !important;
    visibility: visible !important;
    margin-left: 0 !important;
}
[data-testid="stSidebar"] > div:first-child {
    padding: 0 !important;
    display: flex !important;
    flex-direction: column !important;
    min-height: 100vh !important;
}

/* ── SIDEBAR BUTTON WITH WHITE BORDER BOX ── */
[data-testid="stSidebar"] button {
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
    width: 100% !important;
    text-align: left !important;
    background: transparent !important;
    border: 1.5px solid rgba(255,255,255,0.25) !important;
    border-radius: 10px !important;
    font-size: 0.88rem !important;
    font-weight: 500 !important;
    padding: 0.6rem 1rem !important;
    margin-bottom: 6px !important;
    transition: all 0.15s !important;
}

[data-testid="stSidebar"] button:hover {
    background: rgba(255,255,255,0.08) !important;
    border-color: rgba(255,255,255,0.4) !important;
}

[data-testid="stSidebar"] button p,
[data-testid="stSidebar"] button span {
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
}

/* main content */
[data-testid="stMain"] { background: #f0f2f6 !important; }
.block-container {
    padding: 2rem 2.5rem !important;
    max-width: 100% !important;
}

/* ── STAT CARDS ── */
.stat-card {
    background: #ffffff;
    border-radius: 14px;
    padding: 1.4rem 1.6rem;
    box-shadow: 0 1px 4px rgba(0,0,0,0.07);
    border: 1px solid #e5e7eb;
}
.stat-label {
    color: #6b7280;
    font-size: 0.78rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 0.4rem;
}
.stat-value {
    color: #111827;
    font-size: 1.9rem;
    font-weight: 700;
    line-height: 1.1;
}
.stat-sub {
    color: #9ca3af;
    font-size: 0.75rem;
    font-weight: 500;
    margin-top: 0.3rem;
}

/* ── QUICK ACTION CARDS ── */
.qa-card {
    background: #ffffff;
    border-radius: 14px;
    padding: 1.5rem;
    box-shadow: 0 1px 4px rgba(0,0,0,0.07);
    border: 1px solid #e5e7eb;
    text-align: center;
    transition: box-shadow 0.2s, transform 0.15s;
}
.qa-card:hover {
    box-shadow: 0 6px 20px rgba(0,0,0,0.12);
    transform: translateY(-2px);
}
.qa-icon { font-size: 2rem; margin-bottom: 0.6rem; }
.qa-title { color: #111827; font-size: 0.9rem; font-weight: 600; }
.qa-desc  { color: #6b7280; font-size: 0.75rem; margin-top: 0.2rem; }

/* ── SECTION HEADING ── */
.section-head {
    color: #111827;
    font-size: 1rem;
    font-weight: 600;
    margin: 1.8rem 0 1rem 0;
}

/* ── PLACEHOLDER ── */
.page-placeholder {
    background: #ffffff;
    border-radius: 16px;
    padding: 4rem 2rem;
    text-align: center;
    border: 2px dashed #e5e7eb;
    color: #9ca3af;
}

/* ── SIDEBAR USER BOX ── */
.sidebar-user-box {
    margin-top: auto !important;
    border-top: 1px solid rgba(255,255,255,0.1);
    padding: 1rem 1.2rem;
}
</style>""", unsafe_allow_html=True)


# ── LOGIN PAGE ────────────────────────────────────────────────────────────
def login_page() -> None:
    inject_css(_get_bg())
    st.markdown("<div style='height:12vh'></div>", unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1.3, 1])
    with col2:
        with st.form("login_form"):
            st.markdown("""
<div style="text-align:center; margin-bottom:1.6rem; pointer-events:none;">
  <div style="
    width:64px; height:64px;
    background:linear-gradient(135deg,#1b3a8c,#3060d0);
    border-radius:16px;
    display:inline-flex; align-items:center; justify-content:center;
    font-size:30px;
    box-shadow:0 8px 28px rgba(48,96,208,0.5);
    margin-bottom:0.9rem;
  ">🏭</div>
  <div style="color:#fff;font-size:1.35rem;font-weight:700;
              font-family:Inter,sans-serif;margin-bottom:.2rem;">
    Warehouse Management
  </div>
  <div style="color:rgba(255,255,255,0.38);font-size:0.82rem;
              font-family:Inter,sans-serif;">
    Secure Access to Operations
  </div>
</div>
""", unsafe_allow_html=True)

            username  = st.text_input("", placeholder="👤  Username",
                                      label_visibility="collapsed")
            password  = st.text_input("", placeholder="🔒  Password",
                                      label_visibility="collapsed",
                                      type="password")
            submitted = st.form_submit_button("Login")

            st.markdown("""
<div style="text-align:center;color:rgba(255,255,255,0.22);font-size:0.7rem;
font-family:Inter,sans-serif;margin-top:1rem;letter-spacing:0.06em;">
Smarter Warehousing. Stronger Tomorrow.
</div>
""", unsafe_allow_html=True)

    if submitted:
        if not username or not password:
            st.error("Please enter username and password.")
        else:
            result = sign_in(username, password)
            if result.ok:
                st.session_state.authenticated = True
                st.session_state.username      = result.username
                st.session_state.session       = result.session
                st.rerun()
            else:
                st.error("Invalid username or password")


# ── SIDEBAR ───────────────────────────────────────────────────────────────
def render_sidebar() -> None:
    with st.sidebar:

        st.markdown("""
<div style="
  padding:1.4rem 1.2rem 1rem;
  border-bottom:1px solid rgba(255,255,255,0.1);
  margin-bottom:0.6rem;
">
  <div style="display:flex;align-items:center;gap:10px;">
    <div style="
      width:36px;height:36px;
      background:linear-gradient(135deg,#1b3a8c,#3060d0);
      border-radius:9px;
      display:inline-flex;align-items:center;justify-content:center;
      font-size:18px;
    ">🏭</div>
    <div>
      <div style="font-weight:700;font-size:0.95rem;
                  color:#ffffff;line-height:1.1;">L2</div>
      <div style="font-size:0.7rem;color:#94a3b8;">Warehouse Management</div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

        nav_items = [
            ("🏠", "Home",           True),
            ("📋", "PO Creation",    True),
            ("🚛", "Gate In",        True),
            ("🛒", "Sales Order",    True),
            ("🚪", "Gate Out",       True),
            ("📦", "Material Check", True),
            ("📊", "Reports",        True),
        ]

        for icon, label, enabled in nav_items:
            if enabled:
                if st.button(f"{icon}  {label}", key=f"nav_{label}",
                             use_container_width=True):
                    st.session_state.current_page = label

                    if label == "Gate Out":
                        st.session_state.gate_out_active_order = None

                    st.rerun()
            else:
                st.markdown(f"""
<div style="
  padding:0.6rem 1rem;
  border-radius:8px;
  color:#ffffff;
  font-size:0.88rem;
  font-weight:500;
  display:flex;
  align-items:center;
  justify-content:space-between;
  margin-bottom:2px;
">
  <span>{icon}  {label}</span>
  <span style="
    background:rgba(255,255,255,0.1);
    color:#94a3b8;
    font-size:0.62rem;
    font-weight:600;
    padding:2px 7px;
    border-radius:99px;
  ">SOON</span>
</div>
""", unsafe_allow_html=True)

        st.markdown(
            "<div style='height:0.4rem'></div>",
            unsafe_allow_html=True,
        )

        if st.button("🚪  Logout", key="logout_btn",
                     use_container_width=True):
            sign_out()
            st.session_state.authenticated = False
            st.session_state.username      = None
            st.session_state.session       = None
            st.session_state.current_page  = "Home"
            st.rerun()

        st.markdown(f"""
<div class="sidebar-user-box">
  <div style="display:flex;align-items:center;gap:10px;">
    <div style="
      width:32px;height:32px;
      background:linear-gradient(135deg,#3060d0,#60a0ff);
      border-radius:50%;
      display:flex;align-items:center;justify-content:center;
      color:#fff;font-weight:700;font-size:0.85rem;
    ">{st.session_state.username[0].upper()}</div>
    <div>
      <div style="font-weight:600;font-size:0.82rem;color:#ffffff;">
        {st.session_state.username}
      </div>
      <div style="font-size:0.7rem;color:#94a3b8;">Warehouse Staff</div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)


# ── HOME PAGE ─────────────────────────────────────────────────────────────
def page_home() -> None:
    st.markdown(f"""
<div style="margin-bottom:1.6rem;">
  <div style="font-size:1.4rem;font-weight:700;color:#111827;">
    Welcome back, {st.session_state.username} 👋
  </div>
  <div style="color:#6b7280;font-size:0.88rem;margin-top:0.2rem;">
    Here's what's happening in the warehouse today.
  </div>
</div>
""", unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)
    for col, icon, label in [
        (c1, "📦", "Total SKUs"),
        (c2, "🚛", "Gate In Today"),
        (c3, "🚪", "Gate Out Today"),
        (c4, "📋", "Open POs"),
    ]:
        with col:
            st.markdown(f"""
<div class="stat-card">
  <div class="stat-label">{icon} {label}</div>
  <div class="stat-value">—</div>
  <div class="stat-sub">Live data coming soon</div>
</div>
""", unsafe_allow_html=True)

    st.markdown(
        '<div class="section-head">Quick Actions</div>',
        unsafe_allow_html=True,
    )

    q1, q2, q3, q4 = st.columns(4)
    for col, icon, title, desc in [
        (q1, "📋", "PO Creation",    "Create a new purchase order"),
        (q2, "🚛", "Gate In",        "Record incoming material"),
        (q3, "🚪", "Gate Out",       "Log outgoing shipment"),
        (q4, "📦", "Material Check", "Verify inventory & quality"),
    ]:
        with col:
            st.markdown(f"""
<div class="qa-card">
  <div class="qa-icon">{icon}</div>
  <div class="qa-title">{title}</div>
  <div class="qa-desc">{desc}</div>
  <div style="margin-top:0.8rem;">
    <span style="
      background:#f3f4f6;color:#9ca3af;
      font-size:0.7rem;font-weight:600;
      padding:3px 10px;border-radius:99px;
    ">Coming Soon</span>
  </div>
</div>
""", unsafe_allow_html=True)

    st.markdown(
        '<div class="section-head">Recent Activity</div>',
        unsafe_allow_html=True,
    )
    st.markdown("""
<div class="page-placeholder">
  <div style="font-size:2rem;margin-bottom:0.6rem;">📭</div>
  <div style="font-weight:600;color:#6b7280;font-size:0.9rem;">
    No activity yet
  </div>
  <div style="font-size:0.8rem;margin-top:0.3rem;">
    Gate In / Gate Out / PO entries will appear here.
  </div>
</div>
""", unsafe_allow_html=True)


# ── PLACEHOLDER PAGES ─────────────────────────────────────────────────────
def page_placeholder(name: str, icon: str) -> None:
    st.markdown(f"""
<div style="margin-bottom:1.6rem;">
  <div style="font-size:1.4rem;font-weight:700;color:#111827;">
    {icon} {name}
  </div>
  <div style="color:#6b7280;font-size:0.88rem;margin-top:0.2rem;">
    This module is under construction.
  </div>
</div>
<div class="page-placeholder">
  <div style="font-size:3rem;margin-bottom:0.8rem;">{icon}</div>
  <div style="font-weight:600;color:#374151;font-size:1rem;">
    {name} — Coming Soon
  </div>
  <div style="font-size:0.82rem;margin-top:0.4rem;">
    This feature will be available in the next phase.
  </div>
</div>
""", unsafe_allow_html=True)


# ── DASHBOARD SHELL ───────────────────────────────────────────────────────
def home_page() -> None:
    inject_dashboard_css()
    render_sidebar()

    page = st.session_state.current_page

    if page == "Home":
        render_home_dashboard(
            username=st.session_state.username,
            on_navigate=lambda p: st.session_state.update(
                current_page=p
            ),
        )
    elif page == "PO Creation":
        render_create_po(
            on_back=lambda: st.session_state.update(
                current_page="Home"
            )
        )
    elif page == "Gate In":
        render_gate_in(
            on_back=lambda: st.session_state.update(
                current_page="Home"
            )
        )
    elif page == "Sales Order":
        render_sales_order(
            on_create_order=lambda: st.session_state.update(
                current_page="Create Sales Order"
            )
        )
    elif page == "Create Sales Order":
        render_create_so(
            on_back=lambda: st.session_state.update(
                current_page="Sales Order"
            )
        )
    elif page == "Gate Out":
        render_gate_out(
            on_back=lambda: st.session_state.update(
                current_page="Home"
            )
        )
    elif page == "Material Check":
        render_material_check(
            on_back=lambda: st.session_state.update(
                current_page="Home"
            )
        )
    elif page == "Reports":
        render_reports(
            on_back=lambda: st.session_state.update(
                current_page="Home"
            )
        )
    elif page == "Picking":
        render_picking(
            on_back=lambda: st.session_state.update(current_page="Home")
        )

    elif page == "Packing":
        render_packing(
            on_back=lambda: st.session_state.update(current_page="Home")
        )
    elif page == "Dispatch":
        render_dispatch(
            on_back=lambda: st.session_state.update(current_page="Home")
        )
    else:
        st.error(f"Unknown page: {page!r}. Redirecting to Home.")
        st.session_state.current_page = "Home"


# ── ROUTER ────────────────────────────────────────────────────────────────
if st.session_state.authenticated:
    home_page()
else:
    login_page()
