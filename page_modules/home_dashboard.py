"""
page_modules/home_dashboard.py

EMIZA WMS — Home Dashboard (live data)

Home page pe dikhta hai:
- Stat cards: Total SKUs, Gate In Today, Gate Out Today, Open POs
- Quick Actions: click karke seedha page pe jao
- Recent Activity: last 8 Gate In / Gate Out entries

IMPORTANT:
- Yeh page READ ONLY hai, koi data change nahi karta
- Saara data 30-60 second ke liye cache hota hai (fast rahe isliye)
- Time India (IST) mein dikhta hai
"""

from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone

import streamlit as st

from auth import get_client


PAGE_SIZE = 1000
RECENT_LIMIT = 8

IST = timezone(timedelta(hours=5, minutes=30))


# =========================================================
# HELPERS
# =========================================================

def _s(value) -> str:
    return str(value or "").strip()


def _e(value) -> str:
    return html.escape(_s(value))


def _f(value) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _fmt_qty(value) -> str:
    value = _f(value)

    if value.is_integer():
        return f"{int(value):,}"

    return f"{value:,.2f}"


def _html(markup: str) -> None:
    cleaned = " ".join(
        line.strip()
        for line in markup.splitlines()
        if line.strip()
    )

    st.markdown(
        cleaned,
        unsafe_allow_html=True,
    )


def _today_start_utc_iso() -> str:
    """Aaj raat 12 baje (IST) ka time, UTC ISO format mein."""

    now_ist = datetime.now(IST)

    start_ist = now_ist.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    return start_ist.astimezone(timezone.utc).isoformat()


