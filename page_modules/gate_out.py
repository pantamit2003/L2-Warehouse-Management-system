"""
page_modules/gate_out.py

EMIZA WMS — Dispatch Process HUB

Ab yeh page sirf ek "hub" hai:
   Select Sales Order
      ↓
   3 process cards dikhte hain: PICKING / PACKING / DISPATCH
   har card ka apna Progress + "Open →" button
      ↓
   "Open →" click karne par us stage ke apne page par jump ho jata hai
   (picking.py / packing.py / dispatch.py), aur wahan se save/confirm hone
   ke baad wapas isi order par is hub par laut aata hai.

IMPORTANT:
- Yeh page khud koi stock transaction ya dispatch-confirm logic nahi
  rakhta — woh sab ab dispatch.py me hai.
- No st.fragment.
"""

from __future__ import annotations

import streamlit as st

from page_modules.outbound_common import (
    s,
    f,
    fmt_qty,
    esc,
    render_html,
    inject_css,
    load_sales_orders,
    load_sales_order_items,
    load_all_order_items,
    load_grouped_totals,
    build_summary_from_items,
    render_stage_order_list,
)

# Jump targets for the process cards on the order-detail view.
_STAGE_JUMPS = [
    ("🧾", "PICKING", "picking_active_order", "Picking"),
    ("📦", "PACKING", "packing_active_order", "Packing"),
    ("🚚", "DISPATCH", "dispatch_active_order", "Dispatch"),
]


# =========================================================
# SESSION STATE
# =========================================================

def _init_state() -> None:

    defaults = {
        "gate_out_active_order": None,
    }

    for key, value in defaults.items():

        if key not in st.session_state:

            st.session_state[key] = value


def _reset_form() -> None:

    st.session_state.pop("gate_out_active_order", None)

    _init_state()


# =========================================================
# LOADERS
# =========================================================

@st.cache_data(ttl=5, show_spinner=False)
def _load_stage_totals_by_order() -> dict:
    """order_id -> {"picking": x, "packing": x, "dispatch": x} summed
    across all SKUs of that order — used for the process cards.
    ("dispatch" progress reuses the Packing total, since dispatch itself
    has no separate quantity table — a full Pack = ready to dispatch.)"""

    picking = load_grouped_totals("picking", "picked_qty", ("order_id",))
    packing = load_grouped_totals("packing", "packed_qty", ("order_id",))

    out: dict = {}

    all_order_ids = set()

    for d in (picking, packing):

        for key in d.keys():

            all_order_ids.add(key[0])

    for order_id in all_order_ids:

        packing_qty = packing.get((order_id,), 0.0)

        out[order_id] = {
            "picking": picking.get((order_id,), 0.0),
            "packing": packing_qty,
            "dispatch": packing_qty,
        }

    return out


def clear_gate_out_caches() -> None:
    """
    Public, callable from picking.py / packing.py so that saving there
    immediately invalidates this hub's own cached progress numbers too.
    """

    _load_stage_totals_by_order.clear()


# =========================================================
# ORDER LIST VIEW
# =========================================================

def _render_order_list(orders: list[dict]) -> None:

    items_by_order = load_all_order_items()

    def summaries_fn() -> list[dict]:

        packed_totals = load_grouped_totals(
            "packing", "packed_qty", ("order_id", "sku_code")
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
                    packed_totals,
                    "DISPATCHED",
                )
            )

        return out

    render_stage_order_list(
        orders,
        summaries_fn,
        search_key="gate_out_search",
        open_key_prefix="go_open",
        active_state_key="gate_out_active_order",
        done_col_label="Dispatched",
        done_tab_label="Dispatched",
    )


# =========================================================
# PROCESS CARDS (Picking / Packing / Dispatch progress, jump-in buttons)
# =========================================================

def _render_process_cards(selected_order_id: str, ordered_total: float) -> None:

    render_html('<div class="go-section" style="margin-top:0.5rem;">🔄 Dispatch Process</div>')

    stage_totals = _load_stage_totals_by_order().get(selected_order_id, {})

    for icon, label, state_key, page_name in _STAGE_JUMPS:

        done_qty = stage_totals.get(label.lower(), 0.0)

        c1, c2 = st.columns([4, 1])

        with c1:

            render_html(
                f"""
                <div class="go-sku-card" style="margin-top:0.4rem;margin-bottom:0.4rem;">
                    <div class="go-sku-code">{icon} {esc(label)}</div>
                    <div style="color:#6b7280;font-size:0.82rem;margin-top:0.2rem;">
                        Progress: {fmt_qty(done_qty)} / {fmt_qty(ordered_total)}
                    </div>
                </div>
                """
            )

        with c2:

            if st.button(
                "Open →",
                key=f"go_jump_{state_key}_{selected_order_id}",
                use_container_width=True,
            ):

                stage_prefix = state_key.replace("_active_order", "")

                st.session_state[state_key] = selected_order_id
                st.session_state[f"{stage_prefix}_return_page"] = "Gate Out"
                st.session_state[f"{stage_prefix}_return_order"] = selected_order_id
                st.session_state["current_page"] = page_name
                st.rerun()

    render_html('<div class="go-divider"></div>')


# =========================================================
# ORDER DETAIL VIEW
# =========================================================

def _render_order_detail(selected_order: dict, selected_order_id: str) -> None:

    if st.button("⬅ Back To Order List", key="go_back_list"):

        st.session_state.gate_out_active_order = None
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

    ordered_total = sum(f(item.get("quantity")) for item in order_items)

    _render_process_cards(selected_order_id, ordered_total)


# =========================================================
# MAIN PAGE BODY
# =========================================================

def _render_gate_out_body(on_back=None) -> None:

    _init_state()

    inject_css()

    render_html('<div class="go-title">🚪 Gate Out</div>')

    if on_back:

        if st.button("⬅ Back To Home", key="go_back"):

            _reset_form()
            on_back()
            st.rerun()

    st.divider()

    orders = load_sales_orders()

    if not orders:
        st.info("No Sales Orders found.")
        return

    active_id = st.session_state.gate_out_active_order

    active_order = None

    if active_id:

        active_order = next(
            (o for o in orders if s(o.get("order_id")) == s(active_id)),
            None,
        )

    if active_order:

        _render_order_detail(active_order, s(active_order.get("order_id")))

    else:

        st.session_state.gate_out_active_order = None
        _render_order_list(orders)


# =========================================================
# ENTRY POINT
# =========================================================

def render_gate_out(on_back=None) -> None:

    _render_gate_out_body(on_back)
