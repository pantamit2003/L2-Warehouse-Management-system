"""
Shared helpers for the outbound flow:

    Sales Order -> Picking (picking.py) -> Physical Picking (physical_picking.py)
    -> Physical Packing (physical_packing.py) -> Packing Done (packing_done.py)
    -> Gate Out (gate_out.py)

Only generic, read-mostly helpers live here: formatting, CSS, the processing
overlay, Sales Order / Sales Order Items loaders, the location_master +
inventory_transactions stock calculation (needed only by Picking, since
that's the only stage that still deals with locations/stock), a generic
paginated "group and sum" loader for the new stage tables, and a shared
order-list table renderer so every stage page shows the same look.

Each stage file owns its OWN table's read/write logic and its OWN session
state — nothing about picking / physical_picking / physical_packing /
packing_done / final OUT logic lives here.
"""

from __future__ import annotations

import html as _html_mod

import streamlit as st

from auth import get_client

PAGE_SIZE = 1000
TOP_LIST = 20


# =========================================================
# BASIC FORMATTING
# =========================================================

def s(value) -> str:
    return str(value or "").strip()


def f(value) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def fmt_qty(value) -> str:
    value = f(value)

    if value.is_integer():
        return str(int(value))

    return f"{value:.2f}"


def esc(value) -> str:
    return _html_mod.escape(s(value))


def render_html(markup: str) -> None:
    cleaned = " ".join(
        line.strip()
        for line in markup.splitlines()
        if line.strip()
    )

    st.markdown(cleaned, unsafe_allow_html=True)


# =========================================================
# PROCESSING OVERLAY (same visual pattern as gate_in.py / old
# gate_out.py — shown at the very TOP of a stage's render
# function, before any widgets rebuild, and bridged across the
# rerun via a "<stage>_show_overlay" session flag consumed at
# the module's render_* entry point).
# =========================================================

def processing_overlay_html(title: str = "Processing...") -> str:
    return f"""
<div style="
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(15, 23, 42, 0.55);
    z-index: 9999;
    display: flex;
    align-items: center;
    justify-content: center;
">
    <div style="
        background: #ffffff;
        border-radius: 16px;
        padding: 2.4rem 3rem;
        text-align: center;
        box-shadow: 0 20px 60px rgba(0,0,0,0.35);
    ">
        <div class="ob-spinner"></div>
        <div style="margin-top: 1.2rem; font-size: 1.05rem; font-weight: 700; color: #111827;">
            {esc(title)}
        </div>
        <div style="margin-top: 0.3rem; font-size: 0.82rem; color: #6b7280;">
            Please wait, do not refresh.
        </div>
    </div>
</div>

<style>
.ob-spinner {{
    width: 48px;
    height: 48px;
    border: 5px solid #e5e7eb;
    border-top: 5px solid #0284c7;
    border-radius: 50%;
    margin: 0 auto;
    animation: ob-spin 0.8s linear infinite;
}}
@keyframes ob-spin {{
    0% {{ transform: rotate(0deg); }}
    100% {{ transform: rotate(360deg); }}
}}
</style>
"""


# =========================================================
# SHARED CSS (same classes gate_out.py already used, so the
# outbound flow keeps a consistent visual style end-to-end)
# =========================================================

