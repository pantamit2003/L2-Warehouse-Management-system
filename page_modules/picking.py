"""
page_modules/picking.py

EMIZA WMS — Stage 1: System Picking

Flow:

Picking
   ↓
Select Sales Order
   ↓
ALL SKUs of selected Sales Order shown together
   ↓
Ordered / Already Picked / Pending Picking / Available Stock
   ↓
Allocate SKU
   ↓
Assigned Locations
   ↓
Warehouse + Location + Current Stock
   ↓
Pick Quantity
   ↓
Add
   ↓
Picking Review
   ↓
Save Picking
   ↓
picking table ONLY (no inventory_transactions, no location_master update)

IMPORTANT:
- Picking does NOT create inventory_transactions.
- Picking does NOT modify location_master.qty.
- Picking is the ONLY outbound stage that needs location_master +
  inventory_transactions, because it decides WHERE stock will come from.
- Because DB stock is never deducted at Picking time, this module tracks
  "committed but not yet shipped" qty per (sku_code, location) GLOBALLY
  (across every Sales Order), so two different orders can never be
  allocated the same physical units. Committed-not-shipped =
      total picked_qty ever recorded in `picking` for that (sku, location)
      - total OUT qty ever recorded in inventory_transactions for that
        (sku, location)
  Available-for-new-picking at a location = current_stock - committed_not_shipped
- The per-location breakdown saved here is exactly what Packing / Dispatched
  will use later; it must not be lost.
- RETURN-PATH: if this page was opened via a jump from another stage
  (e.g. the "Open →" button on Dispatched's process card), a
  "picking_return_page" / "picking_return_order" pair is set in session
  state. Both "Back To Order List" and a successful Save then navigate
  straight back to that origin page/order instead of Picking's own list.
- No st.fragment.
"""

from __future__ import annotations

import streamlit as st

from auth import get_client

from page_modules.outbound_common import (
    TOP_LIST,
    s,
    f,
    fmt_qty,
    esc,
    render_html,
    processing_overlay_html,
    inject_css,
    load_sales_orders,
    load_sales_order_items,
    load_all_order_items,
    get_ordered_qty,
    load_sku_locations,
    load_sku_transactions,
    get_location_stock,
    get_total_stock,
    load_picking_lines,
    clear_common_caches,
    load_grouped_totals,
    build_summary_from_items,
    render_stage_order_list,
)

PROCESSING_TITLE = "Processing Picking..."


# =========================================================
# SESSION STATE
# =========================================================

def _init_state() -> None:

    defaults = {
        "picking_active_order": None,
        "picking_items": [],
        "picking_success": False,
        "picking_error": "",
        "picking_show_overlay": False,
    }

    for key, value in defaults.items():

        if key not in st.session_state:

            st.session_state[key] = value


def _reset_form() -> None:

    for key in [
        "picking_active_order",
        "picking_items",
        "picking_success",
        "picking_error",
        "picking_return_page",
        "picking_return_order",
    ]:

        st.session_state.pop(key, None)

    _init_state()


def _go_back_to_origin_or_list() -> None:
    """
    Used by "Back To Order List" and by a successful Save. If this page was
    opened via a jump from another stage (Dispatched's process cards), send
    the user straight back to that origin order instead of Picking's own
    order list.
    """

    return_page = st.session_state.pop("picking_return_page", None)
    return_order = st.session_state.pop("picking_return_order", None)

    st.session_state.picking_active_order = None

    if return_page:

        st.session_state["current_page"] = return_page

        if return_page == "Gate Out":

            st.session_state["gate_out_active_order"] = return_order


# =========================================================
# GLOBAL COMMITTED (PICKED-NOT-SHIPPED) PER (SKU, LOCATION)
# =========================================================

@st.cache_data(ttl=20, show_spinner=False)
def _load_committed_picked_by_location() -> dict:
    """
    Total picked_qty ever recorded in `picking`, grouped by
    (sku_code, location) — across ALL Sales Orders.
    """

    return load_grouped_totals(
        "picking",
        "picked_qty",
        ("sku_code", "location"),
    )