def _format_time(value) -> str:
    """DB ka created_at → '18-09-2026 11:31' (IST)."""

    raw = _s(value)

    if not raw:
        return "-"

    try:

        dt = datetime.fromisoformat(
            raw.replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(IST).strftime(
            "%d-%m-%Y %H:%M"
        )

    except Exception:

        return raw[:16]


# =========================================================
# LOAD: TOTAL SKUS  (location_master mein distinct SKU)
# =========================================================

@st.cache_data(ttl=60, show_spinner=False)
def _load_sku_stats() -> dict | None:

    try:

        client = get_client()

        skus: set[str] = set()
        locations: set[str] = set()

        start = 0

        while True:

            response = (
                client
                .table("location_master")
                .select("sku,location")
                .order("location")
                .range(start, start + PAGE_SIZE - 1)
                .execute()
            )

            data = response.data or []

            for row in data:

                sku = _s(row.get("sku"))
                location = _s(row.get("location"))

                if sku:
                    skus.add(sku)

                if location:
                    locations.add(location)

            if len(data) < PAGE_SIZE:
                break

            start += PAGE_SIZE

        return {
            "skus": len(skus),
            "locations": len(locations),
        }

    except Exception:

        return None


# =========================================================
# LOAD: TODAY GATE IN / GATE OUT
# =========================================================

@st.cache_data(ttl=30, show_spinner=False)
def _load_today_stats() -> dict | None:

    try:

        response = (
            get_client()
            .table("inventory_transactions")
            .select("transaction_type,qty")
            .gte(
                "created_at",
                _today_start_utc_iso(),
            )
            .limit(PAGE_SIZE)
            .execute()
        )

        stats = {
            "in_entries": 0,
            "in_units": 0.0,
            "out_entries": 0,
            "out_units": 0.0,
        }

        for row in response.data or []:

            kind = _s(
                row.get("transaction_type")
            ).upper()

            qty = _f(row.get("qty"))

            if kind == "IN":

                stats["in_entries"] += 1
                stats["in_units"] += qty

            elif kind == "OUT":

                stats["out_entries"] += 1
                stats["out_units"] += qty

        return stats

    except Exception:

        return None


# =========================================================
# LOAD: OPEN POs  (Gate In ka same logic)
# =========================================================

@st.cache_data(ttl=30, show_spinner=False)
def _load_open_po_stats() -> dict | None:

    try:

        from page_modules.gate_in import (
            _load_pos,
            _load_receiving_all,
            _load_qc_all,
            _load_putaway_all,
            _po_summary,
        )

        po_data = _load_pos()

        recv_map = _load_receiving_all()
        passed_map, rejected_map = _load_qc_all()
        putaway_map = _load_putaway_all()

        pending = 0
        partial = 0

        for po in po_data:

            if not _s(po.get("po_no")):
                continue

            status = _po_summary(
                po,
                recv_map,
                passed_map,
                rejected_map,
                putaway_map,
            )["status"]

            if status == "PENDING":
                pending += 1

            elif status in ("RECEIVING", "QC", "PUTAWAY"):
                partial += 1

        return {
            "open": pending + partial,
            "pending": pending,
            "partial": partial,
        }

    except Exception as e:

        # TEMPORARY DEBUG — asli error yahan store hota hai. Fix
        # confirm ho jaye toh ye line hata sakte ho.
        st.session_state["_open_po_debug_error"] = str(e)

        return None


# =========================================================
# LOAD: RECENT ACTIVITY
# =========================================================

@st.cache_data(ttl=30, show_spinner=False)
def _load_recent_activity() -> list[dict] | None:

    try:

        response = (
            get_client()
            .table("inventory_transactions")
            .select(
                "transaction_type,po_number,sku,location,qty,created_at"
            )
            .order("created_at", desc=True)
            .limit(RECENT_LIMIT)
            .execute()
        )

        return response.data or []

    except Exception:

        return None


# =========================================================
# CSS
# =========================================================

def _inject_css() -> None:

    st.markdown(
        """
        <style>

        /* RECENT ACTIVITY TABLE */

        .hd-table {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 14px;
            padding: 0.4rem 1rem;
            box-shadow: 0 1px 4px rgba(0,0,0,0.07);
        }

        .hd-tr {
            display: grid;
            grid-template-columns: 1.5fr 0.8fr 1.4fr 2.4fr 1.4fr 0.8fr;
            gap: 0.8rem;
            align-items: center;
            padding: 0.7rem 0.2rem;
            border-bottom: 1px solid #f1f5f9;
        }

        .hd-tr:last-child {
            border-bottom: none;
        }

        .hd-th {
            color: #6b7280;
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .hd-td {
            color: #374151;
            font-size: 0.82rem;
            word-break: break-word;
        }

        .hd-td-strong {
            color: #111827;
            font-weight: 600;
        }

        .hd-badge {
            display: inline-block;
            padding: 3px 10px;
            border-radius: 99px;
            font-size: 0.7rem;
            font-weight: 700;
        }

        .hd-in  { background: #dcfce7; color: #166534; }
        .hd-out { background: #ffedd5; color: #9a3412; }

        .hd-empty {
            background: #ffffff;
            border-radius: 16px;
            padding: 3rem 2rem;
            text-align: center;
            border: 2px dashed #e5e7eb;
            color: #9ca3af;
        }

        </style>
        """,
        unsafe_allow_html=True,
    )


# =========================================================
# UI PIECES
# =========================================================

def _stat_card(
    icon: str,
    label: str,
    value: str,
    sub: str,
) -> None:

    _html(
        f"""
        <div class="stat-card">
            <div class="stat-label">{icon} {label}</div>
            <div class="stat-value">{value}</div>
            <div class="stat-sub">{sub}</div>
        </div>
        """
    )


def _render_recent_activity(rows: list[dict] | None) -> None:

    if rows is None:

        st.warning(
            "Recent activity load nahi ho payi."
        )

        return

    if not rows:

        _html(
            """
            <div class="hd-empty">
                <div style="font-size:2rem;margin-bottom:0.6rem;">📭</div>
                <div style="font-weight:600;color:#6b7280;font-size:0.9rem;">
                    No activity yet
                </div>
                <div style="font-size:0.8rem;margin-top:0.3rem;">
                    Gate In / Gate Out entries yahan dikhengi.
                </div>
            </div>
            """
        )

        return

    body = """
        <div class="hd-tr hd-th">
            <div>Time</div>
            <div>Type</div>
            <div>PO / SO</div>
            <div>SKU</div>
            <div>Location</div>
            <div>Qty</div>
        </div>
    """

    for row in rows:

        kind = _s(row.get("transaction_type")).upper()

        badge_cls = "hd-in" if kind == "IN" else "hd-out"

        body += f"""
            <div class="hd-tr">
                <div class="hd-td">
                    {_format_time(row.get("created_at"))}
                </div>
                <div class="hd-td">
                    <span class="hd-badge {badge_cls}">{_e(kind) or "-"}</span>
                </div>
                <div class="hd-td hd-td-strong">
                    {_e(row.get("po_number")) or "-"}
                </div>
                <div class="hd-td">
                    {_e(row.get("sku")) or "-"}
                </div>
                <div class="hd-td">
                    {_e(row.get("location")) or "-"}
                </div>
                <div class="hd-td hd-td-strong">
                    {_fmt_qty(row.get("qty"))}
                </div>
            </div>
        """

    _html(
        f'<div class="hd-table">{body}</div>'
    )


# =========================================================
# MAIN
# =========================================================

def render_home_dashboard(
    username: str,
    on_navigate=None,
) -> None:
    """
    on_navigate(page_name) — Quick Action button dabane par call hota hai.
    """

    _inject_css()

    # =====================================================
    # HEADER
    # =====================================================

    left, right = st.columns([6, 1.2])

    with left:

        today_text = datetime.now(IST).strftime(
            "%A, %d %B %Y"
        )

        _html(
            f"""
            <div style="margin-bottom:1.2rem;">
                <div style="font-size:1.4rem;font-weight:700;color:#111827;">
                    Welcome back, {_e(username)} 👋
                </div>
                <div style="color:#6b7280;font-size:0.88rem;margin-top:0.2rem;">
                    {today_text} · Here's what's happening in the warehouse today.
                </div>
            </div>
            """
        )

    with right:

        if st.button(
            "🔄 Refresh",
            use_container_width=True,
            key="home_refresh",
        ):

            _load_sku_stats.clear()
            _load_today_stats.clear()
            _load_open_po_stats.clear()
            _load_recent_activity.clear()

            st.rerun()

    # =====================================================
    # STAT CARDS
    # =====================================================

    sku_stats = _load_sku_stats()
    today_stats = _load_today_stats()
    po_stats = _load_open_po_stats()

    c1, c2, c3, c4 = st.columns(4)

    with c1:

        if sku_stats:

            _stat_card(
                "📦",
                "Total SKUs",
                f'{sku_stats["skus"]:,}',
                f'{sku_stats["locations"]:,} locations',
            )

        else:

            _stat_card("📦", "Total SKUs", "—", "Data load nahi hua")

    with c2:

        if today_stats:

            _stat_card(
                "🚛",
                "Gate In Today",
                _fmt_qty(today_stats["in_units"]),
                f'{today_stats["in_entries"]} entries · units',
            )

        else:

            _stat_card("🚛", "Gate In Today", "—", "Data load nahi hua")

    with c3:

        if today_stats:

            _stat_card(
                "🚪",
                "Gate Out Today",
                _fmt_qty(today_stats["out_units"]),
                f'{today_stats["out_entries"]} entries · units',
            )

        else:

            _stat_card("🚪", "Gate Out Today", "—", "Data load nahi hua")

    with c4:

        if po_stats:

            _stat_card(
                "📋",
                "Open POs",
                f'{po_stats["open"]:,}',
                f'{po_stats["pending"]} pending · '
                f'{po_stats["partial"]} partial',
            )

        else:

            _stat_card("📋", "Open POs", "—", "Data load nahi hua")

            # TEMPORARY DEBUG — asli error yahan dikhega. Fix hone ke
            # baad ye 2 lines hata dena.
            if st.session_state.get("_open_po_debug_error"):

                st.caption(
                    f"Debug: {st.session_state['_open_po_debug_error']}"
                )

    # =====================================================
    # QUICK ACTIONS
    # =====================================================

    st.markdown(
        '<div class="section-head">Quick Actions</div>',
        unsafe_allow_html=True,
    )

    actions = [
        ("📋", "PO Creation", "Create a new purchase order"),
        ("🚛", "Gate In", "Receive material against PO"),
        ("🛒", "Sales Order", "Create & track sales orders"),
        ("🚪", "Gate Out", "Dispatch against sales order"),
        ("📦", "Material Check", "Find stock by SKU & location"),
    ]

    columns = st.columns(len(actions))

    for col, (icon, title, desc) in zip(columns, actions):

        with col:

            _html(
                f"""
                <div class="qa-card">
                    <div class="qa-icon">{icon}</div>
                    <div class="qa-title">{title}</div>
                    <div class="qa-desc">{desc}</div>
                </div>
                """
            )

            if st.button(
                "Open →",
                key=f"home_qa_{title}",
                use_container_width=True,
            ):

                if on_navigate:

                    on_navigate(title)

                    st.rerun()

    # =====================================================
    # RECENT ACTIVITY
    # =====================================================

    st.markdown(
        '<div class="section-head">Recent Activity</div>',
        unsafe_allow_html=True,
    )

    _render_recent_activity(
        _load_recent_activity()
    )
