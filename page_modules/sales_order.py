"""
page_modules/sales_order.py
EMIZA WMS — Sales Order Module
"""

from __future__ import annotations
import streamlit as st
from auth import get_client


# =========================================================
# HELPERS
# =========================================================

def _s(value) -> str:
    return str(value or "").strip()

def _f(value) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


# =========================================================
# CSS
# =========================================================

def inject_sales_order_css() -> None:
    st.markdown("""
<style>

.so-page-title {
    font-size: 1.35rem;
    font-weight: 700;
    color: #111827;
    margin-bottom: 0.2rem;
}

/* ── STAT CARDS ── */
.so-stat-card {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    padding: 0.8rem 1.2rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}
.so-stat-label {
    font-size: 0.72rem;
    color: #6b7280;
    font-weight: 500;
    margin-bottom: 0.25rem;
}
.so-stat-value {
    font-size: 1.6rem;
    font-weight: 700;
    color: #111827;
    line-height: 1.1;
}

/* ── SEARCH ── */
.search-label {
    font-size: 0.82rem;
    font-weight: 600;
    color: #374151;
    margin-bottom: 0.3rem;
}

/* ── TABLE ── */
.so-header-text {
    font-size: 0.78rem;
    font-weight: 700;
    color: #374151;
}
.so-order-id {
    color: #0284c7;
    font-size: 0.84rem;
    font-weight: 700;
    line-height: 1.4;
}
.so-date {
    color: #374151;
    font-size: 0.8rem;
    line-height: 1.45;
}
.so-customer-name {
    color: #111827;
    font-size: 0.83rem;
    font-weight: 600;
    line-height: 1.4;
}
.so-customer-phone {
    color: #64748b;
    font-size: 0.77rem;
    margin-top: 3px;
}
.so-item-sku {
    color: #111827;
    font-size: 0.8rem;
    font-weight: 600;
    line-height: 1.4;
    word-break: break-word;
}
.so-item-qty {
    color: #64748b;
    font-size: 0.76rem;
    margin-bottom: 4px;
}
.so-cell {
    color: #374151;
    font-size: 0.8rem;
    line-height: 1.4;
}

/* ── STATUS ── */
.so-status {
    display: inline-block;
    background: #dcfce7;
    color: #166534;
    padding: 4px 9px;
    border-radius: 15px;
    font-size: 0.72rem;
    font-weight: 600;
    white-space: nowrap;
}
.so-status-picking    { background: #fef9c3; color: #854d0e; }
.so-status-packing    { background: #ede9fe; color: #5b21b6; }
.so-status-partial    { background: #ffedd5; color: #9a3412; }
.so-status-dispatched { background: #dbeafe; color: #1e40af; }
.so-status-cancelled  { background: #fee2e2; color: #991b1b; }

/* ── ORDER DETAIL CARD ── */
.so-detail-card {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    padding: 1.4rem 1.6rem;
    margin-bottom: 1rem;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}
.so-detail-title {
    font-size: 0.72rem;
    font-weight: 700;
    color: #6b7280;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    padding-bottom: 0.6rem;
    border-bottom: 1px solid #f3f4f6;
    margin-bottom: 1rem;
}
.so-detail-label {
    font-size: 0.72rem;
    color: #6b7280;
    font-weight: 500;
    margin-bottom: 0.15rem;
}
.so-detail-value {
    font-size: 0.85rem;
    color: #111827;
    font-weight: 600;
}

/* ── DIVIDER ── */
.so-divider {
    border-bottom: 1px solid #e5e7eb;
    margin-bottom: 0.15rem;
}

</style>
""", unsafe_allow_html=True)


# =========================================================
# DATA LOADERS
# =========================================================