@st.cache_data(ttl=20, show_spinner=False)
def _load_out_by_sku_location() -> dict:
    """
    Total OUT qty ever recorded in inventory_transactions,
    grouped by (sku, location) — across ALL Sales Orders.
    """

    return load_grouped_totals(
        "inventory_transactions",
        "qty",
        ("sku", "location"),
        filters={"transaction_type": "OUT"},
    )


def _clear_picking_caches() -> None:

    clear_common_caches()

    _load_committed_picked_by_location.clear()
    _load_out_by_sku_location.clear()

    # Also invalidate Gate Out's own cached progress numbers, so a jump
    # back to Gate Out right after saving shows fresh Picking progress
    # immediately instead of a stale cached value.
    try:

        from page_modules.gate_out import clear_gate_out_caches

        clear_gate_out_caches()

    except Exception:

        pass


def _available_for_new_picking(
    sku_code: str,
    location: str,
    location_data: list[dict],
    transaction_data: list[dict],
    committed: dict,
    out_totals: dict,
) -> float:
    """
    current_stock(location) - (committed_not_shipped at this sku+location)

    committed_not_shipped = total ever picked at (sku, location)
                             - total OUT ever at (sku, location)
    """

    current_stock = get_location_stock(
        location,
        location_data,
        transaction_data,
    )

    key = (s(sku_code), s(location))

    committed_qty = committed.get(key, 0.0)
    out_qty = out_totals.get(key, 0.0)

    committed_not_shipped = max(0.0, committed_qty - out_qty)

    return max(0.0, current_stock - committed_not_shipped)


# =========================================================
# ALREADY PICKED (for THIS order+sku, from picking table)
# =========================================================

def _get_already_picked_qty(
    picking_lines: dict,
    order_id: str,
    sku_code: str,
) -> float:

    rows = picking_lines.get((s(order_id), s(sku_code)), [])

    return sum(f(r.get("picked_qty")) for r in rows)


def _get_already_picked_at_location(
    picking_lines: dict,
    order_id: str,
    sku_code: str,
    location: str,
) -> float:

    rows = picking_lines.get((s(order_id), s(sku_code)), [])

    return sum(
        f(r.get("picked_qty"))
        for r in rows
        if s(r.get("location")) == s(location)
    )


# =========================================================
# CURRENT FORM (unsaved, this session) HELPERS
# =========================================================

def _get_form_qty(order_id: str, sku_code: str) -> float:

    return sum(
        f(item["qty"])
        for item in st.session_state.picking_items
        if item["order_id"] == order_id and item["sku_code"] == sku_code
    )


def _get_form_location_qty(order_id: str, sku_code: str, location: str) -> float:

    return sum(
        f(item["qty"])
        for item in st.session_state.picking_items
        if item["order_id"] == order_id
        and item["sku_code"] == sku_code
        and item["location"] == location
    )


def _add_picking_item(
    order_id: str,
    sku_code: str,
    location: str,
    warehouse: str,
    qty: float,
    available_at_location: float,
    pending_qty: float,
) -> bool:

    if not order_id:
        st.session_state.picking_error = "Please select a Sales Order."
        return False

    if not sku_code:
        st.session_state.picking_error = "Please select a SKU."
        return False

    if not location:
        st.session_state.picking_error = "Please select a Location."
        return False

    if qty <= 0:
        st.session_state.picking_error = "Pick quantity must be greater than 0."
        return False

    if qty > available_at_location:
        st.session_state.picking_error = (
            f"Only {fmt_qty(available_at_location)} units are available "
            f"to pick at {location}."
        )
        return False

    if qty > pending_qty:
        st.session_state.picking_error = (
            f"Only {fmt_qty(pending_qty)} units are pending for {sku_code}."
        )
        return False

    st.session_state.picking_items.append(
        {
            "order_id": order_id,
            "sku_code": sku_code,
            "location": location,
            "warehouse": warehouse,
            "qty": qty,
        }
    )

    st.session_state.picking_error = ""

    return True


