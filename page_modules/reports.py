"""
page_modules/reports.py
----------------
Reports page — 5 report types:
1. PO Report
2. Gate In Report
3. Gate Out Report
4. Sales Order Report
5. Current Inventory
"""

from __future__ import annotations

import io
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from db.supabase_client import get_client


# =========================================================
# HELPERS
# =========================================================

def _s(val) -> str:
    return str(val or "").strip()

def _f(val) -> float:
    try:
        return float(val or 0)
    except Exception:
        return 0.0


# =========================================================
# CSS
# =========================================================

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

[data-testid="stMain"] {
    background: #f0f2f6 !important;
    font-family: 'Inter', sans-serif;
}

.rpt-title {
    font-size: 1.45rem;
    font-weight: 700;
    color: #111827;
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 1.4rem;
}

.rpt-section-header {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.72rem;
    font-weight: 700;
    color: #6b7280;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    padding: 0.9rem 1.2rem;
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    margin-top: 1rem;
    margin-bottom: 1rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.rpt-label {
    font-size: 0.78rem;
    font-weight: 600;
    color: #374151;
    margin-bottom: 0.18rem;
}
.star { color: #f59e0b; }

.rpt-info {
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 10px;
    padding: 0.75rem 1.2rem;
    color: #1d4ed8;
    font-size: 0.85rem;
    font-weight: 600;
    margin-bottom: 1rem;
}

.rpt-empty {
    background: #ffffff;
    border: 2px dashed #e5e7eb;
    border-radius: 12px;
    padding: 3rem 2rem;
    text-align: center;
    color: #9ca3af;
    margin-top: 1rem;
}

[data-testid="stMain"] label {
    font-size: 0.78rem !important;
    font-weight: 600 !important;
    color: #374151 !important;
}

[data-testid="stMain"] input,
[data-testid="stMain"] [data-baseweb="select"] > div {
    background: #ffffff !important;
    border: 1px solid #d1d5db !important;
    border-radius: 8px !important;
    font-size: 0.88rem !important;
}
</style>
"""

# =========================================================
# SECTION HEADER
# =========================================================

def _section(icon: str, title: str) -> None:
    st.markdown(
        f'<div class="rpt-section-header">'
        f'<span>{icon}</span>{title}'
        f'</div>',
        unsafe_allow_html=True,
    )

def _label(text: str, required: bool = False) -> None:
    star = '<span class="star">⭐</span> ' if required else ""
    st.markdown(
        f'<div class="rpt-label">{star}{text}</div>',
        unsafe_allow_html=True,
    )


# =========================================================
# EXCEL DOWNLOAD HELPER
# =========================================================

def _to_excel(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Report")
    return buf.getvalue()


# =========================================================
# DATA LOADERS
# =========================================================

# ── 1. PO REPORT ──────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def _load_po_report(
    date_from: str,
    date_to: str,
) -> pd.DataFrame:
    try:
        res = (
            get_client()
            .table("po_master")
            .select(
                "po_no,vendor,warehouse,po_type,"
                "po_date,exp_date,transport,"
                "seller_po,invoice_type,remarks,"
                "sku_data,created_at"
            )
            .gte("created_at", date_from)
            .lte("created_at", date_to + "T23:59:59")
            .order("created_at", desc=True)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return pd.DataFrame()

        records = []
        for r in rows:
            sku_data = r.get("sku_data") or []
            if not sku_data:
                # PO with no SKUs — still show header
                records.append({
                    "PO No":        _s(r.get("po_no")),
                    "Vendor":       _s(r.get("vendor")),
                    "Warehouse":    _s(r.get("warehouse")),
                    "PO Type":      _s(r.get("po_type")),
                    "PO Date":      _s(r.get("po_date")),
                    "Exp Date":     _s(r.get("exp_date")),
                    "Transport":    _s(r.get("transport")),
                    "Seller PO":    _s(r.get("seller_po")),
                    "Invoice Type": _s(r.get("invoice_type")),
                    "Remarks":      _s(r.get("remarks")),
                    "SKU Code":     "",
                    "SKU Name":     "",
                    "Ordered Qty":  "",
                    "Created At":   _s(r.get("created_at"))[:19],
                })
            else:
                for sku in sku_data:
                    records.append({
                        "PO No":        _s(r.get("po_no")),
                        "Vendor":       _s(r.get("vendor")),
                        "Warehouse":    _s(r.get("warehouse")),
                        "PO Type":      _s(r.get("po_type")),
                        "PO Date":      _s(r.get("po_date")),
                        "Exp Date":     _s(r.get("exp_date")),
                        "Transport":    _s(r.get("transport")),
                        "Seller PO":    _s(r.get("seller_po")),
                        "Invoice Type": _s(r.get("invoice_type")),
                        "Remarks":      _s(r.get("remarks")),
                        "SKU Code":     _s(sku.get("sku_code")),
                        "SKU Name":     _s(sku.get("sku_name")),
                        "Ordered Qty":  _f(sku.get("qty")),
                        "Created At":   _s(r.get("created_at"))[:19],
                    })

        return pd.DataFrame(records)

    except Exception as e:
        st.error(f"PO Report load error: {e}")
        return pd.DataFrame()


# ── 2. GATE IN REPORT ─────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def _load_gate_in_report(
    date_from: str,
    date_to: str,
) -> pd.DataFrame:
    try:
        res = (
            get_client()
            .table("inventory_transactions")
            .select("id,po_number,sku,location,qty,created_at")
            .eq("transaction_type", "IN")
            .gte("created_at", date_from)
            .lte("created_at", date_to + "T23:59:59")
            .order("created_at", desc=True)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return pd.DataFrame()

        return pd.DataFrame([
            {
                "Txn ID":     r.get("id"),
                "PO Number":  _s(r.get("po_number")),
                "SKU":        _s(r.get("sku")),
                "Location":   _s(r.get("location")),
                "Qty":        _f(r.get("qty")),
                "Created At": _s(r.get("created_at"))[:19],
            }
            for r in rows
        ])

    except Exception as e:
        st.error(f"Gate In Report load error: {e}")
        return pd.DataFrame()


# ── 3. GATE OUT REPORT ────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def _load_gate_out_report(
    date_from: str,
    date_to: str,
) -> pd.DataFrame:
    try:
        res = (
            get_client()
            .table("inventory_transactions")
            .select("id,po_number,sku,location,qty,created_at")
            .eq("transaction_type", "OUT")
            .gte("created_at", date_from)
            .lte("created_at", date_to + "T23:59:59")
            .order("created_at", desc=True)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return pd.DataFrame()

        return pd.DataFrame([
            {
                "Txn ID":     r.get("id"),
                "Reference":  _s(r.get("po_number")),
                "SKU":        _s(r.get("sku")),
                "Location":   _s(r.get("location")),
                "Qty":        _f(r.get("qty")),
                "Created At": _s(r.get("created_at"))[:19],
            }
            for r in rows
        ])

    except Exception as e:
        st.error(f"Gate Out Report load error: {e}")
        return pd.DataFrame()


# ── 4. SALES ORDER REPORT ─────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def _load_so_report(
    date_from: str,
    date_to: str,
) -> pd.DataFrame:
    try:
        # SO headers
        so_res = (
            get_client()
            .table("sales_orders")
            .select(
                "id,order_id,warehouse,customer_name,"
                "phone,email,order_type,status,created_at"
            )
            .gte("created_at", date_from)
            .lte("created_at", date_to + "T23:59:59")
            .order("created_at", desc=True)
            .execute()
        )
        so_rows = so_res.data or []
        if not so_rows:
            return pd.DataFrame()

        so_ids = [r["id"] for r in so_rows]
        so_map = {r["id"]: r for r in so_rows}

        # SO items
        items_res = (
            get_client()
            .table("sales_order_items")
            .select(
                "sales_order_id,sku_code,quantity,"
                "mrp,selling_price,discount_amount,"
                "shelf_life_type,is_non_sellable,zone"
            )
            .in_("sales_order_id", so_ids)
            .execute()
        )
        item_rows = items_res.data or []

        if not item_rows:
            # SOs with no items
            return pd.DataFrame([
                {
                    "Order ID":      _s(so_map[sid]["order_id"]),
                    "Warehouse":     _s(so_map[sid]["warehouse"]),
                    "Customer":      _s(so_map[sid]["customer_name"]),
                    "Phone":         _s(so_map[sid]["phone"]),
                    "Email":         _s(so_map[sid]["email"]),
                    "Order Type":    _s(so_map[sid]["order_type"]),
                    "Status":        _s(so_map[sid]["status"]),
                    "SKU Code":      "",
                    "Quantity":      "",
                    "MRP":           "",
                    "Selling Price": "",
                    "Discount":      "",
                    "Shelf Life":    "",
                    "Non Sellable":  "",
                    "Zone":          "",
                    "Created At":    _s(so_map[sid]["created_at"])[:19],
                }
                for sid in so_ids
            ])

        records = []
        for item in item_rows:
            sid = item["sales_order_id"]
            so  = so_map.get(sid, {})
            records.append({
                "Order ID":      _s(so.get("order_id")),
                "Warehouse":     _s(so.get("warehouse")),
                "Customer":      _s(so.get("customer_name")),
                "Phone":         _s(so.get("phone")),
                "Email":         _s(so.get("email")),
                "Order Type":    _s(so.get("order_type")),
                "Status":        _s(so.get("status")),
                "SKU Code":      _s(item.get("sku_code")),
                "Quantity":      _f(item.get("quantity")),
                "MRP":           _f(item.get("mrp")),
                "Selling Price": _f(item.get("selling_price")),
                "Discount":      _f(item.get("discount_amount")),
                "Shelf Life":    _s(item.get("shelf_life_type")),
                "Non Sellable":  _s(item.get("is_non_sellable")),
                "Zone":          _s(item.get("zone")),
                "Created At":    _s(so.get("created_at"))[:19],
            })

        return pd.DataFrame(records)

    except Exception as e:
        st.error(f"Sales Order Report load error: {e}")
        return pd.DataFrame()


# ── 5. CURRENT INVENTORY ──────────────────────────────────

@st.cache_data(ttl=30, show_spinner=False)
def _load_inventory_report() -> pd.DataFrame:
    try:
        # Location master — opening stock
        loc_res = (
            get_client()
            .table("location_master")
            .select("location,sku,qty")
            .execute()
        )
        loc_rows = loc_res.data or []

        # All transactions
        txn_res = (
            get_client()
            .table("inventory_transactions")
            .select("transaction_type,sku,location,qty")
            .execute()
        )
        txn_rows = txn_res.data or []

        if not loc_rows and not txn_rows:
            return pd.DataFrame()

        # Opening stock df
        opening_records = [
            {
                "sku":      _s(r.get("sku")),
                "location": _s(r.get("location")),
                "opening":  _f(r.get("qty")),
            }
            for r in loc_rows
            if _s(r.get("sku")) and _s(r.get("location"))
        ]
        opening_df = (
            pd.DataFrame(opening_records)
            .groupby(["sku", "location"], as_index=False)["opening"]
            .sum()
            if opening_records
            else pd.DataFrame(columns=["sku", "location", "opening"])
        )

        # Transaction IN / OUT
        in_records  = []
        out_records = []
        for r in txn_rows:
            sku = _s(r.get("sku"))
            loc = _s(r.get("location"))
            qty = _f(r.get("qty"))
            ttype = _s(r.get("transaction_type")).upper()
            if not sku or not loc:
                continue
            if ttype == "IN":
                in_records.append({"sku": sku, "location": loc, "in_qty": qty})
            elif ttype == "OUT":
                out_records.append({"sku": sku, "location": loc, "out_qty": qty})

        in_df = (
            pd.DataFrame(in_records)
            .groupby(["sku", "location"], as_index=False)["in_qty"]
            .sum()
            if in_records
            else pd.DataFrame(columns=["sku", "location", "in_qty"])
        )

        out_df = (
            pd.DataFrame(out_records)
            .groupby(["sku", "location"], as_index=False)["out_qty"]
            .sum()
            if out_records
            else pd.DataFrame(columns=["sku", "location", "out_qty"])
        )

        # Merge all
        df = opening_df.copy()
        df = df.merge(in_df,  on=["sku", "location"], how="outer")
        df = df.merge(out_df, on=["sku", "location"], how="outer")
        df = df.fillna(0)

        df["current_qty"] = df["opening"] + df["in_qty"] - df["out_qty"]

        # Remove zero stock rows
        df = df[df["current_qty"] > 0].copy()

        df = df.rename(columns={
            "sku":         "SKU",
            "location":    "Location",
            "opening":     "Opening Qty",
            "in_qty":      "Total IN",
            "out_qty":     "Total OUT",
            "current_qty": "Current Qty",
        })

        return df.sort_values(
            ["SKU", "Location"]
        ).reset_index(drop=True)

    except Exception as e:
        st.error(f"Inventory Report load error: {e}")
        return pd.DataFrame()


# =========================================================
# REPORT TYPE CHANGE RESET
# =========================================================

def _on_report_type_change() -> None:
    """Reset date filters and old results when report type changes."""
    st.session_state.rpt_date_from = date.today() - timedelta(days=30)
    st.session_state.rpt_date_to   = date.today()
    st.session_state.pop("rpt_df", None)
    st.session_state.pop("rpt_title", None)


# =========================================================
# MAIN PAGE
# =========================================================

def render_reports(on_back=None) -> None:

    st.markdown(_CSS, unsafe_allow_html=True)

    # ── Title + Back ──
    c1, c2 = st.columns([8, 2])
    with c1:
        st.markdown(
            '<div class="rpt-title">📊 Reports</div>',
            unsafe_allow_html=True,
        )
    with c2:
        if on_back and st.button(
            "⬅ Back To Home", use_container_width=True
        ):
            on_back()
            st.rerun()

    st.divider()

    # =========================================================
    # FILTERS
    # =========================================================

    _section("🔍", "REPORT FILTERS")

    REPORT_TYPES = [
        "— Select Report —",
        "PO Report",
        "Gate In Report",
        "Gate Out Report",
        "Sales Order Report",
        "Current Inventory",
    ]

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        _label("Report Type", required=True)
        report_type = st.selectbox(
            "report_type", REPORT_TYPES,
            key="rpt_type", label_visibility="collapsed",
            on_change=_on_report_type_change,
        )

    # Date filters — not needed for Current Inventory
    if "rpt_date_from" not in st.session_state:
        st.session_state.rpt_date_from = date.today() - timedelta(days=30)
    if "rpt_date_to" not in st.session_state:
        st.session_state.rpt_date_to = date.today()

    date_from = st.session_state.rpt_date_from
    date_to   = st.session_state.rpt_date_to

    if report_type not in ("— Select Report —", "Current Inventory"):
        with c2:
            _label("Date From")
            date_from = st.date_input(
                "date_from", value=st.session_state.rpt_date_from,
                key="rpt_date_from", label_visibility="collapsed",
            )
        with c3:
            _label("Date To")
            date_to = st.date_input(
                "date_to", value=st.session_state.rpt_date_to,
                key="rpt_date_to", label_visibility="collapsed",
            )

    with c4:
        st.write("")
        st.write("")
        generate = st.button(
            "📊 Generate Report",
            type="primary",
            use_container_width=True,
            disabled=(report_type == "— Select Report —"),
        )

    # =========================================================
    # GENERATE
    # =========================================================

    if report_type == "— Select Report —":
        st.markdown(
            '<div class="rpt-empty">'
            '<div style="font-size:2.5rem;margin-bottom:0.6rem">📊</div>'
            '<div style="font-weight:600;font-size:0.95rem;color:#6b7280">'
            'Select a report type to get started'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    if not generate and "rpt_df" not in st.session_state:
        st.info("👆 Select filters and click Generate Report.")
        return

    if generate:
        df_from = str(date_from)
        df_to   = str(date_to)

        with st.spinner("Generating report..."):
            if report_type == "PO Report":
                df = _load_po_report(df_from, df_to)

            elif report_type == "Gate In Report":
                df = _load_gate_in_report(df_from, df_to)

            elif report_type == "Gate Out Report":
                df = _load_gate_out_report(df_from, df_to)

            elif report_type == "Sales Order Report":
                df = _load_so_report(df_from, df_to)

            elif report_type == "Current Inventory":
                df = _load_inventory_report()

            else:
                df = pd.DataFrame()

        st.session_state.rpt_df    = df
        st.session_state.rpt_title = report_type

    df = st.session_state.get("rpt_df", pd.DataFrame())

    # =========================================================
    # RESULTS
    # =========================================================

    _section("📋", f"REPORT — {st.session_state.get('rpt_title', '')}")

    if df.empty:
        st.markdown(
            '<div class="rpt-empty">'
            '<div style="font-size:2rem;margin-bottom:0.5rem">📭</div>'
            '<div style="font-weight:600;color:#6b7280;font-size:0.9rem">'
            'No data found for selected filters'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    # Summary
    st.markdown(
        f'<div class="rpt-info">'
        f'📋 Total Rows: <b>{len(df)}</b>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Table
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Download buttons
    c1, c2, _ = st.columns([2, 2, 6])

    with c1:
        st.download_button(
            label="⬇ Download CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name=f"{_s(st.session_state.get('rpt_title','report')).replace(' ','_')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with c2:
        st.download_button(
            label="⬇ Download Excel",
            data=_to_excel(df),
            file_name=f"{_s(st.session_state.get('rpt_title','report')).replace(' ','_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