@st.cache_data(ttl=30, show_spinner=False)
def _load_sales_orders() -> list[dict]:
    try:
        response = (
            get_client()
            .table("sales_orders")
            .select(
                "id,order_id,warehouse,customer_name,"
                "phone,email,alternate_phone,remark,"
                "order_type,status,created_at,"
                "billing_address_1,billing_address_2,"
                "billing_pincode,billing_state,billing_city,"
                "shipping_name,shipping_phone,"
                "shipping_address_1,shipping_address_2,"
                "shipping_pincode,shipping_state,shipping_city,"
                "same_as_billing"
            )
            .order("created_at", desc=True)
            .execute()
        )
        return response.data or []
    except Exception as e:
        st.error(f"Unable to load Sales Orders: {e}")
        return []


@st.cache_data(ttl=30, show_spinner=False)
def _load_order_items(sales_order_ids: tuple) -> dict:
    if not sales_order_ids:
        return {}
    try:
        response = (
            get_client()
            .table("sales_order_items")
            .select(
                "sales_order_id,sku_code,quantity,"
                "mrp,selling_price,discount_amount,"
                "shelf_life_type,is_non_sellable,zone"
            )
            .in_("sales_order_id", list(sales_order_ids))
            .execute()
        )
        grouped = {}
        for row in response.data or []:
            oid = row["sales_order_id"]
            grouped.setdefault(oid, []).append(row)
        return grouped
    except Exception as e:
        st.error(f"Unable to load Sales Order Items: {e}")
        return {}


@st.cache_data(ttl=5, show_spinner=False)
def _load_gate_out_totals(order_codes: tuple) -> dict:
    """(order_id, sku) -> total OUT qty (= Packed, since only Packing
    inserts inventory_transactions OUT now)."""
    if not order_codes:
        return {}
    try:
        response = (
            get_client()
            .table("inventory_transactions")
            .select("transaction_type,po_number,sku,qty")
            .eq("transaction_type", "OUT")
            .in_("po_number", list(order_codes))
            .execute()
        )
        totals = {}
        for row in response.data or []:
            key = (_s(row.get("po_number")), _s(row.get("sku")))
            totals[key] = totals.get(key, 0.0) + _f(row.get("qty"))
        return totals
    except Exception as e:
        st.error(f"Unable to load Gate Out data: {e}")
        return {}


@st.cache_data(ttl=5, show_spinner=False)
def _load_picking_totals(order_codes: tuple) -> dict:
    """(order_id, sku) -> total picked_qty ever recorded in `picking`."""
    if not order_codes:
        return {}
    try:
        response = (
            get_client()
            .table("picking")
            .select("order_id,sku_code,picked_qty")
            .in_("order_id", list(order_codes))
            .execute()
        )
        totals = {}
        for row in response.data or []:
            key = (_s(row.get("order_id")), _s(row.get("sku_code")))
            totals[key] = totals.get(key, 0.0) + _f(row.get("picked_qty"))
        return totals
    except Exception as e:
        st.error(f"Unable to load Picking data: {e}")
        return {}


# =========================================================
# CANCEL ORDER
# =========================================================

def _cancel_order(order_db_id: int) -> tuple[bool, str]:
    try:
        get_client() \
            .table("sales_orders") \
            .update({"status": "CANCELLED"}) \
            .eq("id", order_db_id) \
            .execute()
        # clear cache so list refreshes
        _load_sales_orders.clear()
        return True, "Order cancelled successfully."
    except Exception as e:
        return False, str(e)


# =========================================================
# STATUS LOGIC
# =========================================================

