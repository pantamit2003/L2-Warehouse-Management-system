"""
page_modules/packing.py

EMIZA WMS — Stage 2 (NEW, per v2 redesign): Packing

Flow:

Packing
   ↓
Select Sales Order
   ↓
ALL SKUs of selected Sales Order shown together (baseline = Picking table,
same per-location breakdown Picking already produced)
   ↓
Ordered / Already Picked (Picking) / Already Packed / Pending Packing
   ↓
Confirm Packed Qty per ORIGINAL PICKING LOCATION (location breakdown is
needed because THIS stage is now where the OUT transaction is created)
   ↓
Add
   ↓
Packing Review
   ↓
Save Packing
   ↓
1) `packing` table  (id, order_id, sku_code, location, packed_qty,
                      packed_by, packed_at)
   -> new unified table, REPLACES physical_picking + physical_packing +
      packing_done for anything going forward.
2) `inventory_transactions` -> OUT   (ONLY place stock is deducted now)

IMPORTANT — per the v2 outbound redesign:
- Packing is the ONLY place inventory_transactions OUT gets created.
  Dispatched (gate_out.py) does NOT insert a second OUT row.
- Packing does NOT touch location_master.qty directly — same hard rule
  as before, only inventory_transactions rows are ever inserted.
- Packing uses the ORIGINAL Picking location breakdown (`picking` table)
  exactly like the old gate_out.py did — it does not re-allocate stock,
  it only confirms how much of what was already picked is now packed
  and shipped out.
- Packed Qty for a SKU is capped by: Picking qty for that SKU minus
  whatever has already been Packed (packing table) for that SKU.
- Packed Qty for a given original picking location is further capped by:
  what was originally picked at that location minus whatever has already
  been Packed from that specific location for this order+sku.
- Fresh re-validation against the DB happens right before insert, exactly
  like the old gate_out.py's _save_gate_out.
- No st.fragment.
"""

from __future__ import annotations

import streamlit as st

from auth import get_client
from page_modules.email_service import send_gate_out_email

from page_modules.outbound_common import (
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
    load_picking_lines,
    clear_common_caches,
    load_grouped_totals,
    build_summary_from_items,
    render_stage_order_list,
)

PROCESSING_TITLE = "Processing Packing..."

# Set this to False once/if the Accounts email trigger point is confirmed
# to stay at Dispatched instead. Kept as a single flag so it's a one-line
# change either way.
SEND_EMAIL_AT_PACKING = True


# =========================================================
# SESSION STATE
# =========================================================

def _init_state() -> None:

    defaults = {
        "packing_active_order": None,
        "packing_items": [],
        "packing_success": False,
        "packing_error": "",
        "packing_email_sent": False,
        "packing_email_error": "",
        "packing_show_overlay": False,
    }

    for key, value in defaults.items():

        if key not in st.session_state:

            st.session_state[key] = value


def _reset_form() -> None:

    for key in [
        "packing_active_order",
        "packing_items",
        "packing_success",
        "packing_error",
        "packing_email_sent",
        "packing_email_error",
        "packing_return_page",
        "packing_return_order",
    ]:

        st.session_state.pop(key, None)

    _init_state()


def _go_back_to_origin_or_list() -> None:
    """
    Used by "Back To Order List" and by a successful Save. If this page was
    opened via a jump from another stage (Dispatched's process cards), send
    the user straight back to that origin order instead of Packing's own
    order list.
    """

    return_page = st.session_state.pop("packing_return_page", None)
    return_order = st.session_state.pop("packing_return_order", None)

    st.session_state.packing_active_order = None

    if return_page:

        st.session_state["current_page"] = return_page

        if return_page == "Gate Out":

            st.session_state["gate_out_active_order"] = return_order


# =========================================================
# LOADERS
# =========================================================

@st.cache_data(ttl=20, show_spinner=False)
def _load_packed_totals_by_order_sku() -> dict:
    """(order_id, sku_code) -> total Packed qty ever recorded in `packing`."""

    return load_grouped_totals(
        "packing", "packed_qty", ("order_id", "sku_code")
    )


@st.cache_data(ttl=20, show_spinner=False)
def _load_packed_totals_by_order_sku_location() -> dict:
    """(order_id, sku_code, location) -> total Packed qty already recorded
    from that exact original picking location, for this order+sku."""

    return load_grouped_totals(
        "packing", "packed_qty", ("order_id", "sku_code", "location")
    )


