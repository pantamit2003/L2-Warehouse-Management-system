"""
page_modules/gate_in.py
------------------------
Gate In page — 3-stage inbound flow.

Flow:
    PO List
        ↓
    Gate In Process  (3 cards: Receiving / QC / Putaway)
        ↓
    ┌─ 1. RECEIVING  → writes to `receiving` table only
    ├─ 2. QC PROCESS → writes to `qc` table only
    └─ 3. PUTAWAY    → writes to `putaway` table + `inventory_transactions` (IN)

Only Putaway increases location stock.
Receiving and QC do NOT touch inventory_transactions.
"""

import json
import pandas as pd
import streamlit as st
from db.supabase_client import get_client


PAGE_SIZE = 1000
TOP_LIST = 20


_PROCESSING_OVERLAY_HTML = """
<div style="
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(15,23,42,0.55);
    z-index: 9999;
    display: flex;
    align-items: center;
    justify-content: center;
">
    <div style="
        background:#ffffff;
        border-radius:16px;
        padding:2.4rem 3rem;
        text-align:center;
        box-shadow:0 20px 60px rgba(0,0,0,0.35);
    ">
        <div class="gi-spinner"></div>
        <div style="
            margin-top:1.2rem;
            font-size:1.05rem;
            font-weight:700;
            color:#111827;
        ">
            Processing…
        </div>
        <div style="
            margin-top:0.3rem;
            font-size:0.82rem;
            color:#6b7280;
        ">
            Please wait, do not refresh.
        </div>
    </div>
</div>
<style>
.gi-spinner {
    width:48px;
    height:48px;
    border:5px solid #e5e7eb;
    border-top:5px solid #0284c7;
    border-radius:50%;
    margin:0 auto;
    animation:gi-spin 0.8s linear infinite;
}
@keyframes gi-spin {
    0%   { transform:rotate(0deg); }
    100% { transform:rotate(360deg); }
}
</style>
"""


_CSS = """
<style>
.gate-title {
    font-size:1.35rem;
    font-weight:700;
    color:#111827;
    margin-bottom:1rem;
    padding-bottom:0.7rem;
    border-bottom:1px solid #e5e7eb;
}
.section-title {
    font-size:0.78rem;
    font-weight:700;
    color:#6b7280;
    letter-spacing:0.08em;
    text-transform:uppercase;
    margin-top:1.1rem;
    margin-bottom:0.7rem;
    padding-bottom:0.45rem;
    border-bottom:1px solid #e5e7eb;
}
.po-info {
    background:#eff6ff;
    border:1px solid #bfdbfe;
    border-radius:10px;
    padding:0.75rem 1rem;
    color:#1d4ed8;
    margin-bottom:1rem;
}
.stock-empty {
    background:#eff6ff;
    border:1px solid #bfdbfe;
    border-radius:10px;
    padding:0.75rem 1rem;
    color:#1d4ed8;
}
.gi-head {
    font-size:0.76rem;
    font-weight:700;
    color:#374151;
}
.gi-po {
    color:#0284c7;
    font-size:0.86rem;
    font-weight:700;
    word-break:break-word;
}
.gi-cell {
    color:#374151;
    font-size:0.82rem;
    line-height:1.4;
    word-break:break-word;
}
.gi-num {
    color:#111827;
    font-size:0.88rem;
    font-weight:700;
}
.gi-badge {
    display:inline-block;
    padding:4px 9px;
    border-radius:15px;
    font-size:0.7rem;
    font-weight:600;
    white-space:nowrap;
}
.gi-badge-pending {
    background:#ffedd5;
    color:#9a3412;
}
.gi-badge-partial {
    background:#dbeafe;
    color:#1e40af;
}
.gi-badge-receiving {
    background:#fef9c3;
    color:#854d0e;
}
.gi-badge-qc {
    background:#ede9fe;
    color:#5b21b6;
}
.gi-badge-putaway {
    background:#d1fae5;
    color:#065f46;
}
.gi-badge-completed {
    background:#dcfce7;
    color:#166534;
}
.gi-sep {
    border-bottom:1px solid #e5e7eb;
    margin:0.2rem 0 0.4rem 0;
}
.gip-card {
    background:#f9fafb;
    border:1px solid #e5e7eb;
    border-radius:12px;
    padding:1rem 1.2rem;
    margin-bottom:0.75rem;
}
.gip-card-title {
    font-size:1rem;
    font-weight:700;
    color:#111827;
    margin-bottom:0.25rem;
}
.gip-card-progress {
    font-size:0.82rem;
    color:#6b7280;
    margin-bottom:0.5rem;
}
button[data-baseweb="tab"][aria-selected="false"] p {
    color:#374151 !important;
    -webkit-text-fill-color:#374151 !important;
}
</style>
"""


def _s(val) -> str:
    return str(val or "").strip()


def _f(val) -> float:
    try:
        return float(val or 0)
    except Exception:
        return 0.0