def _get_order_status(
    order_code: str,
    items: list[dict],
    picking_totals: dict,
    packed_totals: dict,
    base_status: str,
) -> tuple[str, str]:
    """
    Status pipeline (in order): CREATED -> PICKING -> PACKING -> DISPATCHED
    (or CANCELLED at any point).

    - PICKING: kam se kam ek SKU pick ho chuka hai, lekin poora order
      abhi Packed nahi hua.
    - PACKING: kam se kam ek SKU Packed/dispatched ho chuka hai, lekin
      poora order abhi fully Packed/dispatched nahi hua.
    - DISPATCHED: har SKU ka Packed qty >= Ordered qty.
    """

    if base_status == "CANCELLED":
        return ("CANCELLED", "so-status-cancelled")

    ordered = {}
    for item in items:
        sku = _s(item.get("sku_code"))
        if sku:
            ordered[sku] = ordered.get(sku, 0.0) + _f(item.get("quantity"))

    if not ordered:
        return (base_status, "")

    any_picked = False
    any_packed = False
    all_done   = True

    for sku, ordered_qty in ordered.items():

        picked_qty = picking_totals.get((order_code, sku), 0.0)
        packed_qty = packed_totals.get((order_code, sku), 0.0)

        if picked_qty > 0:
            any_picked = True

        if packed_qty > 0:
            any_packed = True

        if packed_qty < ordered_qty:
            all_done = False

    if all_done:
        return ("DISPATCHED", "so-status-dispatched")

    if any_packed:
        return ("PACKING", "so-status-packing")

    if any_picked:
        return ("PICKING", "so-status-picking")

    return (base_status, "")


# =========================================================
# DATE FORMAT
# =========================================================

def _format_date(value) -> str:
    if not value:
        return "-"
    value = str(value)
    try:
        date_part = value[:10]
        time_part = value[11:16]
        y, m, d   = date_part.split("-")
        return f"{d}-{m}-{y}<br>{time_part}"
    except Exception:
        return value

def _format_date_plain(value) -> str:
    if not value:
        return "-"
    value = str(value)
    try:
        date_part = value[:10]
        time_part = value[11:16]
        y, m, d   = date_part.split("-")
        return f"{d}-{m}-{y} {time_part}"
    except Exception:
        return value


# =========================================================
# CONSTANTS
# =========================================================

TABS      = ["Order Processing", "Picking", "Packing", "Dispatched", "Cancelled"]
PAGE_SIZE = 10

TAB_FILTERS = {
    "Order Processing": None,
    "Picking":          "PICKING",
    "Packing":          "PACKING",
    "Dispatched":       "DISPATCHED",
    "Cancelled":        "CANCELLED",
}


# =========================================================
# ORDER DETAIL VIEW
# =========================================================