def _clear_packing_caches() -> None:
    clear_common_caches()

    _load_packed_totals_by_order_sku.clear()
    _load_packed_totals_by_order_sku_location.clear()

    try:
        from page_modules.gate_out import clear_gate_out_caches
        clear_gate_out_caches()
    except Exception:
        pass

    try:
        from page_modules.dispatch import clear_dispatch_caches
        clear_dispatch_caches()
    except Exception:
        pass


# =========================================================
# CURRENT FORM (unsaved, this session) HELPERS
# =========================================================

def _get_form_qty(order_id: str, sku_code: str) -> float:

    return sum(
        f(item["qty"])
        for item in st.session_state.packing_items
        if item["order_id"] == order_id and item["sku_code"] == sku_code
    )


def _get_form_location_qty(order_id: str, sku_code: str, location: str) -> float:

    return sum(
        f(item["qty"])
        for item in st.session_state.packing_items
        if item["order_id"] == order_id
        and item["sku_code"] == sku_code
        and item["location"] == location
    )


def _add_packing_item(
    order_id: str,
    sku_code: str,
    location: str,
    warehouse: str,
    qty: float,
    available_at_location: float,
    pending_qty: float,
) -> bool:

    if not order_id:
        st.session_state.packing_error = "Please select a Sales Order."
        return False

    if not sku_code:
        st.session_state.packing_error = "Please select a SKU."
        return False

    if not location:
        st.session_state.packing_error = "Please select a Location."
        return False

    if qty <= 0:
        st.session_state.packing_error = "Packed quantity must be greater than 0."
        return False

    if qty > available_at_location:
        st.session_state.packing_error = (
            f"Only {fmt_qty(available_at_location)} units of the ORIGINAL "
            f"Picking commitment remain at {location}."
        )
        return False

    if qty > pending_qty:
        st.session_state.packing_error = (
            f"Only {fmt_qty(pending_qty)} units are pending "
            f"(Picked but not yet Packed) for {sku_code}."
        )
        return False

    st.session_state.packing_items.append(
        {
            "order_id": order_id,
            "sku_code": sku_code,
            "location": location,
            "warehouse": warehouse,
            "qty": qty,
        }
    )

    st.session_state.packing_error = ""

    return True


# =========================================================
# SAVE PACKING  (packing table + inventory_transactions OUT)
# =========================================================

def _save_packing(items: list[dict], packed_by: str) -> tuple[bool, str | None]:

    if not items:
        return False, "Please add at least one Packing item."

    client = get_client()

    try:

        order_sku_pairs = list(
            dict.fromkeys((item["order_id"], item["sku_code"]) for item in items)
        )

        # -----------------------------------------------
        # VALIDATE EVERY ORDER / SKU / LOCATION (fresh)
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

            # Fresh already-Packed total for this sku
            packed_response = (
                client.table("packing")
                .select("location,packed_qty")
                .eq("order_id", order_id)
                .eq("sku_code", sku_code)
                .execute()
            )

            already_packed_rows = packed_response.data or []

            already_packed_total = sum(f(r.get("packed_qty")) for r in already_packed_rows)

            already_packed_by_location: dict = {}

            for r in already_packed_rows:

                loc = s(r.get("location"))

                already_packed_by_location[loc] = already_packed_by_location.get(
                    loc, 0.0
                ) + f(r.get("packed_qty"))

            # Fresh ORIGINAL picking breakdown for this sku (the cap)
            picking_response = (
                client.table("picking")
                .select("location,warehouse,picked_qty")
                .eq("order_id", order_id)
                .eq("sku_code", sku_code)
                .execute()
            )

            picked_by_location: dict = {}

            for row in picking_response.data or []:

                loc = s(row.get("location"))

                picked_by_location[loc] = picked_by_location.get(loc, 0.0) + f(
                    row.get("picked_qty")
                )

            total_picked = sum(picked_by_location.values())

            requested_qty = sum(f(item["qty"]) for item in sku_items)

            pending_qty = total_picked - already_packed_total

            if requested_qty > pending_qty:
                return False, (
                    f"{order_id} / {sku_code}: only {fmt_qty(pending_qty)} "
                    f"units are pending (Picked but not yet Packed), "
                    f"but {fmt_qty(requested_qty)} were requested."
                )

            unique_locations = list(
                dict.fromkeys(item["location"] for item in sku_items)
            )

            for location in unique_locations:

                if location not in picked_by_location:
                    return False, (
                        f"{location} was never in the original Picking "
                        f"breakdown for {sku_code} on {order_id}."
                    )

                requested_at_location = sum(
                    f(item["qty"]) for item in sku_items if item["location"] == location
                )

                picked_qty_here = picked_by_location.get(location, 0.0)

                already_packed_here = already_packed_by_location.get(location, 0.0)

                available_here = picked_qty_here - already_packed_here

                if requested_at_location > available_here:
                    return False, (
                        f"{sku_code} at {location}: only "
                        f"{fmt_qty(available_here)} units remain from the "
                        f"original Picking commitment, but "
                        f"{fmt_qty(requested_at_location)} requested."
                    )

        # -----------------------------------------------
        # INSERT — packing table + inventory_transactions OUT
        # (both created here; this is the single point stock
        # is deducted, per the v2 redesign)
        # -----------------------------------------------

        packing_rows = []
        out_rows = []

        for item in items:

            packing_rows.append(
                {
                    "order_id": item["order_id"],
                    "sku_code": item["sku_code"],
                    "location": item["location"],
                    "packed_qty": item["qty"],
                    "packed_by": packed_by,
                }
            )

            out_rows.append(
                {
                    "transaction_type": "OUT",
                    "po_number": item["order_id"],
                    "sku": item["sku_code"],
                    "location": item["location"],
                    "qty": item["qty"],
                }
            )

        client.table("packing").insert(packing_rows).execute()

        client.table("inventory_transactions").insert(out_rows).execute()

        _clear_packing_caches()

        return True, None

    except Exception as e:

        return False, str(e)