OUTBOUND_CSS = """
<style>

.go-title {
    font-size: 1.35rem;
    font-weight: 700;
    color: #111827;
    margin-bottom: 1.2rem;
}

.go-section {
    font-size: 0.82rem;
    font-weight: 700;
    color: #64748b;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    padding-bottom: 0.55rem;
    border-bottom: 1px solid #e5e7eb;
    margin-bottom: 1rem;
}

.go-info {
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 10px;
    padding: 0.85rem 1rem;
    margin: 0.5rem 0;
}

.go-info-label {
    color: #64748b;
    font-size: 0.75rem;
    margin-bottom: 0.2rem;
}

.go-info-value {
    color: #111827;
    font-size: 1rem;
    font-weight: 700;
}

.go-stock {
    background: #f0fdf4;
    border: 1px solid #bbf7d0;
    border-radius: 10px;
    padding: 0.85rem 1rem;
    color: #166534;
    font-weight: 600;
    margin: 0.5rem 0;
}

.go-pending {
    background: #fff7ed;
    border: 1px solid #fed7aa;
    border-radius: 10px;
    padding: 0.85rem 1rem;
    color: #9a3412;
    font-weight: 600;
    margin: 0.5rem 0;
}

.go-sku-card {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    padding: 0.9rem 1rem;
    margin-top: 1rem;
    margin-bottom: 0.7rem;
}

.go-sku-code {
    color: #111827;
    font-size: 0.95rem;
    font-weight: 700;
}

.go-location-card {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    padding: 0.9rem 1rem;
    margin: 0.5rem 0;
}

.go-location-name {
    color: #111827;
    font-size: 0.88rem;
    font-weight: 700;
}

.go-location-warehouse {
    color: #0284c7;
    font-size: 0.75rem;
    font-weight: 600;
    margin-top: 0.2rem;
}

.go-location-stock {
    color: #166534;
    font-size: 0.85rem;
    font-weight: 700;
}

.go-review {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 0.75rem 1rem;
    margin-bottom: 0.5rem;
}

.go-review-label {
    color: #64748b;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}

.go-review-value {
    color: #111827;
    font-size: 0.9rem;
    font-weight: 700;
}

.go-dispatched {
    background: #ecfdf5;
    border: 1px solid #bbf7d0;
    border-radius: 10px;
    padding: 0.8rem 1rem;
    color: #166534;
    font-weight: 600;
    margin: 0.6rem 0;
}

.go-divider {
    height: 1px;
    background: #e5e7eb;
    margin: 1.2rem 0;
}

.gl-head {
    font-size: 0.76rem;
    font-weight: 700;
    color: #374151;
}

.gl-order {
    color: #0284c7;
    font-size: 0.86rem;
    font-weight: 700;
    word-break: break-word;
}

.gl-cell {
    color: #374151;
    font-size: 0.82rem;
    line-height: 1.4;
    word-break: break-word;
}

.gl-num {
    color: #111827;
    font-size: 0.88rem;
    font-weight: 700;
}

.gl-badge {
    display: inline-block;
    padding: 4px 9px;
    border-radius: 15px;
    font-size: 0.7rem;
    font-weight: 600;
    white-space: nowrap;
}

.gl-badge-pending {
    background: #ffedd5;
    color: #9a3412;
}

.gl-badge-partial {
    background: #dbeafe;
    color: #1e40af;
}

.gl-badge-done {
    background: #dcfce7;
    color: #166534;
}

.gl-sep {
    border-bottom: 1px solid #e5e7eb;
    margin: 0.2rem 0 0.4rem 0;
}

button[data-baseweb="tab"][aria-selected="false"] p {
    color: #374151 !important;
    -webkit-text-fill-color: #374151 !important;
}

[data-testid="stHorizontalBlock"] {
    align-items: center !important;
}
</style>    
"""


def inject_css() -> None:
    st.markdown(OUTBOUND_CSS, unsafe_allow_html=True)


# =========================================================
# SALES ORDERS + ITEMS (read-only, shared across every stage)
# =========================================================

@st.cache_data(ttl=30, show_spinner=False)
def load_sales_orders() -> list[dict]:

    client = get_client()

    try:

        response = (
            client.table("sales_orders")
            .select(
                """
                id,
                order_id,
                warehouse,
                existing_customer,
                customer_name,
                email,
                phone,
                alternate_phone,
                remark,
                order_type,

                billing_address_1,
                billing_address_2,
                billing_pincode,
                billing_state,
                billing_city,

                shipping_name,
                shipping_phone,
                shipping_address_1,
                shipping_address_2,
                shipping_pincode,
                shipping_state,
                shipping_city,

                same_as_billing,

                status,
                created_at
                """
            )
            .order("created_at", desc=True)
            .execute()
        )

        return response.data or []

    except Exception:

        return []