# =========================================================
# SAVE PICKING
# =========================================================

def _save_picking(items: list[dict], picked_by: str) -> tuple[bool, str | None]:

    if not items:
        return False, "Please add at least one Picking item."

    client = get_client()

    try:

        unique_skus = list(dict.fromkeys(item["sku_code"] for item in items))

        # -----------------------------------------------
        # FRESH DATA (re-fetch, don't trust session state)
        # -----------------------------------------------

        fresh_transactions = {}
        fresh_locations = {}

        for sku_code in unique_skus:

            tx_response = (
                client.table("inventory_transactions")
                .select("id,transaction_type,po_number,sku,location,qty")
                .eq("sku", sku_code)
                .execute()
            )

            fresh_transactions[sku_code] = tx_response.data or []

            loc_response = (
                client.table("location_master")
                .select("wh_location,location,sku,qty")
                .eq("sku", sku_code)
                .execute()
            )

            fresh_locations[sku_code] = loc_response.data or []

        fresh_committed = load_grouped_totals(
            "picking", "picked_qty", ("sku_code", "location")
        )

        fresh_out = load_grouped_totals(
            "inventory_transactions",
            "qty",
            ("sku", "location"),
            filters={"transaction_type": "OUT"},
        )

        order_sku_pairs = list(
            dict.fromkeys((item["order_id"], item["sku_code"]) for item in items)
        )

        # -----------------------------------------------
        # VALIDATE EVERY ORDER / SKU
        # -----------------------------------------------

        for order_id, sku_code in order_sku_pairs:

            sku_items = [
                item
                for item in items
                if item["order_id"] == order_id and item["sku_code"] == sku_code
            ]

            # Sales Order must exist and not be cancelled
            order_response = (
                client.table("sales_orders")
                .select("id,status")
                .eq("order_id", order_id)
                .single()
                .execute()
            )

            if not order_response.data:
                return False, f"Sales Order {order_id} not found."

            if s(order_response.data.get("status")).upper() == "CANCELLED":
                return False, f"Sales Order {order_id} is CANCELLED."

            sales_order_db_id = order_response.data["id"]

            # Ordered qty
            item_response = (
                client.table("sales_order_items")
                .select("quantity")
                .eq("sales_order_id", sales_order_db_id)
                .eq("sku_code", sku_code)
                .execute()
            )

            ordered_qty = sum(
                f(row.get("quantity")) for row in (item_response.data or [])
            )

            # Already picked for this order+sku (fresh)
            picking_response = (
                client.table("picking")
                .select("picked_qty")
                .eq("order_id", order_id)
                .eq("sku_code", sku_code)
                .execute()
            )

            already_picked = sum(
                f(row.get("picked_qty")) for row in (picking_response.data or [])
            )

            requested_qty = sum(f(item["qty"]) for item in sku_items)

            pending_qty = ordered_qty - already_picked

            if requested_qty > pending_qty:
                return False, (
                    f"{order_id} / {sku_code}: only {fmt_qty(pending_qty)} "
                    f"units are pending, but {fmt_qty(requested_qty)} were requested."
                )

            # Assigned locations for this SKU
            assigned_locations = {
                s(row.get("location"))
                for row in fresh_locations[sku_code]
                if s(row.get("location"))
            }

            location_data = fresh_locations[sku_code]
            transaction_data = fresh_transactions[sku_code]

            unique_locations = list(
                dict.fromkeys(item["location"] for item in sku_items)
            )

            for location in unique_locations:

                if location not in assigned_locations:
                    return False, f"{location} is not assigned to SKU {sku_code}."

                requested_at_location = sum(
                    f(item["qty"]) for item in sku_items if item["location"] == location
                )

                available = _available_for_new_picking(
                    sku_code,
                    location,
                    location_data,
                    transaction_data,
                    fresh_committed,
                    fresh_out,
                )

                if requested_at_location > available:
                    return False, (
                        f"{sku_code} at {location}: only {fmt_qty(available)} "
                        f"units are available to pick, but "
                        f"{fmt_qty(requested_at_location)} requested."
                    )

        # -----------------------------------------------
        # INSERT
        # -----------------------------------------------

        rows = []

        for item in items:

            rows.append(
                {
                    "order_id": item["order_id"],
                    "sku_code": item["sku_code"],
                    "warehouse": item.get("warehouse") or "",
                    "location": item["location"],
                    "picked_qty": item["qty"],
                    "picked_by": picked_by,
                }
            )

        client.table("picking").insert(rows).execute()

        _clear_picking_caches()

        return True, None

    except Exception as e:

        return False, str(e)


