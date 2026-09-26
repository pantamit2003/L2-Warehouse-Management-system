"""
page_modules/dispatch.py

EMIZA WMS — Stage 3: Dispatch (own page — same pattern as Picking/Packing)

Flow:

Dispatch
   ↓
Select Sales Order
   ↓
"Ready For Dispatch" — shows Ordered vs Packed per SKU (informational only)
   ↓
Confirm Dispatch (single click, per order) — ALWAYS available as long as
SOMETHING has been packed, even if not the full ordered qty. Packing is
the source of truth for "how much stock actually left the warehouse", so
Dispatch does not block on partial packing — it is just the warehouse's
confirmation that whatever was packed has now physically gone out.
   ↓
Marks the order Dispatched — NO inventory_transactions insert here.
Stock was ALREADY deducted at the Packing stage.
   ↓
Accounts Email (only if SEND_EMAIL_AT_PACKING in packing.py is False —
otherwise the email already went out at Packing, so this stage stays
silent to avoid a duplicate email)

IMPORTANT:
- Dispatch does NOT insert inventory_transactions OUT. Packing already
  did that.
- Dispatch does NOT touch location_master or picking locations at all.
- Dispatch does NOT require full packing before allowing confirmation —
  partial packed qty can be dispatched too (packed = ground truth of what
  physically left).
- RETURN-PATH: if this page was opened via a jump from gate_out.py's hub
  (the "Open →" button on the Dispatch process card), a
  "dispatch_return_page" / "dispatch_return_order" pair is set in
  session state. Both "Back To Order List" and a successful Confirm
  Dispatch then navigate straight back to that origin page/order.
- No st.fragment.
"""

from __future__ import annotations

import streamlit as st

from page_modules.email_service import send_gate_out_email
from page_modules.packing import SEND_EMAIL_AT_PACKING

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
    clear_common_caches,
    load_grouped_totals,
    build_summary_from_items,
    render_stage_order_list,
)

PROCESSING_TITLE = "Processing Dispatch..."


# =========================================================
# SESSION STATE
# =========================================================

def _init_state() -> None:

    defaults = {
        "dispatch_active_order": None,
        "dispatch_success": False,
        "dispatch_email_sent": False,
        "dispatch_email_error": "",
        "dispatch_show_overlay": False,
    }

    for key, value in defaults.items():

        if key not in st.session_state:

            st.session_state[key] = value


def _reset_form() -> None:

    for key in [
        "dispatch_active_order",
        "dispatch_success",
        "dispatch_email_sent",
        "dispatch_email_error",
        "dispatch_return_page",
        "dispatch_return_order",
    ]:

        st.session_state.pop(key, None)

    _init_state()


def _go_back_to_origin_or_list() -> None:
    """
    Used by "Back To Order List" and by a successful Confirm Dispatch. If
    this page was opened via a jump from gate_out.py's hub, send the user
    straight back to that origin order instead of Dispatch's own list.
    """

    return_page = st.session_state.pop("dispatch_return_page", None)
    return_order = st.session_state.pop("dispatch_return_order", None)

    st.session_state.dispatch_active_order = None

    if return_page:

        st.session_state["current_page"] = return_page

        if return_page == "Gate Out":

            st.session_state["gate_out_active_order"] = return_order


# =========================================================
# LOADERS
# =========================================================

@st.cache_data(ttl=5, show_spinner=False)
def _load_packed_totals_by_order_sku() -> dict:
    """(order_id, sku_code) -> total Packed qty (= already dispatched-
    ready, since Packing is the point stock actually leaves)."""

    return load_grouped_totals(
        "packing", "packed_qty", ("order_id", "sku_code")
    )


def _clear_dispatch_caches() -> None:

    clear_common_caches()

    _load_packed_totals_by_order_sku.clear()


def clear_dispatch_caches() -> None:
    """
    Public, callable from packing.py so that saving a Packing immediately
    invalidates Dispatch's own cached progress numbers too.
    """

    _load_packed_totals_by_order_sku.clear()


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
                    "DISPATCHED",
                )
            )

        return out

    render_stage_order_list(
        orders,
        summaries_fn,
        search_key="dispatch_search",
        open_key_prefix="dp_open",
        active_state_key="dispatch_active_order",
        done_col_label="Dispatched",
        done_tab_label="Dispatched",
    )


# =========================================================
# ORDER DETAIL VIEW
# =========================================================