@st.cache_data(ttl=30, show_spinner=False)
def load_sales_order_items(sales_order_id: int) -> list[dict]:

    client = get_client()

    try:

        response = (
            client.table("sales_order_items")
            .select(
                """
                id,
                sales_order_id,
                sku_code,
                quantity,
                shelf_life_type,
                mrp,
                selling_price,
                discount_amount,
                is_non_sellable,
                zone
                """
            )
            .eq("sales_order_id", sales_order_id)
            .execute()
        )

        return response.data or []

    except Exception as e:

        st.error(f"Unable to load Sales Order Items: {e}")

        return []


@st.cache_data(ttl=30, show_spinner=False)
def load_all_order_items() -> dict:
    """All sales_order_items grouped by sales_order_id (bulk, for list views)."""

    client = get_client()

    grouped: dict = {}

    start = 0

    while True:

        response = (
            client.table("sales_order_items")
            .select("id,sales_order_id,sku_code,quantity")
            .order("id")
            .range(start, start + PAGE_SIZE - 1)
            .execute()
        )

        data = response.data or []

        for row in data:

            grouped.setdefault(row["sales_order_id"], []).append(row)

        if len(data) < PAGE_SIZE:
            break

        start += PAGE_SIZE

    return grouped


def get_ordered_qty(items: list[dict], sku_code: str) -> float:

    total = 0.0

    for item in items:

        if s(item.get("sku_code")) == sku_code:

            total += f(item.get("quantity"))

    return total


# =========================================================
# LOCATION MASTER + INVENTORY TRANSACTIONS (stock helpers).
# Only Picking needs these — it's the only stage that still
# deals with WHERE stock physically sits.
# =========================================================

@st.cache_data(ttl=30, show_spinner=False)
def load_sku_locations(sku_code: str) -> list[dict]:

    client = get_client()

    try:

        response = (
            client.table("location_master")
            .select("wh_location,tower,rack,bin,location,sku,qty")
            .eq("sku", sku_code)
            .execute()
        )

        return response.data or []

    except Exception as e:

        st.error(f"Unable to load locations for {sku_code}: {e}")

        return []


@st.cache_data(ttl=30, show_spinner=False)
def load_sku_transactions(sku_code: str) -> list[dict]:

    client = get_client()

    try:

        response = (
            client.table("inventory_transactions")
            .select("id,transaction_type,po_number,sku,location,qty")
            .eq("sku", sku_code)
            .execute()
        )

        return response.data or []

    except Exception as e:

        st.error(f"Unable to load transactions for {sku_code}: {e}")

        return []


def get_location_stock(location: str, location_data: list[dict], transactions: list[dict]) -> float:
    """Opening (location_master.qty) + IN - OUT, for one location. Never negative."""

    location = s(location)

    opening_qty = 0.0

    for row in location_data:

        if s(row.get("location")) == location:

            opening_qty += f(row.get("qty"))

    transaction_qty = 0.0

    for tx in transactions:

        if s(tx.get("location")) != location:
            continue

        ttype = s(tx.get("transaction_type")).upper()

        qty = f(tx.get("qty"))

        if ttype == "IN":

            transaction_qty += qty

        elif ttype == "OUT":

            transaction_qty -= qty

    return max(0.0, opening_qty + transaction_qty)


def get_total_stock(location_data: list[dict], transactions: list[dict]) -> float:

    locations = set()

    for row in location_data:

        loc = s(row.get("location"))

        if loc:
            locations.add(loc)

    for tx in transactions:

        loc = s(tx.get("location"))

        if loc:
            locations.add(loc)

    return sum(get_location_stock(loc, location_data, transactions) for loc in locations)


@st.cache_data(ttl=20, show_spinner=False)
def load_picking_lines() -> dict:
    """
    Every picking table row, grouped by (order_id, sku_code) -> list of
    {location, picked_qty, warehouse}.

    This is the "original picking location" breakdown that Physical
    Picking works through and that the final Gate Out uses to split the
    OUT transaction across the same locations it was picked from.
    """

    client = get_client()

    grouped: dict = {}

    start = 0

    while True:

        response = (
            client.table("picking")
            .select("id,order_id,sku_code,warehouse,location,picked_qty")
            .order("id")
            .range(start, start + PAGE_SIZE - 1)
            .execute()
        )

        data = response.data or []

        for row in data:

            key = (s(row.get("order_id")), s(row.get("sku_code")))

            grouped.setdefault(key, []).append(row)

        if len(data) < PAGE_SIZE:
            break

        start += PAGE_SIZE

    return grouped