# =========================================================
# ORDER LIST VIEW
# =========================================================

def _render_order_list(orders: list[dict]) -> None:

    items_by_order = load_all_order_items()

    def summaries_fn() -> list[dict]:

        picked_totals = load_grouped_totals(
            "picking", "picked_qty", ("order_id", "sku_code")
        )

        out = []

        for order in orders:

            if not s(order.get("order_id")):
                continue

            if s(order.get("status")).upper() == "CANCELLED":
                continue

            out.append(
                build_summary_from_items(
                    order,
                    items_by_order.get(order["id"], []),
                    picked_totals,
                    "PICKED",
                )
            )

        return out

    render_stage_order_list(
        orders,
        summaries_fn,
        search_key="picking_search",
        open_key_prefix="pk_open",
        active_state_key="picking_active_order",
        done_col_label="Picked",
        done_tab_label="Picked",
    )


# =========================================================
# ORDER DETAIL VIEW
# =========================================================

def _render_order_detail(selected_order: dict, selected_order_id: str) -> None:

    if st.button("⬅ Back To Order List", key="pk_back_list"):

        _go_back_to_origin_or_list()
        st.rerun()

    c1, c2, c3 = st.columns(3)

    with c1:
        render_html(
            f"""
            <div class="go-info">
                <div class="go-info-label">Order ID</div>
                <div class="go-info-value">{esc(selected_order.get("order_id"))}</div>
            </div>
            """
        )

    with c2:
        render_html(
            f"""
            <div class="go-info">
                <div class="go-info-label">Customer</div>
                <div class="go-info-value">{esc(selected_order.get("customer_name"))}</div>
            </div>
            """
        )

    with c3:
        render_html(
            f"""
            <div class="go-info">
                <div class="go-info-label">Warehouse</div>
                <div class="go-info-value">{esc(selected_order.get("warehouse"))}</div>
            </div>
            """
        )

    sales_order_db_id = selected_order["id"]

    order_items = load_sales_order_items(sales_order_db_id)

    if not order_items:
        st.warning("No SKU items found in this Sales Order.")
        return

    sku_list = list(
        dict.fromkeys(
            s(item.get("sku_code")) for item in order_items if s(item.get("sku_code"))
        )
    )

    picking_lines = load_picking_lines()
    committed = _load_committed_picked_by_location()
    out_totals = _load_out_by_sku_location()

    render_html('<div class="go-section" style="margin-top:1.5rem;">📦 ORDER SKUs</div>')

    for sku_index, sku_code in enumerate(sku_list):

        location_data = load_sku_locations(sku_code)
        transaction_data = load_sku_transactions(sku_code)

        ordered_qty = get_ordered_qty(order_items, sku_code)

        already_picked = _get_already_picked_qty(
            picking_lines, selected_order_id, sku_code
        )

        current_form_qty = _get_form_qty(selected_order_id, sku_code)

        pending_qty = max(0.0, ordered_qty - already_picked - current_form_qty)

        total_stock = get_total_stock(location_data, transaction_data)

        render_html(
            f"""
            <div class="go-sku-card">
                <div class="go-sku-code">📦 {esc(sku_code)}</div>
            </div>
            """
        )

        c1, c2, c3, c4 = st.columns(4)

        with c1:
            render_html(
                f"""
                <div class="go-info">
                    <div class="go-info-label">Ordered</div>
                    <div class="go-info-value">{fmt_qty(ordered_qty)}</div>
                </div>
                """
            )

        with c2:
            render_html(
                f"""
                <div class="go-info">
                    <div class="go-info-label">Already Picked</div>
                    <div class="go-info-value">{fmt_qty(already_picked)}</div>
                </div>
                """
            )

        with c3:
            render_html(
                f"""
                <div class="go-pending">
                    <div style="font-size:0.72rem;">PENDING PICKING</div>
                    <div style="font-size:1rem;margin-top:0.15rem;">{fmt_qty(pending_qty)}</div>
                </div>
                """
            )

        with c4:
            render_html(
                f"""
                <div class="go-stock">
                    <div style="font-size:0.72rem;">TOTAL STOCK (raw)</div>
                    <div style="font-size:1rem;margin-top:0.15rem;">{fmt_qty(total_stock)}</div>
                </div>
                """
            )

        if pending_qty <= 0:
            render_html(
                f'<div class="go-dispatched">✅ {esc(sku_code)} is fully picked.</div>'
            )
            continue

        assigned_location_rows = []
        seen = set()

        for row in location_data:

            location = s(row.get("location"))

            if not location or location in seen:
                continue

            seen.add(location)
            assigned_location_rows.append(row)

        if not assigned_location_rows:
            st.warning(f"No location is assigned to {sku_code}.")
            continue

        with st.expander(f"📍 Allocate {sku_code}", expanded=True):

            render_html(
                '<div style="font-size:0.9rem;font-weight:700;color:#374151;'
                'margin-bottom:0.7rem;">Assigned Locations</div>'
            )

            # -------------------------------------------
            # FULLY ALLOCATE
            # -------------------------------------------

            if st.button(
                f"⚡ Fully Allocate ({fmt_qty(pending_qty)})",
                type="primary",
                key=f"pk_full_{selected_order_id}_{sku_code}",
            ):

                remaining = max(
                    0.0,
                    ordered_qty
                    - already_picked
                    - _get_form_qty(selected_order_id, sku_code),
                )

                allocated_any = False

                for alloc_row in assigned_location_rows:

                    if remaining <= 0:
                        break

                    alloc_location = s(alloc_row.get("location"))

                    alloc_warehouse = s(alloc_row.get("wh_location")) or s(
                        selected_order.get("warehouse")
                    )

                    alloc_available = _available_for_new_picking(
                        sku_code,
                        alloc_location,
                        location_data,
                        transaction_data,
                        committed,
                        out_totals,
                    )

                    alloc_available = max(
                        0.0,
                        alloc_available
                        - _get_form_location_qty(
                            selected_order_id, sku_code, alloc_location
                        ),
                    )

                    take = min(remaining, alloc_available)

                    if take <= 0:
                        continue

                    if _add_picking_item(
                        selected_order_id,
                        sku_code,
                        alloc_location,
                        alloc_warehouse,
                        take,
                        alloc_available,
                        remaining,
                    ):
                        remaining -= take
                        allocated_any = True

                if allocated_any:

                    if remaining > 0:
                        st.session_state.picking_error = (
                            f"{sku_code}: available stock kam tha, "
                            f"{fmt_qty(remaining)} units abhi bhi pending hain."
                        )

                    st.session_state.picking_clear_prefixes = [
                        f"pk_qty_{selected_order_id}_{sku_code}_"
                    ]

                    st.rerun()

            # -------------------------------------------
            # LOCATION ROWS
            # -------------------------------------------

            for location_index, location_row in enumerate(assigned_location_rows):

                location = s(location_row.get("location"))

                warehouse = s(location_row.get("wh_location")) or s(
                    selected_order.get("warehouse")
                )

                raw_stock = get_location_stock(location, location_data, transaction_data)

                available_global = _available_for_new_picking(
                    sku_code,
                    location,
                    location_data,
                    transaction_data,
                    committed,
                    out_totals,
                )

                already_in_form_here = _get_form_location_qty(
                    selected_order_id, sku_code, location
                )

                available_for_this_form = max(0.0, available_global - already_in_form_here)

                c1, c2, c3 = st.columns([3.2, 2.0, 2.0])

                with c1:
                    render_html(
                        f"""
                        <div class="go-location-card">
                            <div class="go-location-name">📍 {esc(location)}</div>
                            <div class="go-location-warehouse">🏭 Warehouse: {esc(warehouse) or "-"}</div>
                        </div>
                        """
                    )

                with c2:
                    render_html(
                        f"""
                        <div class="go-location-card">
                            <div class="go-location-stock">Raw Stock: {fmt_qty(raw_stock)}</div>
                            <div style="color:#64748b;font-size:0.72rem;margin-top:0.25rem;">
                                Available to pick: {fmt_qty(available_for_this_form)}
                            </div>
                        </div>
                        """
                    )

                with c3:

                    max_qty = max(0.0, min(pending_qty, available_for_this_form))

                    if max_qty > 0:

                        location_qty = st.number_input(
                            "Pick Qty",
                            min_value=0.0,
                            max_value=float(max_qty),
                            value=0.0,
                            step=1.0,
                            key=f"pk_qty_{selected_order_id}_{sku_code}_{location_index}",
                        )

                    else:

                        location_qty = 0.0
                        st.caption("No stock available")

                if location_qty > 0:

                    if st.button(
                        "➕ Add",
                        type="primary",
                        use_container_width=True,
                        key=f"pk_add_{selected_order_id}_{sku_code}_{location_index}",
                    ):

                        latest_pending = max(
                            0.0,
                            ordered_qty
                            - already_picked
                            - _get_form_qty(selected_order_id, sku_code),
                        )

                        latest_available_global = _available_for_new_picking(
                            sku_code,
                            location,
                            location_data,
                            transaction_data,
                            committed,
                            out_totals,
                        )

                        latest_available = max(
                            0.0,
                            latest_available_global
                            - _get_form_location_qty(
                                selected_order_id, sku_code, location
                            ),
                        )

                        if location_qty > latest_pending:
                            st.error(
                                f"Only {fmt_qty(latest_pending)} units are "
                                f"pending for {sku_code}."
                            )

                        elif location_qty > latest_available:
                            st.error(
                                f"Only {fmt_qty(latest_available)} units are "
                                f"available to pick at {location}."
                            )

                        else:

                            added = _add_picking_item(
                                selected_order_id,
                                sku_code,
                                location,
                                warehouse,
                                location_qty,
                                latest_available,
                                latest_pending,
                            )

                            if added:

                                st.session_state.picking_clear_exact = [
                                    f"pk_qty_{selected_order_id}_{sku_code}_{location_index}"
                                ]

                                st.rerun()

        if sku_index < len(sku_list) - 1:
            render_html('<div class="go-divider"></div>')

    # =====================================================
    # PICKING REVIEW
    # =====================================================

    selected_review_items = [
        item
        for item in st.session_state.picking_items
        if item["order_id"] == selected_order_id
    ]

    if selected_review_items:

        render_html('<div class="go-section" style="margin-top:1.5rem;">📋 PICKING REVIEW</div>')

        c1, c2, c3, c4 = st.columns([3, 3, 1.5, 0.8])

        with c1:
            st.markdown("**SKU**")

        with c2:
            st.markdown("**WAREHOUSE / LOCATION**")

        with c3:
            st.markdown("**QTY**")

        with c4:
            st.markdown("**REMOVE**")

        for item in selected_review_items:

            actual_index = st.session_state.picking_items.index(item)

            c1, c2, c3, c4 = st.columns([3, 3, 1.5, 0.8])

            with c1:
                render_html(
                    f"""
                    <div class="go-review">
                        <div class="go-review-label">SKU</div>
                        <div class="go-review-value">{esc(item["sku_code"])}</div>
                    </div>
                    """
                )

            with c2:
                render_html(
                    f"""
                    <div class="go-review">
                        <div class="go-review-label">Warehouse / Location</div>
                        <div class="go-review-value">🏭 {esc(item.get("warehouse"))}</div>
                        <div style="color:#0284c7;font-size:0.8rem;font-weight:600;margin-top:0.25rem;">
                            📍 {esc(item["location"])}
                        </div>
                    </div>
                    """
                )

            with c3:
                render_html(
                    f"""
                    <div class="go-review">
                        <div class="go-review-label">QTY</div>
                        <div class="go-review-value">{fmt_qty(item["qty"])}</div>
                    </div>
                    """
                )

            with c4:

                if st.button("🗑", key=f"pk_remove_{actual_index}"):

                    st.session_state.picking_items.pop(actual_index)
                    st.rerun()

        total_review_qty = sum(f(item["qty"]) for item in selected_review_items)

        render_html(
            f"""
            <div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;
                        padding:0.9rem 1rem;margin-top:0.8rem;margin-bottom:0.8rem;
                        color:#1e3a8a;font-weight:600;">
                Total Picking Quantity: {fmt_qty(total_review_qty)}
            </div>
            """
        )

        if st.session_state.picking_error:
            st.error(st.session_state.picking_error)

        if st.button(
            "✅ Save Picking",
            type="primary",
            use_container_width=True,
            key="save_picking",
        ):

            processing_placeholder = st.empty()

            processing_placeholder.markdown(
                processing_overlay_html(PROCESSING_TITLE),
                unsafe_allow_html=True,
            )

            picked_by = st.session_state.get("username", "")

            success, error = _save_picking(selected_review_items, picked_by)

            if success:

                st.session_state.picking_items = [
                    i
                    for i in st.session_state.picking_items
                    if i["order_id"] != selected_order_id
                ]

                st.session_state.picking_success = True
                st.session_state.picking_error = ""
                st.session_state.picking_clear_prefixes = ["pk_qty_"]
                st.session_state.picking_show_overlay = True

                _go_back_to_origin_or_list()

                st.rerun()

            else:

                processing_placeholder.empty()

                st.session_state.picking_error = error or "Unknown error"

                st.error(f"❌ Picking save failed: {error}")