def _render_order_detail(
    order: dict,
    items: list[dict],
) -> None:

    order_id = _s(order.get("order_id"))
    status   = _s(order.get("_status") or order.get("status"))

    # ── Back button ──
    if st.button("← Back to Orders", key="so_detail_back"):
        st.session_state.so_selected_order_id = None
        st.rerun()

    st.markdown(
        f'<div style="font-size:1.2rem;font-weight:700;'
        f'color:#111827;margin:0.8rem 0 1.2rem;">',
        unsafe_allow_html=True,
    )

    # ── Top row — Order ID + Status + Cancel ──
    c1, c2, c3 = st.columns([3, 2, 2])
    with c1:
        st.markdown(
            f'<div style="font-size:1.1rem;font-weight:700;color:#111827;">'
            f'📋 Order Details — '
            f'<span style="color:#0284c7">{order_id}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with c2:
        css = order.get("_css", "")
        st.markdown(
            f'<div style="padding-top:0.3rem;">'
            f'<span class="so-status {css}">{status}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with c3:
        # Cancel only if not already DISPATCHED or CANCELLED
        if status not in ("DISPATCHED", "CANCELLED"):
            if st.button(
                "🚫 Cancel Order",
                key=f"so_cancel_btn_{order['id']}",
                type="primary",
                use_container_width=True,
            ):
                st.session_state[
                    f"so_confirm_cancel_{order['id']}"
                ] = True

    # ── Confirm cancel ──
    confirm_key = f"so_confirm_cancel_{order['id']}"
    if st.session_state.get(confirm_key):
        st.warning(
            f"⚠️ Are you sure you want to cancel **{order_id}**? "
            "This cannot be undone."
        )
        yes_col, no_col, _ = st.columns([1.2, 1.2, 5])
        with yes_col:
            if st.button(
                "✅ Yes, Cancel",
                key=f"so_cancel_yes_{order['id']}",
                type="primary",
            ):
                ok, msg = _cancel_order(order["id"])
                if ok:
                    st.success("✅ Order cancelled successfully.")
                    st.session_state[confirm_key]              = False
                    st.session_state.so_selected_order_id      = None
                    st.rerun()
                else:
                    st.error(f"❌ Cancel failed: {msg}")
        with no_col:
            if st.button(
                "✖ No, Go Back",
                key=f"so_cancel_no_{order['id']}",
            ):
                st.session_state[confirm_key] = False
                st.rerun()

    st.markdown("<div style='height:0.6rem'></div>",
                unsafe_allow_html=True)

    # ── ORDER INFO CARD ──
    st.markdown(
        '<div class="so-detail-card">'
        '<div class="so-detail-title">📄 ORDER INFORMATION</div>',
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(
            f'<div class="so-detail-label">Order ID</div>'
            f'<div class="so-detail-value">{order_id}</div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f'<div class="so-detail-label">Order Date</div>'
            f'<div class="so-detail-value">'
            f'{_format_date_plain(order.get("created_at"))}'
            f'</div>',
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f'<div class="so-detail-label">Order Type</div>'
            f'<div class="so-detail-value">'
            f'{_s(order.get("order_type")) or "-"}'
            f'</div>',
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            f'<div class="so-detail-label">Warehouse</div>'
            f'<div class="so-detail-value">'
            f'{_s(order.get("warehouse")) or "-"}'
            f'</div>',
            unsafe_allow_html=True,
        )

    if _s(order.get("remark")):
        st.markdown("<div style='height:0.6rem'></div>",
                    unsafe_allow_html=True)
        st.markdown(
            f'<div class="so-detail-label">Remark</div>'
            f'<div class="so-detail-value">'
            f'{_s(order.get("remark"))}'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown('</div>', unsafe_allow_html=True)

    # ── CUSTOMER + ADDRESS ──
    left_col, right_col = st.columns(2)

    with left_col:
        st.markdown(
            '<div class="so-detail-card">'
            '<div class="so-detail-title">👤 CUSTOMER DETAILS</div>',
            unsafe_allow_html=True,
        )
        fields = [
            ("Name",            order.get("customer_name")),
            ("Phone",           order.get("phone")),
            ("Email",           order.get("email")),
            ("Alternate Phone", order.get("alternate_phone")),
        ]
        for label, val in fields:
            if _s(val):
                st.markdown(
                    f'<div class="so-detail-label">{label}</div>'
                    f'<div class="so-detail-value">'
                    f'{_s(val)}</div>'
                    f'<div style="height:0.4rem"></div>',
                    unsafe_allow_html=True,
                )
        st.markdown('</div>', unsafe_allow_html=True)

    with right_col:
        # Billing
        st.markdown(
            '<div class="so-detail-card">'
            '<div class="so-detail-title">🏠 BILLING ADDRESS</div>',
            unsafe_allow_html=True,
        )
        billing = ", ".join(filter(None, [
            _s(order.get("billing_address_1")),
            _s(order.get("billing_address_2")),
            _s(order.get("billing_city")),
            _s(order.get("billing_state")),
            _s(order.get("billing_pincode")),
        ]))
        st.markdown(
            f'<div class="so-detail-value">{billing or "-"}</div>',
            unsafe_allow_html=True,
        )
        st.markdown('</div>', unsafe_allow_html=True)

        # Shipping
        if not order.get("same_as_billing"):
            st.markdown(
                '<div class="so-detail-card">'
                '<div class="so-detail-title">🚚 SHIPPING ADDRESS</div>',
                unsafe_allow_html=True,
            )
            shipping = ", ".join(filter(None, [
                _s(order.get("shipping_name")),
                _s(order.get("shipping_address_1")),
                _s(order.get("shipping_address_2")),
                _s(order.get("shipping_city")),
                _s(order.get("shipping_state")),
                _s(order.get("shipping_pincode")),
            ]))
            st.markdown(
                f'<div class="so-detail-value">{shipping or "-"}</div>',
                unsafe_allow_html=True,
            )
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.info("Shipping address same as billing.")

    # ── ITEMS TABLE ──
    st.markdown(
        '<div class="so-detail-card">'
        '<div class="so-detail-title">📦 ORDER ITEMS</div>',
        unsafe_allow_html=True,
    )

    if not items:
        st.info("No items found for this order.")
    else:
        ih1, ih2, ih3, ih4, ih5 = st.columns(
            [2.5, 1.0, 1.0, 1.0, 1.2]
        )
        for col, label in zip(
            [ih1, ih2, ih3, ih4, ih5],
            ["SKU Code", "Quantity", "MRP", "Selling Price", "Discount"],
        ):
            with col:
                st.markdown(
                    f'<div class="so-header-text">{label}</div>',
                    unsafe_allow_html=True,
                )

        st.markdown(
            '<div style="border-bottom:2px solid #e5e7eb;'
            'margin:0.4rem 0 0.3rem;"></div>',
            unsafe_allow_html=True,
        )

        for item in items:
            ic1, ic2, ic3, ic4, ic5 = st.columns(
                [2.5, 1.0, 1.0, 1.0, 1.2]
            )
            with ic1:
                st.markdown(
                    f'<div class="so-cell" style="font-weight:600;">'
                    f'{_s(item.get("sku_code")) or "-"}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with ic2:
                st.markdown(
                    f'<div class="so-cell">'
                    f'{_f(item.get("quantity")):g}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with ic3:
                st.markdown(
                    f'<div class="so-cell">'
                    f'₹{_f(item.get("mrp")):g}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with ic4:
                st.markdown(
                    f'<div class="so-cell">'
                    f'₹{_f(item.get("selling_price")):g}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with ic5:
                st.markdown(
                    f'<div class="so-cell">'
                    f'₹{_f(item.get("discount_amount")):g}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            st.markdown(
                '<div class="so-divider"></div>',
                unsafe_allow_html=True,
            )

    st.markdown('</div>', unsafe_allow_html=True)


# =========================================================
# MAIN PAGE
# =========================================================

def render_sales_order(on_create_order=None) -> None:

    inject_sales_order_css()

    # ── session state init ──
    if "so_active_tab"         not in st.session_state:
        st.session_state.so_active_tab         = "Order Processing"
    if "so_page_number"        not in st.session_state:
        st.session_state.so_page_number        = 1
    if "so_selected_order_id"  not in st.session_state:
        st.session_state.so_selected_order_id  = None

    # =====================================================
    # HEADER
    # =====================================================

    col_title, col_btn = st.columns([7, 1.3])
    with col_title:
        st.markdown(
            '<div class="so-page-title">🛒 Sales Order</div>',
            unsafe_allow_html=True,
        )
    with col_btn:
        if st.button(
            "➕ Create Order", type="primary",
            use_container_width=True,
            key="sales_order_create_btn",
        ):
            if on_create_order:
                on_create_order()
                st.rerun()

    # =====================================================
    # LOAD DATA
    # =====================================================

    orders = _load_sales_orders()
    if not orders:
        st.info("No Sales Orders found.")
        return

    order_ids   = tuple(o["id"] for o in orders)
    order_codes = tuple(
        _s(o.get("order_id")) for o in orders
        if _s(o.get("order_id"))
    )

    items_by_order  = _load_order_items(order_ids)
    picking_totals  = _load_picking_totals(order_codes)
    packed_totals   = _load_gate_out_totals(order_codes)

    # ── compute effective status ──
    resolved = []
    for order in orders:
        items       = items_by_order.get(order["id"], [])
        base_status = _s(order.get("status")) or "CREATED"
        status, css = _get_order_status(
            _s(order.get("order_id")),
            items, picking_totals, packed_totals, base_status,
        )
        resolved.append({
            **order,
            "_status": status,
            "_css":    css,
            "_items":  items,
        })

    # =====================================================
    # DETAIL VIEW — agar koi order selected hai
    # =====================================================

    if st.session_state.so_selected_order_id is not None:
        sel_id = st.session_state.so_selected_order_id
        sel_order = next(
            (o for o in resolved if o["id"] == sel_id), None
        )
        if sel_order:
            _render_order_detail(
                sel_order,
                sel_order["_items"],
            )
            return

    # =====================================================
    # STAT CARDS
    # =====================================================

    counts = {}
    for o in resolved:
        s = o["_status"]
        counts[s] = counts.get(s, 0) + 1

    stat_items = [
        ("Total",      len(resolved)),
        ("Created",    counts.get("CREATED",    0)),
        ("Picking",    counts.get("PICKING",    0)),
        ("Packing",    counts.get("PACKING",    0)),
        ("Dispatched", counts.get("DISPATCHED", 0)),
        ("Cancelled",  counts.get("CANCELLED",  0)),
    ]

    cols = st.columns(len(stat_items))
    for col, (label, val) in zip(cols, stat_items):
        with col:
            st.markdown(f"""
<div class="so-stat-card">
  <div class="so-stat-label">{label}</div>
  <div class="so-stat-value">{val}</div>
</div>
""", unsafe_allow_html=True)

    st.markdown(
        "<div style='height:1rem'></div>",
        unsafe_allow_html=True,
    )

    # =====================================================
    # TABS
    # =====================================================

    tab_cols = st.columns(len(TABS))
    for col, tab in zip(tab_cols, TABS):
        with col:
            is_active = st.session_state.so_active_tab == tab
            btn_style = (
                "background:#eff6ff !important;"
                "color:#0284c7 !important;"
                "border-bottom:2px solid #0284c7 !important;"
                "font-weight:700 !important;"
            ) if is_active else ""
            if st.button(
                tab, key=f"so_tab_{tab}",
                use_container_width=True,
            ):
                st.session_state.so_active_tab  = tab
                st.session_state.so_page_number = 1
                st.rerun()

    st.markdown(
        '<div style="border-bottom:2px solid #e5e7eb;'
        'margin-bottom:1rem;"></div>',
        unsafe_allow_html=True,
    )

    # =====================================================
    # SEARCH
    # =====================================================

    st.markdown(
        '<div class="search-label">Search Sales Orders</div>',
        unsafe_allow_html=True,
    )
    search = st.text_input(
        "Search",
        placeholder="Search Order ID, Customer or Phone...",
        label_visibility="collapsed",
        key="so_processing_search",
    ).strip().lower()

    # =====================================================
    # FILTER
    # =====================================================

    tab_filter = TAB_FILTERS.get(st.session_state.so_active_tab)

    filtered = []
    for o in resolved:
        if tab_filter and o["_status"] != tab_filter:
            continue
        if search:
            haystack = " ".join([
                _s(o.get("order_id")),
                _s(o.get("customer_name")),
                _s(o.get("phone")),
                _s(o.get("warehouse")),
            ]).lower()
            if search not in haystack:
                continue
        filtered.append(o)

    if not filtered:
        st.info("No orders match your search.")
        return

    # =====================================================
    # PAGINATION
    # =====================================================

    total_orders = len(filtered)
    total_pages  = max(1, (total_orders + PAGE_SIZE - 1) // PAGE_SIZE)
    page         = min(st.session_state.so_page_number, total_pages)
    start        = (page - 1) * PAGE_SIZE
    end          = min(start + PAGE_SIZE, total_orders)
    page_orders  = filtered[start:end]

    # =====================================================
    # TABLE HEADER
    # =====================================================

    COL_W = [1.25, 1.15, 1.55, 2.0, 1.1, 1.0, 0.95, 1.05]

    h1,h2,h3,h4,h5,h6,h7,h8 = st.columns(COL_W)
    for col, label in zip(
        [h1,h2,h3,h4,h5,h6,h7,h8],
        ["Order ID","Order Date","Customer Details",
         "Item Details","Warehouse","Order Type","Status","Action"],
    ):
        with col:
            st.markdown(
                f'<div class="so-header-text">{label}</div>',
                unsafe_allow_html=True,
            )

    st.markdown(
        '<div style="border-bottom:2px solid #e5e7eb;'
        'margin-bottom:0.3rem;"></div>',
        unsafe_allow_html=True,
    )

    # =====================================================
    # TABLE ROWS
    # =====================================================

    for order in page_orders:

        items   = order["_items"]
        status  = order["_status"]
        css_cls = order["_css"]

        item_html = ""
        for item in items:
            sku = _s(item.get("sku_code")) or "-"
            qty = _s(item.get("quantity")) or "0"
            item_html += (
                f'<div class="so-item-sku">{sku}</div>'
                f'<div class="so-item-qty">QTY: {qty}</div>'
            )
        if not item_html:
            item_html = "-"

        r1,r2,r3,r4,r5,r6,r7,r8 = st.columns(COL_W)

        with r1:
            st.markdown(
                f'<div class="so-order-id">'
                f'{_s(order.get("order_id"))}</div>',
                unsafe_allow_html=True,
            )
        with r2:
            st.markdown(
                f'<div class="so-date">'
                f'{_format_date(order.get("created_at"))}</div>',
                unsafe_allow_html=True,
            )
        with r3:
            st.markdown(
                f'<div class="so-customer-name">'
                f'{_s(order.get("customer_name")) or "-"}</div>'
                f'<div class="so-customer-phone">'
                f'{_s(order.get("phone")) or "-"}</div>',
                unsafe_allow_html=True,
            )
        with r4:
            st.markdown(item_html, unsafe_allow_html=True)
        with r5:
            st.markdown(
                f'<div class="so-cell">'
                f'{_s(order.get("warehouse")) or "-"}</div>',
                unsafe_allow_html=True,
            )
        with r6:
            st.markdown(
                f'<div class="so-cell">'
                f'{_s(order.get("order_type")) or "-"}</div>',
                unsafe_allow_html=True,
            )
        with r7:
            st.markdown(
                f'<span class="so-status {css_cls}">{status}</span>',
                unsafe_allow_html=True,
            )
        with r8:
            if st.button(
                "👁 View",
                key=f"so_view_{order['id']}",
                use_container_width=True,
            ):
                st.session_state.so_selected_order_id = order["id"]
                st.rerun()

        st.markdown(
            '<div class="so-divider"></div>',
            unsafe_allow_html=True,
        )

    # =====================================================
    # PAGINATION CONTROLS
    # =====================================================

    st.markdown(
        "<div style='height:0.8rem'></div>",
        unsafe_allow_html=True,
    )

    info_col, prev_col, page_col, next_col = st.columns([4, 1, 2, 1])

    with info_col:
        st.markdown(
            f'<div style="font-size:0.82rem;color:#6b7280;'
            f'padding-top:0.5rem;">'
            f'{start+1} - {end} of {total_orders} orders'
            f'</div>',
            unsafe_allow_html=True,
        )
    with prev_col:
        if st.button("← Prev", use_container_width=True,
                     disabled=(page <= 1), key="so_prev"):
            st.session_state.so_page_number = page - 1
            st.rerun()
    with page_col:
        st.markdown(
            f'<div style="text-align:center;font-size:0.85rem;'
            f'color:#374151;padding-top:0.5rem;font-weight:600;">'
            f'Page {page} of {total_pages}</div>',
            unsafe_allow_html=True,
        )
    with next_col:
        if st.button("Next →", use_container_width=True,
                     disabled=(page >= total_pages), key="so_next"):
            st.session_state.so_page_number = page + 1
            st.rerun()