def clear_common_caches() -> None:

    load_sales_orders.clear()
    load_sales_order_items.clear()
    load_all_order_items.clear()
    load_sku_locations.clear()
    load_sku_transactions.clear()
    load_picking_lines.clear()


# =========================================================
# GENERIC PAGINATED "GROUP AND SUM" LOADER — every stage
# table (picking / physical_picking / physical_packing /
# packing_done) and inventory_transactions (OUT) use this
# same shape: sum a qty column grouped by some key columns.
# =========================================================

def load_grouped_totals(table_name: str, qty_col: str, key_cols: tuple, filters: dict | None = None) -> dict:

    client = get_client()

    totals: dict = {}

    start = 0

    select_cols = ",".join(list(key_cols) + [qty_col])

    while True:

        query = client.table(table_name).select(select_cols).order("id")

        if filters:

            for col, val in filters.items():

                query = query.eq(col, val)

        query = query.range(start, start + PAGE_SIZE - 1)

        response = query.execute()

        data = response.data or []

        for row in data:

            key = tuple(s(row.get(c)) for c in key_cols)

            totals[key] = totals.get(key, 0.0) + f(row.get(qty_col))

        if len(data) < PAGE_SIZE:
            break

        start += PAGE_SIZE

    return totals


# =========================================================
# STAGE SUMMARY (per Sales Order) — used to build the
# Pending / Done list tables. Two flavours:
#
# - from_items(): baseline is the ORIGINAL ordered qty from
#   sales_order_items. Used by Picking (stage 1) only.
#
# - from_baseline(): baseline is the PREVIOUS stage's total
#   for that order+sku (e.g. Physical Picking's cap is what
#   was System Picked). Used by stages 2-5.
# =========================================================

def _status_from(ordered: float, done: float, pending: float, done_label: str) -> tuple[str, str]:

    if ordered <= 0:
        return "PENDING", "pending"

    if pending <= 0:
        return done_label, "done"

    if done > 0:
        return "PARTIAL", "partial"

    return "PENDING", "pending"


def build_summary_from_items(order: dict, items: list[dict], done_totals: dict, done_label: str) -> dict:

    order_id = s(order.get("order_id"))

    ordered_by_sku: dict[str, float] = {}

    for item in items:

        sku = s(item.get("sku_code"))

        if not sku:
            continue

        ordered_by_sku[sku] = ordered_by_sku.get(sku, 0.0) + f(item.get("quantity"))

    ordered = 0.0
    done = 0.0
    pending = 0.0

    for sku, ordered_qty in ordered_by_sku.items():

        done_qty = done_totals.get((order_id, sku), 0.0)

        ordered += ordered_qty

        done += min(done_qty, ordered_qty)

        pending += max(ordered_qty - done_qty, 0.0)

    status_label, status_kind = _status_from(ordered, done, pending, done_label)

    return {
        "order": order,
        "order_id": order_id,
        "customer": s(order.get("customer_name")),
        "phone": s(order.get("phone")),
        "warehouse": s(order.get("warehouse")),
        "sku_count": len(ordered_by_sku),
        "ordered": ordered,
        "done": done,
        "pending": pending,
        "status": status_label,
        "status_kind": status_kind,
    }


def build_summary_from_baseline(order: dict, baseline_totals: dict, done_totals: dict, done_label: str) -> dict:

    order_id = s(order.get("order_id"))

    relevant = {
        key: qty
        for key, qty in baseline_totals.items()
        if key[0] == order_id and qty > 0
    }

    ordered = 0.0
    done = 0.0
    pending = 0.0

    for key, cap_qty in relevant.items():

        done_qty = done_totals.get(key, 0.0)

        ordered += cap_qty

        done += min(done_qty, cap_qty)

        pending += max(cap_qty - done_qty, 0.0)

    status_label, status_kind = _status_from(ordered, done, pending, done_label)

    return {
        "order": order,
        "order_id": order_id,
        "customer": s(order.get("customer_name")),
        "phone": s(order.get("phone")),
        "warehouse": s(order.get("warehouse")),
        "sku_count": len(relevant),
        "ordered": ordered,
        "done": done,
        "pending": pending,
        "status": status_label,
        "status_kind": status_kind,
    }