# =========================================================
# MAIN PAGE BODY
# =========================================================

def _render_picking_body(on_back=None) -> None:

    _init_state()

    inject_css()

    prefixes = st.session_state.pop("picking_clear_prefixes", None)

    if prefixes:

        for key in list(st.session_state.keys()):

            if isinstance(key, str) and key.startswith(tuple(prefixes)):

                st.session_state.pop(key, None)

    exact_keys = st.session_state.pop("picking_clear_exact", None)

    if exact_keys:

        for key in exact_keys:

            st.session_state.pop(key, None)

    render_html('<div class="go-title">🧾 Picking</div>')

    if on_back:

        if st.button("⬅ Back To Home", key="pk_back"):

            _reset_form()
            on_back()
            st.rerun()

    st.divider()

    if st.session_state.picking_success:

        st.success("🎉 Picking Saved Successfully!")
        st.session_state.picking_success = False

    orders = load_sales_orders()

    if not orders:
        st.info("No Sales Orders found.")
        return

    active_id = st.session_state.picking_active_order

    active_order = None

    if active_id:

        active_order = next(
            (o for o in orders if s(o.get("order_id")) == s(active_id)),
            None,
        )

    if active_order:

        _render_order_detail(active_order, s(active_order.get("order_id")))

    else:

        st.session_state.picking_active_order = None
        _render_order_list(orders)


# =========================================================
# ENTRY POINT
# =========================================================

def render_picking(on_back=None) -> None:

    overlay = None

    if st.session_state.pop("picking_show_overlay", False):

        overlay = st.empty()

        overlay.markdown(
            processing_overlay_html(PROCESSING_TITLE),
            unsafe_allow_html=True,
        )

    try:

        _render_picking_body(on_back)

    finally:

        if overlay is not None:

            overlay.empty()