def _init_state() -> None:
    defaults = {
        "gate_in_active_po": None,
        "gate_in_stage": None,
        "gate_in_success": False,
        "gate_in_pending_save": None,
        "receiving_lines": [],
        "qc_lines": [],
        "putaway_lines": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


@st.cache_data(ttl=60, show_spinner=False)
def _load_pos() -> list[dict]:
    try:
        r = (
            get_client()
            .table("po_master")
            .select("po_no,warehouse,vendor,po_type,sku_data")
            .order("created_at", desc=True)
            .execute()
        )
        return r.data or []
    except Exception as e:
        raise Exception(f"PO Master load error: {e}")


@st.cache_data(ttl=20, show_spinner=False)
def _load_receiving(po_no: str) -> list[dict]:
    try:
        r = (
            get_client()
            .table("receiving")
            .select("sku_code,received_qty")
            .eq("po_no", _s(po_no))
            .execute()
        )
        return r.data or []
    except Exception as e:
        raise Exception(f"Receiving load error: {e}")


@st.cache_data(ttl=20, show_spinner=False)
def _load_receiving_all() -> dict:
    try:
        totals = {}
        start = 0
        while True:
            r = (
                get_client()
                .table("receiving")
                .select("po_no,sku_code,received_qty")
                .order("id")
                .range(start, start + PAGE_SIZE - 1)
                .execute()
            )
            data = r.data or []
            for row in data:
                key = (_s(row.get("po_no")), _s(row.get("sku_code")))
                totals[key] = totals.get(key, 0.0) + _f(row.get("received_qty"))
            if len(data) < PAGE_SIZE:
                break
            start += PAGE_SIZE
        return totals
    except Exception as e:
        raise Exception(f"Receiving bulk load error: {e}")


def _total_received(po_no: str, sku_code: str) -> float:
    rows = _load_receiving(po_no)
    return sum(
        _f(r.get("received_qty"))
        for r in rows
        if _s(r.get("sku_code")) == _s(sku_code)
    )


@st.cache_data(ttl=20, show_spinner=False)
def _load_qc(po_no: str) -> list[dict]:
    try:
        r = (
            get_client()
            .table("qc")
            .select("sku_code,passed_qty,rejected_qty")
            .eq("po_no", _s(po_no))
            .execute()
        )
        return r.data or []
    except Exception as e:
        raise Exception(f"QC load error: {e}")


@st.cache_data(ttl=20, show_spinner=False)
def _load_qc_all() -> tuple[dict, dict]:
    try:
        passed_map = {}
        rejected_map = {}
        start = 0
        while True:
            r = (
                get_client()
                .table("qc")
                .select("po_no,sku_code,passed_qty,rejected_qty")
                .order("id")
                .range(start, start + PAGE_SIZE - 1)
                .execute()
            )
            data = r.data or []
            for row in data:
                key = (_s(row.get("po_no")), _s(row.get("sku_code")))
                passed_map[key] = passed_map.get(key, 0.0) + _f(row.get("passed_qty"))
                rejected_map[key] = rejected_map.get(key, 0.0) + _f(row.get("rejected_qty"))
            if len(data) < PAGE_SIZE:
                break
            start += PAGE_SIZE
        return passed_map, rejected_map
    except Exception as e:
        raise Exception(f"QC bulk load error: {e}")


def _total_qc(po_no: str, sku_code: str) -> tuple[float, float]:
    rows = _load_qc(po_no)
    passed = sum(_f(r.get("passed_qty")) for r in rows if _s(r.get("sku_code")) == _s(sku_code))
    rejected = sum(_f(r.get("rejected_qty")) for r in rows if _s(r.get("sku_code")) == _s(sku_code))
    return passed, rejected


@st.cache_data(ttl=20, show_spinner=False)
def _load_putaway(po_no: str) -> list[dict]:
    try:
        r = (
            get_client()
            .table("putaway")
            .select("sku_code,putaway_qty")
            .eq("po_no", _s(po_no))
            .execute()
        )
        return r.data or []
    except Exception as e:
        raise Exception(f"Putaway load error: {e}")


@st.cache_data(ttl=20, show_spinner=False)
def _load_putaway_all() -> dict:
    try:
        totals = {}
        start = 0
        while True:
            r = (
                get_client()
                .table("putaway")
                .select("po_no,sku_code,putaway_qty")
                .order("id")
                .range(start, start + PAGE_SIZE - 1)
                .execute()
            )
            data = r.data or []
            for row in data:
                key = (_s(row.get("po_no")), _s(row.get("sku_code")))
                totals[key] = totals.get(key, 0.0) + _f(row.get("putaway_qty"))
            if len(data) < PAGE_SIZE:
                break
            start += PAGE_SIZE
        return totals
    except Exception as e:
        raise Exception(f"Putaway bulk load error: {e}")


def _total_putaway(po_no: str, sku_code: str) -> float:
    rows = _load_putaway(po_no)
    return sum(_f(r.get("putaway_qty")) for r in rows if _s(r.get("sku_code")) == _s(sku_code))


def _stage_totals(po_no: str, sku_code: str, ordered_qty: float) -> dict:
    received = _total_received(po_no, sku_code)
    qc_passed, qc_rej = _total_qc(po_no, sku_code)
    putaway = _total_putaway(po_no, sku_code)

    receiving_pending = max(ordered_qty - received, 0)
    qc_pending = max(received - qc_passed - qc_rej, 0)
    putaway_pending = max(qc_passed - putaway, 0)

    return {
        "ordered": ordered_qty,
        "received": received,
        "receiving_pending": receiving_pending,
        "qc_passed": qc_passed,
        "qc_rejected": qc_rej,
        "qc_pending": qc_pending,
        "putaway": putaway,
        "putaway_pending": putaway_pending,
    }


def _stage_totals_from_maps(
    po_no: str,
    sku_code: str,
    ordered_qty: float,
    recv_map: dict,
    passed_map: dict,
    rejected_map: dict,
    putaway_map: dict,
) -> dict:
    key = (_s(po_no), _s(sku_code))
    received = recv_map.get(key, 0.0)
    qc_passed = passed_map.get(key, 0.0)
    qc_rej = rejected_map.get(key, 0.0)
    putaway = putaway_map.get(key, 0.0)

    return {
        "ordered": ordered_qty,
        "received": received,
        "receiving_pending": max(ordered_qty - received, 0),
        "qc_passed": qc_passed,
        "qc_rejected": qc_rej,
        "qc_pending": max(received - qc_passed - qc_rej, 0),
        "putaway": putaway,
        "putaway_pending": max(qc_passed - putaway, 0),
    }


def _clear_stage_caches() -> None:
    _load_receiving.clear()
    _load_receiving_all.clear()
    _load_qc.clear()
    _load_qc_all.clear()
    _load_putaway.clear()
    _load_putaway_all.clear()
    _load_pos.clear()
    _load_sku_locations.clear()
    _load_sku_transactions.clear()


def _get_po_skus(po_record: dict) -> list[dict]:
    raw = po_record.get("sku_data")
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _unique_skus(po_skus: list[dict]) -> dict[str, dict]:
    result = {}
    for sku in po_skus:
        code = _s(sku.get("sku_code"))
        if code:
            result[code] = sku
    return result


@st.cache_data(ttl=30, show_spinner=False)
def _load_sku_locations(sku_code: str) -> list[dict]:
    sku_code = _s(sku_code)
    if not sku_code:
        return []
    try:
        r = (
            get_client()
            .table("location_master")
            .select("wh_location,tower,rack,bin,location,sku,qty")
            .eq("sku", sku_code)
            .order("location")
            .execute()
        )
        return r.data or []
    except Exception as e:
        raise Exception(f"Location Master load error: {e}")


@st.cache_data(ttl=10, show_spinner=False)
def _load_sku_transactions(sku_code: str) -> list[dict]:
    sku_code = _s(sku_code)
    if not sku_code:
        return []
    try:
        r = (
            get_client()
            .table("inventory_transactions")
            .select("id,transaction_type,po_number,sku,location,qty")
            .eq("sku", sku_code)
            .execute()
        )
        return r.data or []
    except Exception as e:
        raise Exception(f"Inventory Transactions load error: {e}")


def _get_opening_stock(location_data: list[dict]) -> pd.DataFrame:
    rows = [
        {"location": _s(r.get("location")), "sku": _s(r.get("sku")), "qty": _f(r.get("qty"))}
        for r in location_data
        if _s(r.get("location")) and _s(r.get("sku"))
    ]
    if not rows:
        return pd.DataFrame(columns=["location", "sku", "qty"])
    return pd.DataFrame(rows).groupby(["location", "sku"], as_index=False)["qty"].sum()


def _get_transaction_stock(transaction_data: list[dict]) -> pd.DataFrame:
    rows = []
    for r in transaction_data:
        loc = _s(r.get("location"))
        sku = _s(r.get("sku"))
        if not loc or not sku:
            continue
        qty = _f(r.get("qty"))
        ttype = _s(r.get("transaction_type")).upper()
        if ttype == "IN":
            rows.append({"location": loc, "sku": sku, "qty": qty})
        elif ttype == "OUT":
            rows.append({"location": loc, "sku": sku, "qty": -qty})
    if not rows:
        return pd.DataFrame(columns=["location", "sku", "qty"])
    return pd.DataFrame(rows).groupby(["location", "sku"], as_index=False)["qty"].sum()


def _get_current_stock(location_data: list[dict], transaction_data: list[dict]) -> pd.DataFrame:
    combined = pd.concat(
        [_get_opening_stock(location_data), _get_transaction_stock(transaction_data)],
        ignore_index=True,
    )
    if combined.empty:
        return pd.DataFrame(columns=["location", "sku", "current_qty"])
    result = (
        combined.groupby(["location", "sku"], as_index=False)["qty"]
        .sum()
        .rename(columns={"qty": "current_qty"})
    )
    result.loc[result["current_qty"].abs() < 1e-6, "current_qty"] = 0
    return result[result["current_qty"] > 0].reset_index(drop=True)


def _get_location_stock(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["location", "current_qty"])
    return (
        df[["location", "current_qty"]]
        .groupby("location", as_index=False)["current_qty"]
        .sum()
        .sort_values("current_qty", ascending=False)
        .reset_index(drop=True)
    )


def _get_location_qty(df: pd.DataFrame, location: str) -> float:
    if df.empty:
        return 0.0
    mask = df["location"].astype(str).str.strip() == _s(location)
    return float(df.loc[mask, "current_qty"].sum())


def _get_location_names(location_data: list[dict]) -> list[str]:
    return sorted({_s(r.get("location")) for r in location_data if _s(r.get("location"))})


def _po_summary(
    po: dict,
    recv_map: dict,
    passed_map: dict,
    rejected_map: dict,
    putaway_map: dict,
) -> dict:
    po_no = _s(po.get("po_no"))
    unique_skus = _unique_skus(_get_po_skus(po))

    ordered = 0.0
    received = 0.0
    qc_passed = 0.0
    qc_rejected = 0.0
    putaway = 0.0

    for sku_code, sku in unique_skus.items():
        ordered_qty = _f(sku.get("qty"))
        totals = _stage_totals_from_maps(po_no, sku_code, ordered_qty, recv_map, passed_map, rejected_map, putaway_map)
        ordered += totals["ordered"]
        received += totals["received"]
        qc_passed += totals["qc_passed"]
        qc_rejected += totals["qc_rejected"]
        putaway += totals["putaway"]

    pending = max(ordered - received, 0)

    receiving_done = ordered > 0 and received >= ordered
    # QC "done" ka matlab: jitna receive hua, utna sab QC ho chuka ho
    # (pass + reject dono milaake) — sirf qc_passed > 0 dekhna kaafi
    # nahi tha (isi wajah se QC bina hue hi PO COMPLETED dikh raha tha).
    qc_done = receiving_done and (qc_passed + qc_rejected) >= received
    putaway_done = qc_done and putaway >= qc_passed

    if ordered <= 0:
        status = "PENDING"
    elif receiving_done and qc_done and putaway_done:
        status = "COMPLETED"
    elif putaway > 0:
        status = "PUTAWAY"
    elif qc_passed > 0 or qc_rejected > 0:
        status = "QC"
    elif received > 0:
        status = "RECEIVING"
    else:
        status = "PENDING"

    return {
        "po": po,
        "po_no": po_no,
        "vendor": _s(po.get("vendor")),
        "warehouse": _s(po.get("warehouse")),
        "sku_count": len(unique_skus),
        "ordered": ordered,
        "received": received,
        "pending": pending,
        "status": status,
    }


_COLS = [1.5, 2.0, 1.2, 0.9, 0.9, 0.9, 1.2, 1.0]


def _cell(col, css_class: str, text) -> None:
    col.markdown(f'<div class="{css_class}">{text}</div>', unsafe_allow_html=True)


def _render_po_rows(rows: list[dict], tab_key: str) -> None:
    if not rows:
        st.info("Koi PO nahi mila.")
        return

    shown = rows[:TOP_LIST]
    h = st.columns(_COLS)
    for col, label in zip(h, ["PO No", "Vendor", "Warehouse", "SKUs", "Ordered", "Pending", "Status", "Action"]):
        _cell(col, "gi-head", label)

    for r in shown:
        c = st.columns(_COLS)
        _cell(c[0], "gi-po", r["po_no"])
        _cell(c[1], "gi-cell", r["vendor"] or "-")
        _cell(c[2], "gi-cell", r["warehouse"] or "-")
        _cell(c[3], "gi-num", r["sku_count"])
        _cell(c[4], "gi-num", f'{r["ordered"]:g}')
        _cell(c[5], "gi-num", f'{r["pending"]:g}')
        c[6].markdown(f'<span class="gi-badge gi-badge-{r["status"].lower()}">{r["status"]}</span>', unsafe_allow_html=True)
        with c[7]:
            label = "Open ▶" if r["status"] != "COMPLETED" else "View"
            if st.button(label, key=f"gate_in_open_{tab_key}_{r['po_no']}", use_container_width=True):
                st.session_state.gate_in_active_po = r["po_no"]
                st.session_state.gate_in_stage = None
                st.session_state.putaway_lines = []
                st.rerun()
        st.markdown('<div class="gi-sep"></div>', unsafe_allow_html=True)

    if len(rows) > TOP_LIST:
        st.caption(f"Pehle {TOP_LIST} PO dikh rahe hain (total {len(rows)}). Baaki ke liye upar search karo.")


def _render_po_list(po_data: list[dict]) -> None:
    st.markdown('<div class="section-title">📄 Purchase Orders</div>', unsafe_allow_html=True)

    search = st.text_input(
        "Search PO",
        placeholder="Search PO No, Vendor or Warehouse...",
        label_visibility="collapsed",
        key="gate_in_search",
    ).strip().lower()

    try:
        recv_map = _load_receiving_all()
        passed_map, rejected_map = _load_qc_all()
        putaway_map = _load_putaway_all()
    except Exception as e:
        st.error(f"❌ Gate In stage data load error: {e}")
        return

    summaries = []
    for po in po_data:
        if not _s(po.get("po_no")):
            continue
        try:
            summary = _po_summary(po, recv_map, passed_map, rejected_map, putaway_map)
        except Exception:
            continue
        if search:
            searchable = " ".join([summary["po_no"], summary["vendor"], summary["warehouse"]]).lower()
            if search not in searchable:
                continue
        summaries.append(summary)

    pending_rows = [s for s in summaries if s["status"] != "COMPLETED"]
    completed_rows = [s for s in summaries if s["status"] == "COMPLETED"]

    tab_p, tab_c = st.tabs([
        f"⏳ Pending ({len(pending_rows)})",
        f"✅ Completed ({len(completed_rows)})",
    ])
    with tab_p:
        _render_po_rows(pending_rows, "pending")
    with tab_c:
        _render_po_rows(completed_rows, "completed")


def _render_gate_in_process(po: dict) -> None:
    po_no = _s(po.get("po_no"))
    vendor = _s(po.get("vendor"))
    warehouse = _s(po.get("warehouse"))

    if st.button("⬅ Back to PO List", key="gip_back_list"):
        st.session_state.gate_in_active_po = None
        st.session_state.gate_in_stage = None
        st.session_state.gate_in_pending_save = None
        st.session_state.receiving_lines = []
        st.session_state.qc_lines = []
        st.session_state.putaway_lines = []
        st.rerun()

    st.markdown(
        f'<div class="po-info"><b>PO:</b> {po_no} &nbsp;|&nbsp; <b>Vendor:</b> {vendor} &nbsp;|&nbsp; <b>Warehouse:</b> {warehouse}</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="gate-title">🔄 Gate In Process</div>', unsafe_allow_html=True)

    unique_skus = _unique_skus(_get_po_skus(po))
    agg = {"ordered": 0.0, "received": 0.0, "qc_passed": 0.0, "qc_rejected": 0.0, "putaway": 0.0}

    # NOTE (perf): compute totals once per SKU and reuse, instead of recomputing.
    for sku_code, sku in unique_skus.items():
        totals = _stage_totals(po_no, sku_code, _f(sku.get("qty")))
        agg["ordered"] += totals["ordered"]
        agg["received"] += totals["received"]
        agg["qc_passed"] += totals["qc_passed"]
        agg["qc_rejected"] += totals["qc_rejected"]
        agg["putaway"] += totals["putaway"]

    cards = [
        ("receiving", "📦", "RECEIVING", agg["received"], agg["ordered"], "gip_open_receiving"),
        ("qc", "🔍", "QC PROCESS", agg["qc_passed"] + agg["qc_rejected"], agg["received"], "gip_open_qc"),
        ("putaway", "📍", "PUTAWAY", agg["putaway"], agg["qc_passed"], "gip_open_putaway"),
    ]

    for stage, icon, title, done, total, button_key in cards:
        col_card, col_button = st.columns([5, 1])
        with col_card:
            progress_text = f"{done:g} / {total:g}" if total > 0 else "–"
            st.markdown(
                f'<div class="gip-card"><div class="gip-card-title">{icon} {title}</div><div class="gip-card-progress">Progress: {progress_text}</div></div>',
                unsafe_allow_html=True,
            )
        with col_button:
            st.markdown("<div style='margin-top:0.6rem'></div>", unsafe_allow_html=True)
            if st.button("Open →", key=button_key, use_container_width=True):
                st.session_state.gate_in_stage = stage
                st.session_state.receiving_lines = []
                st.session_state.qc_lines = []
                st.session_state.putaway_lines = []
                st.rerun()


def _sku_totals_map(po_no: str, sku_list: list[dict]) -> dict:
    """
    Compute _stage_totals() exactly once per SKU and cache the result
    for reuse within a single render pass (summary table + dropdown +
    default index all used to call this 3x per SKU separately).
    Pure perf helper — values and logic are unchanged.
    """
    totals_map = {}
    for sku in sku_list:
        code = _s(sku.get("sku_code"))
        totals_map[code] = _stage_totals(po_no, code, _f(sku.get("qty")))
    return totals_map


def _render_receiving(po: dict) -> None:
    po_no = _s(po.get("po_no"))

    # Save click ke turant baad, kisi bhi widget rebuild se PEHLE overlay
    # dikha do — warna native Streamlit "running" dim bina overlay ke
    # dikhta hai jab tak neeche wala save-handler nahi chalta.
    if st.session_state.get("gate_in_pending_save") == "receiving":
        overlay = st.empty()
        overlay.markdown(_PROCESSING_OVERLAY_HTML, unsafe_allow_html=True)
        st.session_state.gate_in_pending_save = None
        if not _do_save_receiving(po):
            overlay.empty()
        return

    if st.button("⬅ Back to Gate In Process", key="recv_back"):
        st.session_state.gate_in_stage = None
        st.session_state.receiving_lines = []
        st.rerun()

    st.markdown(
        f'<div class="po-info"><b>PO:</b> {po_no} &nbsp;|&nbsp; <b>Vendor:</b> {_s(po.get("vendor"))}</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="gate-title">📦 Receiving</div>', unsafe_allow_html=True)

    unique_skus = _unique_skus(_get_po_skus(po))
    if not unique_skus:
        st.warning("⚠️ Is PO mein koi SKU nahi mila.")
        return

    sku_list = list(unique_skus.values())
    totals_map = _sku_totals_map(po_no, sku_list)

    summary_rows = []
    for sku_code, sku in unique_skus.items():
        totals = totals_map[sku_code]
        summary_rows.append({
            "SKU": _s(sku.get("sku_name")) or sku_code,
            "Ordered": totals["ordered"],
            "Already Received": totals["received"],
            "Pending": totals["receiving_pending"],
        })

    st.markdown('<div class="section-title">📊 SKU Summary</div>', unsafe_allow_html=True)
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    sku_options = []
    for sku in sku_list:
        code = _s(sku.get("sku_code"))
        totals = totals_map[code]
        sku_options.append(f"{_s(sku.get('sku_name')) or code} — Pending: {totals['receiving_pending']:g}")

    default_idx = next((i for i, sku in enumerate(sku_list) if totals_map[_s(sku.get("sku_code"))]["receiving_pending"] > 0), 0)

    selected_display = st.selectbox("Select SKU", sku_options, index=default_idx, label_visibility="collapsed", key=f"recv_sku_{po_no}")
    idx = sku_options.index(selected_display)
    selected_sku = sku_list[idx]
    sku_code = _s(selected_sku.get("sku_code"))
    totals = totals_map[sku_code]
    pending_qty = totals["receiving_pending"]

    c1, c2, c3 = st.columns(3)
    c1.metric("Ordered", f'{totals["ordered"]:g}')
    c2.metric("Already Received", f'{totals["received"]:g}')
    c3.metric("Pending", f'{pending_qty:g}')

    if pending_qty <= 0:
        st.success("✅ Is SKU ki poori quantity receive ho chuki hai.")
        return

    st.markdown('<div class="section-title">📥 Enter Received Qty</div>', unsafe_allow_html=True)
    receive_qty = st.number_input("Receive Qty", min_value=0.0, max_value=float(pending_qty), value=0.0, step=1.0, key=f"recv_qty_{po_no}_{sku_code}", help=f"Max: {pending_qty:g}")

    if st.button("➕ Add Line", key=f"recv_add_{po_no}_{sku_code}"):
        if receive_qty <= 0:
            st.error("❌ Quantity 0 se zyada honi chahiye.")
        elif receive_qty > pending_qty:
            st.error(f"❌ Sirf {pending_qty:g} quantity pending hai.")
        else:
            st.session_state.receiving_lines.append({
                "po_no": po_no,
                "sku_code": sku_code,
                "sku_name": _s(selected_sku.get("sku_name")) or sku_code,
                "qty": float(receive_qty),
            })
            for key in list(st.session_state.keys()):
                if key == f"recv_qty_{po_no}_{sku_code}":
                    st.session_state.pop(key, None)
            st.rerun()

    if st.session_state.receiving_lines:
        st.markdown('<div class="section-title">📋 Staged Lines (this session)</div>', unsafe_allow_html=True)
        lines_df = pd.DataFrame(st.session_state.receiving_lines)[["po_no", "sku_code", "sku_name", "qty"]]
        lines_df.columns = ["PO No", "SKU Code", "SKU Name", "Qty"]
        st.dataframe(lines_df, use_container_width=True, hide_index=True)

        total_staged = sum(_f(l.get("qty")) for l in st.session_state.receiving_lines)
        st.info(f"📦 Total Staged: {total_staged:g}")

        col_save, col_clear = st.columns([3, 1])
        with col_clear:
            if st.button("🗑 Clear Lines", key="recv_clear"):
                st.session_state.receiving_lines = []
                st.rerun()

        with col_save:
            if st.button("✅ Save Receiving", type="primary", use_container_width=True, key="recv_save"):
                if not st.session_state.receiving_lines:
                    st.warning("⚠️ Koi line staged nahi hai.")
                else:
                    st.session_state.gate_in_pending_save = "receiving"
                    st.rerun()


def _do_save_receiving(po: dict) -> bool:
    """
    Called from the pending-save check at the TOP of _render_receiving,
    with the overlay already showing. Returns True on success (in which
    case it triggers a rerun and never actually returns), False on
    failure (caller clears the overlay and the error stays visible).
    """
    po_no = _s(po.get("po_no"))
    lines = list(st.session_state.receiving_lines)

    if not lines:
        st.warning("⚠️ Koi line staged nahi hai.")
        return False

    try:
        username = st.session_state.get("username", "")
        receiving_rows = []
        for line in lines:
            receiving_rows.append({
                "po_no": po_no,
                "sku_code": _s(line.get("sku_code")),
                "received_qty": _f(line.get("qty")),
                "received_by": username,
            })
        get_client().table("receiving").insert(receiving_rows).execute()
        _clear_stage_caches()
    except Exception as e:
        st.error(f"❌ Receiving save nahi hua: {e}")
        return False

    st.session_state.receiving_lines = []
    st.session_state.gate_in_success = True
    # Save ke baad "Gate In Process" (3-card) overview par wapas —
    # detail screen par hi na raha jaaye.
    st.session_state.gate_in_stage = None
    # Overlay yahan nahi hataya: agla run apna overlay dikhaye aur
    # page poora render hone ke baad hi hataye (purani screen ka
    # flash na aaye) — create_po.py wala pattern.
    st.session_state.gate_in_show_overlay = True
    st.rerun()
    return True


def _render_qc(po: dict) -> None:
    po_no = _s(po.get("po_no"))

    if st.session_state.get("gate_in_pending_save") == "qc":
        overlay = st.empty()
        overlay.markdown(_PROCESSING_OVERLAY_HTML, unsafe_allow_html=True)
        st.session_state.gate_in_pending_save = None
        if not _do_save_qc(po):
            overlay.empty()
        return

    if st.button("⬅ Back to Gate In Process", key="qc_back"):
        st.session_state.gate_in_stage = None
        st.session_state.qc_lines = []
        st.rerun()

    st.markdown(
        f'<div class="po-info"><b>PO:</b> {po_no} &nbsp;|&nbsp; <b>Vendor:</b> {_s(po.get("vendor"))}</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="gate-title">🔍 QC Process</div>', unsafe_allow_html=True)

    unique_skus = _unique_skus(_get_po_skus(po))
    if not unique_skus:
        st.warning("⚠️ Is PO mein koi SKU nahi mila.")
        return

    sku_list = list(unique_skus.values())
    totals_map = _sku_totals_map(po_no, sku_list)

    summary_rows = []
    for sku_code, sku in unique_skus.items():
        totals = totals_map[sku_code]
        summary_rows.append({
            "SKU": _s(sku.get("sku_name")) or sku_code,
            "Received": totals["received"],
            "QC Passed": totals["qc_passed"],
            "QC Rejected": totals["qc_rejected"],
            "QC Pending": totals["qc_pending"],
        })

    st.markdown('<div class="section-title">📊 QC Summary</div>', unsafe_allow_html=True)
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    sku_options = []
    for sku in sku_list:
        code = _s(sku.get("sku_code"))
        totals = totals_map[code]
        sku_options.append(f"{_s(sku.get('sku_name')) or code} — QC Pending: {totals['qc_pending']:g}")

    default_idx = next((i for i, sku in enumerate(sku_list) if totals_map[_s(sku.get("sku_code"))]["qc_pending"] > 0), 0)

    selected_display = st.selectbox("Select SKU", sku_options, index=default_idx, label_visibility="collapsed", key=f"qc_sku_{po_no}")
    idx = sku_options.index(selected_display)
    selected_sku = sku_list[idx]
    sku_code = _s(selected_sku.get("sku_code"))
    totals = totals_map[sku_code]
    qc_pending = totals["qc_pending"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Received", f'{totals["received"]:g}')
    c2.metric("QC Passed", f'{totals["qc_passed"]:g}')
    c3.metric("QC Rejected", f'{totals["qc_rejected"]:g}')
    c4.metric("QC Pending", f'{qc_pending:g}')

    if totals["received"] <= 0:
        st.warning("⚠️ Pehle kuch quantity receive karo.")
        return

    if qc_pending <= 0:
        st.success("✅ Is SKU ki saari received quantity QC ho chuki hai.")
        return

    st.markdown('<div class="section-title">🔍 Enter QC Result</div>', unsafe_allow_html=True)

    col_passed, col_rejected = st.columns(2)
    with col_passed:
        passed_qty = st.number_input("Passed Qty", min_value=0.0, max_value=float(qc_pending), value=0.0, step=1.0, key=f"qc_passed_{po_no}_{sku_code}")
    with col_rejected:
        max_rejected = max(qc_pending - passed_qty, 0.0)
        rejected_qty = st.number_input("Rejected Qty", min_value=0.0, max_value=float(max_rejected), value=0.0, step=1.0, key=f"qc_rejected_{po_no}_{sku_code}")

    remark = st.text_input("QC Remark (optional)", key=f"qc_remark_{po_no}_{sku_code}", placeholder="e.g. Damaged packaging, colour mismatch...")

    total_qc_entered = passed_qty + rejected_qty
    if total_qc_entered > qc_pending:
        st.error(f"❌ Passed + Rejected ({total_qc_entered:g}) > QC Pending ({qc_pending:g})")

    if st.button("➕ Add Line", key=f"qc_add_{po_no}_{sku_code}"):
        if total_qc_entered <= 0:
            st.error("❌ Passed + Rejected dono 0 nahi ho sakte.")
        elif total_qc_entered > qc_pending:
            st.error(f"❌ Sirf {qc_pending:g} units QC ke liye available hain.")
        else:
            st.session_state.qc_lines.append({
                "po_no": po_no,
                "sku_code": sku_code,
                "sku_name": _s(selected_sku.get("sku_name")) or sku_code,
                "passed_qty": float(passed_qty),
                "rejected_qty": float(rejected_qty),
                "remark": remark,
            })
            for key in list(st.session_state.keys()):
                if key in (f"qc_passed_{po_no}_{sku_code}", f"qc_rejected_{po_no}_{sku_code}", f"qc_remark_{po_no}_{sku_code}"):
                    st.session_state.pop(key, None)
            st.rerun()

    if st.session_state.qc_lines:
        st.markdown('<div class="section-title">📋 Staged Lines (this session)</div>', unsafe_allow_html=True)
        lines_df = pd.DataFrame(st.session_state.qc_lines)[["po_no", "sku_code", "sku_name", "passed_qty", "rejected_qty", "remark"]]
        lines_df.columns = ["PO No", "SKU Code", "SKU Name", "Passed", "Rejected", "Remark"]
        st.dataframe(lines_df, use_container_width=True, hide_index=True)

        total_passed = sum(_f(l.get("passed_qty")) for l in st.session_state.qc_lines)
        total_rejected = sum(_f(l.get("rejected_qty")) for l in st.session_state.qc_lines)
        st.info(f"📊 Total Passed: {total_passed:g} | Total Rejected: {total_rejected:g}")

        col_save, col_clear = st.columns([3, 1])
        with col_clear:
            if st.button("🗑 Clear Lines", key="qc_clear"):
                st.session_state.qc_lines = []
                st.rerun()

        with col_save:
            if st.button("✅ Save QC", type="primary", use_container_width=True, key="qc_save"):
                if not st.session_state.qc_lines:
                    st.warning("⚠️ Koi line staged nahi hai.")
                else:
                    st.session_state.gate_in_pending_save = "qc"
                    st.rerun()


def _do_save_qc(po: dict) -> bool:
    po_no = _s(po.get("po_no"))
    lines = list(st.session_state.qc_lines)

    if not lines:
        st.warning("⚠️ Koi line staged nahi hai.")
        return False

    try:
        username = st.session_state.get("username", "")
        qc_rows = []
        for line in lines:
            qc_rows.append({
                "po_no": po_no,
                "sku_code": _s(line.get("sku_code")),
                "passed_qty": _f(line.get("passed_qty")),
                "rejected_qty": _f(line.get("rejected_qty")),
                "remark": _s(line.get("remark")),
                "qc_by": username,
            })
        get_client().table("qc").insert(qc_rows).execute()
        _clear_stage_caches()
    except Exception as e:
        st.error(f"❌ QC save nahi hua: {e}")
        return False

    st.session_state.qc_lines = []
    st.session_state.gate_in_success = True
    st.session_state.gate_in_stage = None
    st.session_state.gate_in_show_overlay = True
    st.rerun()
    return True


def _render_putaway(po: dict) -> None:
    po_no = _s(po.get("po_no"))

    if st.session_state.get("gate_in_pending_save") == "putaway":
        overlay = st.empty()
        overlay.markdown(_PROCESSING_OVERLAY_HTML, unsafe_allow_html=True)
        st.session_state.gate_in_pending_save = None
        if not _do_save_putaway(po):
            overlay.empty()
        return

    if st.button("⬅ Back to Gate In Process", key="pta_back"):
        st.session_state.gate_in_stage = None
        st.session_state.putaway_lines = []
        st.rerun()

    if st.session_state.get("gate_in_success"):
        st.success("🎉 Putaway Saved Successfully!")
        st.session_state.gate_in_success = False

    st.markdown(
        f'<div class="po-info"><b>PO:</b> {po_no} &nbsp;|&nbsp; <b>Vendor:</b> {_s(po.get("vendor"))}</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="gate-title">📍 Putaway</div>', unsafe_allow_html=True)

    unique_skus = _unique_skus(_get_po_skus(po))
    if not unique_skus:
        st.warning("⚠️ Is PO mein koi SKU nahi mila.")
        return

    sku_list = list(unique_skus.values())
    totals_map = _sku_totals_map(po_no, sku_list)

    summary_rows = []
    for sku_code, sku in unique_skus.items():
        totals = totals_map[sku_code]
        summary_rows.append({
            "SKU": _s(sku.get("sku_name")) or sku_code,
            "QC Passed": totals["qc_passed"],
            "Already Putaway": totals["putaway"],
            "Putaway Pending": totals["putaway_pending"],
        })

    st.markdown('<div class="section-title">📊 Putaway Summary</div>', unsafe_allow_html=True)
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    sku_options = []
    for sku in sku_list:
        code = _s(sku.get("sku_code"))
        totals = totals_map[code]
        sku_options.append(f"{_s(sku.get('sku_name')) or code} — Putaway Pending: {totals['putaway_pending']:g}")

    default_idx = next((i for i, sku in enumerate(sku_list) if totals_map[_s(sku.get("sku_code"))]["putaway_pending"] > 0), 0)

    selected_display = st.selectbox("Select SKU", sku_options, index=default_idx, label_visibility="collapsed", key=f"pta_sku_{po_no}")
    idx = sku_options.index(selected_display)
    selected_sku = sku_list[idx]
    sku_code = _s(selected_sku.get("sku_code"))
    totals = totals_map[sku_code]
    putaway_pending = totals["putaway_pending"]

    c1, c2, c3 = st.columns(3)
    c1.metric("QC Passed", f'{totals["qc_passed"]:g}')
    c2.metric("Already Putaway", f'{totals["putaway"]:g}')
    c3.metric("Putaway Pending", f'{putaway_pending:g}')

    if totals["qc_passed"] <= 0:
        st.warning("⚠️ QC pass hone ke baad hi putaway kar sakte ho.")
        return

    if putaway_pending <= 0:
        st.success("✅ Is SKU ki saari QC-passed quantity putaway ho chuki hai.")
        return

    already_staged = sum(_f(line.get("qty")) for line in st.session_state.putaway_lines if _s(line.get("sku_code")) == sku_code)
    remaining_to_stage = max(putaway_pending - already_staged, 0.0)

    try:
        location_data = _load_sku_locations(sku_code)
        transaction_data = _load_sku_transactions(sku_code)
    except Exception as e:
        st.error(f"❌ Location load error: {e}")
        return

    current_stock_df = _get_current_stock(location_data, transaction_data)
    sku_locations = _get_location_names(location_data)

    if not sku_locations:
        st.error(f"❌ {_s(selected_sku.get('sku_name')) or sku_code} ke liye Location Master mein koi location assigned nahi hai.")
        return

    st.markdown('<div class="section-title">📍 Current Location Stock</div>', unsafe_allow_html=True)
    location_stock_df = _get_location_stock(current_stock_df)
    if location_stock_df.empty:
        st.markdown('<div class="stock-empty">ℹ️ Is SKU ka abhi kisi location par stock nahi hai.</div>', unsafe_allow_html=True)
    else:
        display_df = location_stock_df.copy()
        display_df.columns = ["Location", "Current Qty"]
        st.dataframe(display_df, use_container_width=True, hide_index=True)

    st.markdown('<div class="section-title">➕ Add Location Line</div>', unsafe_allow_html=True)

    if remaining_to_stage <= 0:
        st.info("ℹ️ Remaining putaway quantity staging list mein add ho chuki hai. 'Save Putaway' dabao.")
    else:
        location_display_map = {}
        location_options = ["— Select Location —"]
        for location in sku_locations:
            current_qty = _get_location_qty(current_stock_df, location)
            display_value = f"{location} — Current: {current_qty:g}"
            location_display_map[display_value] = location
            location_options.append(display_value)

        selected_location_display = st.selectbox("Select Location", location_options, label_visibility="collapsed", key=f"pta_loc_{po_no}_{sku_code}")

        line_qty = st.number_input("Putaway Qty", min_value=0.0, max_value=float(remaining_to_stage), value=0.0, step=1.0, key=f"pta_qty_{po_no}_{sku_code}", help=f"Max: {remaining_to_stage:g}")

        if st.button("➕ Add Line", key=f"pta_add_{po_no}_{sku_code}"):
            if selected_location_display == "— Select Location —":
                st.error("❌ Location select karo.")
            elif line_qty <= 0:
                st.error("❌ Qty 0 se zyada honi chahiye.")
            elif line_qty > remaining_to_stage:
                st.error(f"❌ Sirf {remaining_to_stage:g} remaining hai.")
            else:
                selected_location = location_display_map[selected_location_display]
                st.session_state.putaway_lines.append({
                    "po_no": po_no,
                    "sku_code": sku_code,
                    "sku_name": _s(selected_sku.get("sku_name")) or sku_code,
                    "location": selected_location,
                    "qty": float(line_qty),
                })
                for key in list(st.session_state.keys()):
                    if key in (f"pta_loc_{po_no}_{sku_code}", f"pta_qty_{po_no}_{sku_code}"):
                        st.session_state.pop(key, None)
                st.rerun()

    if st.session_state.putaway_lines:
        st.markdown('<div class="section-title">📋 Staged Lines (this session)</div>', unsafe_allow_html=True)
        lines_df = pd.DataFrame(st.session_state.putaway_lines)[["po_no", "sku_code", "sku_name", "location", "qty"]]
        lines_df.columns = ["PO No", "SKU Code", "SKU Name", "Location", "Qty"]
        st.dataframe(lines_df, use_container_width=True, hide_index=True)

        total_staged = sum(_f(l.get("qty")) for l in st.session_state.putaway_lines)
        st.info(f"📦 Total Staged: {total_staged:g}")

        col_save, col_clear = st.columns([3, 1])
        with col_clear:
            if st.button("🗑 Clear Lines", key="pta_clear"):
                st.session_state.putaway_lines = []
                st.rerun()

        with col_save:
            if st.button("✅ Save Putaway", type="primary", use_container_width=True, key="pta_save"):
                if not st.session_state.putaway_lines:
                    st.warning("⚠️ Koi line staged nahi hai.")
                else:
                    st.session_state.gate_in_pending_save = "putaway"
                    st.rerun()


def _do_save_putaway(po: dict) -> bool:
    po_no = _s(po.get("po_no"))
    lines = list(st.session_state.putaway_lines)
    unique_skus = _unique_skus(_get_po_skus(po))

    if not lines:
        st.warning("⚠️ Koi line staged nahi hai.")
        return False

    qty_by_sku = {}
    for line in lines:
        sku_code = _s(line.get("sku_code"))
        qty_by_sku[sku_code] = qty_by_sku.get(sku_code, 0.0) + _f(line.get("qty"))

    for sku_code, total_qty in qty_by_sku.items():
        sku_record = unique_skus.get(sku_code)
        if not sku_record:
            st.error(f"❌ SKU {sku_code} PO mein nahi mila.")
            return False
        totals = _stage_totals(po_no, sku_code, _f(sku_record.get("qty")))
        pending = totals["putaway_pending"]
        if total_qty > pending + 1e-6:
            st.error(f"❌ {sku_code}: Sirf {pending:g} units putaway ke liye available hain (aap {total_qty:g} daalne ki koshish kar rahe ho).")
            return False

    _load_sku_locations.clear()
    allowed_by_sku = {}
    for line in lines:
        sku_code = _s(line.get("sku_code"))
        location = _s(line.get("location"))
        if sku_code not in allowed_by_sku:
            allowed_by_sku[sku_code] = _get_location_names(_load_sku_locations(sku_code))
        if location not in allowed_by_sku[sku_code]:
            st.error(f"❌ {sku_code}: {location} valid assigned location nahi hai.")
            return False

    try:
        supabase = get_client()
        username = st.session_state.get("username", "")
        warehouse = _s(po.get("warehouse"))

        putaway_rows = []
        for line in lines:
            putaway_rows.append({
                "po_no": po_no,
                "sku_code": _s(line.get("sku_code")),
                "warehouse": warehouse,
                "location": _s(line.get("location")),
                "putaway_qty": _f(line.get("qty")),
                "putaway_by": username,
            })
        supabase.table("putaway").insert(putaway_rows).execute()

        transaction_rows = []
        for line in lines:
            transaction_rows.append({
                "transaction_type": "IN",
                "po_number": po_no,
                "sku": _s(line.get("sku_code")),
                "location": _s(line.get("location")),
                "qty": _f(line.get("qty")),
            })
        supabase.table("inventory_transactions").insert(transaction_rows).execute()

        _clear_stage_caches()
    except Exception as e:
        st.error(f"❌ Putaway save nahi hua: {e}")
        return False

    st.session_state.putaway_lines = []
    st.session_state.gate_in_success = True
    st.session_state.gate_in_stage = None
    st.session_state.gate_in_show_overlay = True
    st.rerun()
    return True


def _render_gate_in_body(on_back=None) -> None:
    _init_state()
    st.markdown(_CSS, unsafe_allow_html=True)

    st.markdown('<div class="gate-title">📥 Gate In</div>', unsafe_allow_html=True)

    if st.button("⬅ Back To Home", key="gate_in_back_home"):
        for k in ("gate_in_active_po", "gate_in_stage", "gate_in_success", "gate_in_pending_save", "receiving_lines", "qc_lines", "putaway_lines"):
            st.session_state.pop(k, None)
        if on_back:
            on_back()
        st.rerun()

    st.divider()

    if st.session_state.get("gate_in_success"):
        st.success("🎉 Gate In Saved Successfully!")
        st.session_state.gate_in_success = False

    flash = st.session_state.pop("gate_in_flash", "")
    if flash:
        st.success(flash)

    try:
        po_data = _load_pos()
    except Exception as e:
        st.error(f"❌ PO Data Load Error: {e}")
        return

    active_po_no = _s(st.session_state.get("gate_in_active_po") or "")
    active_po = next((p for p in po_data if _s(p.get("po_no")) == active_po_no), None) if active_po_no else None

    if not active_po:
        st.session_state.gate_in_active_po = None
        st.session_state.gate_in_stage = None
        _render_po_list(po_data)
        return

    stage = st.session_state.get("gate_in_stage")

    if stage == "receiving":
        _render_receiving(active_po)
    elif stage == "qc":
        _render_qc(active_po)
    elif stage == "putaway":
        _render_putaway(active_po)
    else:
        _render_gate_in_process(active_po)


def render_gate_in(on_back=None) -> None:
    """
    Entry point. Agar pichhle save (_do_save_receiving / _do_save_qc /
    _do_save_putaway) ne 'gate_in_show_overlay' flag set kiya hai, to
    is naye run ke SHURU mein hi overlay dikha do — body poora render
    (aur uske andar ke DB refetch) hone tak overlay wahi rehta hai.
    Isse purani/dim/unstyled screen ka flash nahi dikhta
    (create_po.py wala hi pattern).
    """
    overlay = None
    if st.session_state.pop("gate_in_show_overlay", False):
        overlay = st.empty()
        overlay.markdown(_PROCESSING_OVERLAY_HTML, unsafe_allow_html=True)

    try:
        _render_gate_in_body(on_back)
    finally:
        if overlay is not None:
            overlay.empty()