# =========================================================
# ORDER LIST VIEW
# =========================================================

def _render_order_list(orders: list[dict]) -> None:

    items_by_order = load_all_order_items()

    def summaries_fn() -> list[dict]:

        packed_totals = _load_packed_totals_by_order_sku()

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
                    packed_totals,
                    "PACKED",
                )
            )

        return out

    render_stage_order_list(
        orders,
        summaries_fn,
        search_key="packing_search",
        open_key_prefix="pkg_open",
        active_state_key="packing_active_order",
        done_col_label="Packed",
        done_tab_label="Packed",
    )


# =========================================================
# ORDER DETAIL VIEW
# =========================================================

def _render_order_detail(selected_order: dict, selected_order_id: str) -> None:

    if st.button("⬅ Back To Order List", key="pkg_back_list"):

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
    packed_by_sku = _load_packed_totals_by_order_sku()
    packed_by_sku_location = _load_packed_totals_by_order_sku_location()

    render_html('<div class="go-section" style="margin-top:1.5rem;">📦 READY FOR PACKING</div>')

    any_sku_ready = False

    for sku_index, sku_code in enumerate(sku_list):

        key = (selected_order_id, sku_code)

        location_rows = picking_lines.get(key, [])

        total_picked = sum(f(r.get("picked_qty")) for r in location_rows)

        if total_picked <= 0:
            # Nothing picked yet -> not eligible for Packing.
            continue

        already_packed_total = packed_by_sku.get(key, 0.0)

        current_form_qty = _get_form_qty(selected_order_id, sku_code)

        pending_qty = max(0.0, total_picked - already_packed_total - current_form_qty)

        ordered_qty = get_ordered_qty(order_items, sku_code)

        any_sku_ready = True

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
                    <div class="go-info-label">Picked</div>
                    <div class="go-info-value">{fmt_qty(total_picked)}</div>
                </div>
                """
            )

        with c3:
            render_html(
                f"""
                <div class="go-info">
                    <div class="go-info-label">Already Packed</div>
                    <div class="go-info-value">{fmt_qty(already_packed_total)}</div>
                </div>
                """
            )

        with c4:
            render_html(
                f"""
                <div class="go-pending">
                    <div style="font-size:0.72rem;">PENDING PACKING</div>
                    <div style="font-size:1rem;margin-top:0.15rem;">{fmt_qty(pending_qty)}</div>
                </div>
                """
            )

        if pending_qty <= 0:
            render_html(
                f'<div class="go-dispatched">✅ {esc(sku_code)} is fully packed.</div>'
            )
            continue

        if not location_rows:
            st.warning(
                f"No original Picking location record found for {sku_code}. "
                f"Cannot Pack without a Picking record."
            )
            continue

        with st.expander(f"📍 Pack {sku_code} (original picking locations)", expanded=True):

            # -------------------------------------------
            # FULLY ALLOCATE (across original locations)
            # -------------------------------------------

            picked_agg: dict = {}
            warehouse_by_location: dict = {}

            for row in location_rows:

                loc = s(row.get("location"))

                picked_agg[loc] = picked_agg.get(loc, 0.0) + f(row.get("picked_qty"))

                if loc not in warehouse_by_location:
                    warehouse_by_location[loc] = s(row.get("warehouse"))

            if st.button(
                f"⚡ Fully Allocate ({fmt_qty(pending_qty)})",
                type="primary",
                key=f"pkg_full_{selected_order_id}_{sku_code}",
            ):

                remaining = max(
                    0.0,
                    total_picked
                    - already_packed_total
                    - _get_form_qty(selected_order_id, sku_code),
                )

                allocated_any = False

                for location, picked_qty_here in picked_agg.items():

                    if remaining <= 0:
                        break

                    already_packed_here = packed_by_sku_location.get(
                        (selected_order_id, sku_code, location), 0.0
                    )

                    available_here = max(
                        0.0,
                        picked_qty_here
                        - already_packed_here
                        - _get_form_location_qty(
                            selected_order_id, sku_code, location
                        ),
                    )

                    take = min(remaining, available_here)

                    if take <= 0:
                        continue

                    if _add_packing_item(
                        selected_order_id,
                        sku_code,
                        location,
                        warehouse_by_location.get(location, "") or s(
                            selected_order.get("warehouse")
                        ),
                        take,
                        available_here,
                        remaining,
                    ):
                        remaining -= take
                        allocated_any = True

                if allocated_any:

                    if remaining > 0:
                        st.session_state.packing_error = (
                            f"{sku_code}: original Picking commitment kam "
                            f"tha, {fmt_qty(remaining)} units abhi bhi "
                            f"pending hain."
                        )

                    st.session_state.packing_clear_prefixes = [
                        f"pkg_qty_{selected_order_id}_{sku_code}_"
                    ]

                    st.rerun()

            # -------------------------------------------
            # PER ORIGINAL LOCATION ROWS
            # -------------------------------------------

            for location_index, (location, picked_qty_here) in enumerate(
                picked_agg.items()
            ):

                warehouse = warehouse_by_location.get(location, "") or s(
                    selected_order.get("warehouse")
                )

                already_packed_here = packed_by_sku_location.get(
                    (selected_order_id, sku_code, location), 0.0
                )

                form_here = _get_form_location_qty(
                    selected_order_id, sku_code, location
                )

                available_here = max(
                    0.0, picked_qty_here - already_packed_here - form_here
                )

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
                            <div class="go-location-stock">Originally Picked: {fmt_qty(picked_qty_here)}</div>
                            <div style="color:#64748b;font-size:0.72rem;margin-top:0.25rem;">
                                Remaining here: {fmt_qty(available_here)}
                            </div>
                        </div>
                        """
                    )

                with c3:

                    max_qty = max(0.0, min(pending_qty, available_here))

                    if max_qty > 0:

                        location_qty = st.number_input(
                            "Packed Qty",
                            min_value=0.0,
                            max_value=float(max_qty),
                            value=0.0,
                            step=1.0,
                            key=f"pkg_qty_{selected_order_id}_{sku_code}_{location_index}",
                        )

                    else:

                        location_qty = 0.0
                        st.caption("Nothing remaining here")

                if location_qty > 0:

                    if st.button(
                        "➕ Add",
                        type="primary",
                        use_container_width=True,
                        key=f"pkg_add_{selected_order_id}_{sku_code}_{location_index}",
                    ):

                        latest_form_qty = _get_form_qty(selected_order_id, sku_code)

                        latest_pending = max(
                            0.0,
                            total_picked
                            - already_packed_total
                            - latest_form_qty,
                        )

                        latest_form_here = _get_form_location_qty(
                            selected_order_id, sku_code, location
                        )

                        latest_available_here = max(
                            0.0,
                            picked_qty_here
                            - already_packed_here
                            - latest_form_here,
                        )

                        if location_qty > latest_pending:

                            st.error(
                                f"Only {fmt_qty(latest_pending)} units are "
                                f"pending for {sku_code}."
                            )

                        elif location_qty > latest_available_here:

                            st.error(
                                f"Only {fmt_qty(latest_available_here)} units "
                                f"remain from the original Picking at "
                                f"{location}."
                            )

                        else:

                            added = _add_packing_item(
                                selected_order_id,
                                sku_code,
                                location,
                                warehouse,
                                location_qty,
                                latest_available_here,
                                latest_pending,
                            )

                            if added:

                                st.session_state.packing_clear_exact = [
                                    f"pkg_qty_{selected_order_id}_{sku_code}_{location_index}"
                                ]

                                st.rerun()

        if sku_index < len(sku_list) - 1:
            render_html('<div class="go-divider"></div>')

    if not any_sku_ready:
        st.info(
            "No SKUs in this order have been Picked yet. Complete Picking first."
        )

    # =====================================================
    # REVIEW
    # =====================================================

    selected_review_items = [
        item
        for item in st.session_state.packing_items
        if item["order_id"] == selected_order_id
    ]

    if selected_review_items:

        render_html('<div class="go-section" style="margin-top:1.5rem;">📋 PACKING REVIEW</div>')

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

            actual_index = st.session_state.packing_items.index(item)

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

                if st.button("🗑", key=f"pkg_remove_{actual_index}"):

                    st.session_state.packing_items.pop(actual_index)
                    st.rerun()

        total_review_qty = sum(f(item["qty"]) for item in selected_review_items)

        render_html(
            f"""
            <div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;
                        padding:0.9rem 1rem;margin-top:0.8rem;margin-bottom:0.8rem;
                        color:#1e3a8a;font-weight:600;">
                Total Packing Quantity: {fmt_qty(total_review_qty)}
            </div>
            """
        )

        if st.session_state.packing_error:
            st.error(st.session_state.packing_error)

        if st.button(
            "✅ Save Packing",
            type="primary",
            use_container_width=True,
            key="save_packing",
        ):

            processing_placeholder = st.empty()

            processing_placeholder.markdown(
                processing_overlay_html(PROCESSING_TITLE),
                unsafe_allow_html=True,
            )

            processed_by = st.session_state.get("username", "")

            success, error = _save_packing(selected_review_items, processed_by)

            if success:

                email_success, email_error = True, ""

                if SEND_EMAIL_AT_PACKING:

                    email_success, email_error = send_gate_out_email(
                        order_data=selected_order,
                        gate_out_items=list(selected_review_items),
                        processed_by=processed_by,
                    )

                st.session_state.packing_items = [
                    i
                    for i in st.session_state.packing_items
                    if i["order_id"] != selected_order_id
                ]

                st.session_state.packing_success = True
                st.session_state.packing_error = ""
                st.session_state.packing_email_sent = email_success
                st.session_state.packing_email_error = (
                    "" if email_success else (email_error or "Unknown email error")
                )
                st.session_state.packing_clear_prefixes = ["pkg_qty_"]
                st.session_state.packing_show_overlay = True

                _go_back_to_origin_or_list()

                st.rerun()

            else:

                processing_placeholder.empty()

                st.session_state.packing_error = error or "Unknown error"

                st.error(f"❌ Packing save failed: {error}")