# =========================================================
# SHARED ORDER-LIST TABLE (same look on every stage page)
# =========================================================

_LIST_COLS = [1.4, 2.0, 1.2, 0.9, 0.9, 0.9, 1.3, 1.0]


def render_order_rows(rows: list[dict], tab_key: str, open_key_prefix: str, active_state_key: str, done_col_label: str, top_list: int = TOP_LIST) -> None:

    if not rows:

        st.info("Koi Sales Order nahi mila.")

        return

    shown = rows[:top_list]

    header = st.columns(_LIST_COLS)

    for col, label in zip(header, ["Order ID", "Customer", "Warehouse", "SKUs", "Ordered", done_col_label, "Status", "Action"]):

        col.markdown(f'<div class="gl-head">{label}</div>', unsafe_allow_html=True)

    for r in shown:

        c = st.columns(_LIST_COLS)

        c[0].markdown(f'<div class="gl-order">{esc(r["order_id"])}</div>', unsafe_allow_html=True)

        c[1].markdown(
            f'<div class="gl-cell">{esc(r["customer"]) or "-"}<br>'
            f'<span style="color:#64748b;font-size:0.75rem;">{esc(r["phone"])}</span></div>',
            unsafe_allow_html=True,
        )

        c[2].markdown(f'<div class="gl-cell">{esc(r["warehouse"]) or "-"}</div>', unsafe_allow_html=True)

        c[3].markdown(f'<div class="gl-num">{r["sku_count"]}</div>', unsafe_allow_html=True)

        c[4].markdown(f'<div class="gl-num">{fmt_qty(r["ordered"])}</div>', unsafe_allow_html=True)

        c[5].markdown(f'<div class="gl-num">{fmt_qty(r["done"])}</div>', unsafe_allow_html=True)

        c[6].markdown(
            f'<span class="gl-badge gl-badge-{r["status_kind"]}">{esc(r["status"])}</span>',
            unsafe_allow_html=True,
        )

        with c[7]:

            label = "View" if r["status_kind"] == "done" else "Open ▶"

            if st.button(label, key=f"{open_key_prefix}_{tab_key}_{r['order_id']}", use_container_width=True):

                st.session_state[active_state_key] = r["order_id"]

                st.rerun()

        st.markdown('<div class="gl-sep"></div>', unsafe_allow_html=True)

    if len(rows) > top_list:

        st.caption(f"Pehle {top_list} orders dikh rahe hain (total {len(rows)}). Baaki dekhne ke liye upar search karo.")


def render_stage_order_list(orders: list[dict], summaries_fn, search_key: str, open_key_prefix: str, active_state_key: str, done_col_label: str, done_tab_label: str) -> None:
    """
    orders: raw sales_orders rows (already filtered for CANCELLED etc by caller)
    summaries_fn: () -> list[dict] of already-built summary dicts
                  (see build_summary_from_items / build_summary_from_baseline)
    """

    render_html('<div class="go-section">📋 SALES ORDERS</div>')

    search = st.text_input(
        "Search Sales Order",
        placeholder="Search Order ID, Customer, Phone or Warehouse...",
        label_visibility="collapsed",
        key=search_key,
    ).strip().lower()

    summaries = summaries_fn()

    if search:

        filtered = []

        for r in summaries:

            searchable = " ".join([r["order_id"], r["customer"], r["phone"], r["warehouse"]]).lower()

            if search in searchable:

                filtered.append(r)

        summaries = filtered

    pending_rows = [r for r in summaries if r["status_kind"] != "done"]

    done_rows = [r for r in summaries if r["status_kind"] == "done"]

    tab_pending, tab_done = st.tabs([
        f"⏳ Pending ({len(pending_rows)})",
        f"✅ {done_tab_label} ({len(done_rows)})",
    ])

    with tab_pending:

        render_order_rows(pending_rows, "pending", open_key_prefix, active_state_key, done_col_label)

    with tab_done:

        render_order_rows(done_rows, "done", open_key_prefix, active_state_key, done_col_label)