def _render_order_detail(selected_order: dict, selected_order_id: str) -> None:

    if st.button("⬅ Back To Order List", key="dp_back_list"):

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

    packed_by_sku = _load_packed_totals_by_order_sku()

    render_html('<div class="go-section">🚚 READY FOR DISPATCH</div>')

    total_packed_all = 0.0

    for sku_index, sku_code in enumerate(sku_list):

        key = (selected_order_id, sku_code)

        ordered_qty = get_ordered_qty(order_items, sku_code)

        packed_qty = packed_by_sku.get(key, 0.0)

        total_packed_all += packed_qty

        render_html(
            f"""
            <div class="go-sku-card">
                <div class="go-sku-code">📦 {esc(sku_code)}</div>
            </div>
            """
        )

        c1, c2 = st.columns(2)

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
                    <div class="go-info-label">Packed (Ready to Dispatch)</div>
                    <div class="go-info-value">{fmt_qty(packed_qty)}</div>
                </div>
                """
            )

        if sku_index < len(sku_list) - 1:
            render_html('<div class="go-divider"></div>')

    render_html('<div class="go-divider"></div>')

    # ---------------------------------------------------
    # Dispatch is NOT blocked on full packing. Packing is
    # the ground truth of what physically left the
    # warehouse — Dispatch is just the confirmation click.
    # ---------------------------------------------------

    if total_packed_all <= 0:

        st.info(
            "Is order me abhi kuch bhi Packed nahi hua hai. "
            "Pehle Packing complete karo."
        )
        return

    st.success(
        f"📦 Total {fmt_qty(total_packed_all)} units packed hain. "
        f"Jitna maal warehouse se pack hokar tayar hai, usi ko dispatch confirm karo."
    )

    if st.button(
        "🚚 Confirm Dispatch",
        type="primary",
        use_container_width=True,
        key=f"dp_confirm_dispatch_{selected_order_id}",
    ):

        processing_placeholder = st.empty()

        processing_placeholder.markdown(
            processing_overlay_html(PROCESSING_TITLE),
            unsafe_allow_html=True,
        )

        processed_by = st.session_state.get("username", "")

        email_success, email_error = True, ""

        # Only send from here if Packing did NOT already send it, to
        # avoid a duplicate Accounts notification.
        if not SEND_EMAIL_AT_PACKING:

            email_success, email_error = send_gate_out_email(
                order_data=selected_order,
                gate_out_items=[],
                processed_by=processed_by,
            )

        processing_placeholder.empty()

        st.session_state.dispatch_success = True
        st.session_state.dispatch_email_sent = email_success
        st.session_state.dispatch_email_error = (
            "" if email_success else (email_error or "Unknown email error")
        )
        st.session_state.dispatch_show_overlay = True

        _go_back_to_origin_or_list()

        st.rerun()


# =========================================================
# MAIN PAGE BODY
# =========================================================

def _render_dispatch_body(on_back=None) -> None:

    _init_state()

    inject_css()

    render_html('<div class="go-title">🚚 Dispatch</div>')

    if on_back:

        if st.button("⬅ Back To Home", key="dp_back"):

            _reset_form()
            on_back()
            st.rerun()

    st.divider()

    if st.session_state.dispatch_success:

        st.success("🎉 Order marked as Dispatched!")

        if not SEND_EMAIL_AT_PACKING:

            if st.session_state.get("dispatch_email_sent", False):

                st.success("📧 Accounts notification sent successfully.")

            else:

                st.warning(
                    "⚠️ Dispatch confirm ho gaya, lekin Accounts email send nahi ho payi."
                )

                email_error = st.session_state.get("dispatch_email_error", "")

                if email_error:

                    st.caption(f"Email Error: {email_error}")

        st.session_state.dispatch_success = False

    orders = load_sales_orders()

    if not orders:
        st.info("No Sales Orders found.")
        return

    active_id = st.session_state.dispatch_active_order

    active_order = None

    if active_id:

        active_order = next(
            (o for o in orders if s(o.get("order_id")) == s(active_id)),
            None,
        )

    if active_order:

        _render_order_detail(active_order, s(active_order.get("order_id")))

    else:

        st.session_state.dispatch_active_order = None
        _render_order_list(orders)


# =========================================================
# ENTRY POINT
# =========================================================

def render_dispatch(on_back=None) -> None:

    overlay = None

    if st.session_state.pop("dispatch_show_overlay", False):

        overlay = st.empty()

        overlay.markdown(
            processing_overlay_html(PROCESSING_TITLE),
            unsafe_allow_html=True,
        )

    try:

        _render_dispatch_body(on_back)

    finally:

        if overlay is not None:

            overlay.empty()