# =========================================================
# MAIN PAGE BODY
# =========================================================

def _render_packing_body(on_back=None) -> None:

    _init_state()

    inject_css()

    prefixes = st.session_state.pop("packing_clear_prefixes", None)

    if prefixes:

        for key in list(st.session_state.keys()):

            if isinstance(key, str) and key.startswith(tuple(prefixes)):

                st.session_state.pop(key, None)

    exact_keys = st.session_state.pop("packing_clear_exact", None)

    if exact_keys:

        for key in exact_keys:

            st.session_state.pop(key, None)

    render_html('<div class="go-title">📦 Packing</div>')

    if on_back:

        if st.button("⬅ Back To Home", key="pkg_back"):

            _reset_form()
            on_back()
            st.rerun()

    st.divider()

    if st.session_state.packing_success:

        st.success("🎉 Packing Saved Successfully! Stock has been deducted.")

        if SEND_EMAIL_AT_PACKING:

            if st.session_state.get("packing_email_sent", False):

                st.success("📧 Accounts notification sent successfully.")

            else:

                st.warning(
                    "⚠️ Packing save ho gaya, lekin Accounts email send nahi ho payi."
                )

                email_error = st.session_state.get("packing_email_error", "")

                if email_error:

                    st.caption(f"Email Error: {email_error}")

        st.session_state.packing_success = False

    orders = load_sales_orders()

    if not orders:
        st.info("No Sales Orders found.")
        return

    active_id = st.session_state.packing_active_order

    active_order = None

    if active_id:

        active_order = next(
            (o for o in orders if s(o.get("order_id")) == s(active_id)),
            None,
        )

    if active_order:

        _render_order_detail(active_order, s(active_order.get("order_id")))

    else:

        st.session_state.packing_active_order = None
        _render_order_list(orders)


# =========================================================
# ENTRY POINT
# =========================================================

def render_packing(on_back=None) -> None:

    overlay = None

    if st.session_state.pop("packing_show_overlay", False):

        overlay = st.empty()

        overlay.markdown(
            processing_overlay_html(PROCESSING_TITLE),
            unsafe_allow_html=True,
        )

    try:

        _render_packing_body(on_back)

    finally:

        if overlay is not None:

            overlay.empty()
