"""
page_modules/create_so.py
EMIZA WMS — Sales Order Creation

Flow:

Create Sales Order
        ↓
Order Details
        ↓
Customer Details
        ↓
Billing Address
        ↓
Shipping Address
        ↓
Add Multiple SKUs
        ↓
Create Order
        ↓
Supabase generates Order ID automatically

IMPORTANT:
- No Location in Sales Order
- Location will be handled later in Gate Out
- Same as Billing Address hides shipping input fields
- Add SKU does NOT clear Billing / Customer information
- Compatible with Streamlit versions without st.fragment
"""

from __future__ import annotations

import streamlit as st

from auth import get_client


# =========================================================
# CONSTANTS
# =========================================================

WAREHOUSE_OPTIONS = [
    "L2",
]

ORDER_TYPE_OPTIONS = [
    "Standard",
    "Replacement",
    "Sample",
    "Transfer",
]

SHELF_LIFE_OPTIONS = [
    "None",
    "Expiry",
    "Manufacturing Date",
]

NON_SELLABLE_OPTIONS = [
    "No",
    "Yes",
]


# =========================================================
# HELPERS
# =========================================================

def _s(value) -> str:
    """Convert value to clean string."""
    return str(value or "").strip()


def _f(value) -> float:
    """Convert value to float safely."""
    try:
        return float(value or 0)
    except Exception:
        return 0.0


# =========================================================
# SKU MASTER
# =========================================================

@st.cache_data(ttl=300, show_spinner=False)
def _load_skus() -> list[dict]:
    """
    Load active SKUs from sku_master.
    """

    try:

        response = (
            get_client()
            .table("sku_master")
            .select("sku_code,sku_name,category")
            .eq("is_active", True)
            .order("sku_name")
            .execute()
        )

        return response.data or []

    except Exception as e:

        st.error(
            f"Unable to load SKU Master: {e}"
        )

        return []


# =========================================================
# WAREHOUSE MASTER
# =========================================================

def _load_warehouses() -> list[str]:
    """
    Currently only L2 is active.
    Can later be replaced by warehouse_master.
    """

    return WAREHOUSE_OPTIONS


# =========================================================
# LIVE STOCK  (SKU select karte hi Quantity ke paas dikhane ke liye)
#
# Gate Out / Material Check jaisa hi calculation:
#     current stock = location_master.qty  +  IN  -  OUT
# =========================================================

@st.cache_data(ttl=30, show_spinner=False)
def _get_sku_stock(sku_code: str) -> float:

    sku_code = _s(sku_code)

    if not sku_code:
        return 0.0

    try:

        client = get_client()

        location_response = (
            client
            .table("location_master")
            .select("qty")
            .eq("sku", sku_code)
            .execute()
        )

        opening_qty = sum(
            _f(row.get("qty"))
            for row in (location_response.data or [])
        )

        transaction_response = (
            client
            .table("inventory_transactions")
            .select("transaction_type,qty")
            .eq("sku", sku_code)
            .execute()
        )

        transaction_qty = 0.0

        for row in (transaction_response.data or []):

            qty = _f(row.get("qty"))

            transaction_type = _s(
                row.get("transaction_type")
            ).upper()

            if transaction_type == "IN":

                transaction_qty += qty

            elif transaction_type == "OUT":

                transaction_qty -= qty

        current_stock = opening_qty + transaction_qty

        return max(0.0, current_stock)

    except Exception:

        # Stock dikhana sirf ek info hai — load fail ho to
        # SKU add karne mein koi rukawat nahi aani chahiye.
        return 0.0


# =========================================================
# SESSION STATE
# =========================================================

def _init_state() -> None:

    defaults = {

        # -------------------------------------------------
        # SKU ITEMS
        # -------------------------------------------------

        "so_items": [],

        # -------------------------------------------------
        # SUCCESS
        # -------------------------------------------------

        "so_success": False,

        "so_created_order_id": None,

        # -------------------------------------------------
        # ORDER DETAILS
        # -------------------------------------------------

        "so_warehouse": "L2",

        "so_order_type": "Standard",

        "so_existing_customer": "",

        # -------------------------------------------------
        # CUSTOMER
        # -------------------------------------------------

        "so_customer_name": "",

        "so_email": "",

        "so_phone": "",

        "so_alternate_phone": "",

        "so_remark": "",

        # -------------------------------------------------
        # BILLING
        # -------------------------------------------------

        "so_billing_address_1": "",

        "so_billing_address_2": "",

        "so_billing_pincode": "",

        "so_billing_state": "",

        "so_billing_city": "",

        # -------------------------------------------------
        # SHIPPING
        # -------------------------------------------------

        "so_shipping_name": "",

        "so_shipping_phone": "",

        "so_shipping_address_1": "",

        "so_shipping_address_2": "",

        "so_shipping_pincode": "",

        "so_shipping_state": "",

        "so_shipping_city": "",

        # -------------------------------------------------
        # SAME AS BILLING
        # -------------------------------------------------

        "so_same_as_billing": False,

        # -------------------------------------------------
        # NEW SKU INPUT
        # -------------------------------------------------

        "so_new_sku": "— Select SKU —",

        "so_new_quantity": 1.0,

        "so_new_shelf_life": "None",

        "so_new_mrp": 0.0,

        "so_new_selling_price": 0.0,

        "so_new_discount": 0.0,

        "so_new_non_sellable": "No",

        "so_new_zone": "",
    }

    for key, value in defaults.items():

        if key not in st.session_state:

            st.session_state[key] = value


# =========================================================
# RESET SKU INPUTS ONLY
# =========================================================

def _reset_sku_inputs() -> None:
    """
    IMPORTANT:

    Only SKU entry fields are reset.

    Customer details
    Billing address
    Shipping address
    Order details

    are NOT touched.
    """

    st.session_state.so_new_sku = "— Select SKU —"

    st.session_state.so_new_quantity = 1.0

    st.session_state.so_new_shelf_life = "None"

    st.session_state.so_new_mrp = 0.0

    st.session_state.so_new_selling_price = 0.0

    st.session_state.so_new_discount = 0.0

    st.session_state.so_new_non_sellable = "No"

    st.session_state.so_new_zone = ""


# =========================================================
# RESET COMPLETE FORM
# =========================================================

def _reset_form() -> None:

    keys_to_clear = [

        # ORDER
        "so_warehouse",
        "so_order_type",
        "so_existing_customer",

        # CUSTOMER
        "so_customer_name",
        "so_email",
        "so_phone",
        "so_alternate_phone",
        "so_remark",

        # BILLING
        "so_billing_address_1",
        "so_billing_address_2",
        "so_billing_pincode",
        "so_billing_state",
        "so_billing_city",

        # SHIPPING
        "so_shipping_name",
        "so_shipping_phone",
        "so_shipping_address_1",
        "so_shipping_address_2",
        "so_shipping_pincode",
        "so_shipping_state",
        "so_shipping_city",

        # SAME BILLING
        "so_same_as_billing",

        # SKU
        "so_new_sku",
        "so_new_quantity",
        "so_new_shelf_life",
        "so_new_mrp",
        "so_new_selling_price",
        "so_new_discount",
        "so_new_non_sellable",
        "so_new_zone",
    ]

    for key in keys_to_clear:

        st.session_state.pop(
            key,
            None,
        )

    st.session_state.so_items = []

    st.session_state.so_success = False

    st.session_state.so_created_order_id = None


# =========================================================
# ADD SKU CALLBACK
# =========================================================

def _add_sku_callback(
    selected_sku_name: str,
    sku_map: dict,
    quantity: float,
    shelf_life_type: str,
    mrp: float,
    selling_price: float,
    discount_amount: float,
    is_non_sellable: str,
    zone: str,
) -> None:
    """
    Add SKU without touching customer/address fields.

    This callback runs before Streamlit reruns the page.
    """

    # -----------------------------------------------------
    # VALIDATION
    # -----------------------------------------------------

    if selected_sku_name == "— Select SKU —":

        st.session_state.so_add_error = (
            "Please select a SKU."
        )

        return

    if quantity <= 0:

        st.session_state.so_add_error = (
            "Quantity must be greater than 0."
        )

        return

    # -----------------------------------------------------
    # GET SELECTED SKU
    # -----------------------------------------------------

    selected_sku = sku_map.get(
        selected_sku_name
    )

    if not selected_sku:

        st.session_state.so_add_error = (
            "Selected SKU could not be found."
        )

        return

    # -----------------------------------------------------
    # CREATE ITEM
    # -----------------------------------------------------

    new_item = {

        "sku_code":
            selected_sku["sku_code"],

        "quantity":
            quantity,

        "shelf_life_type":
            shelf_life_type,

        "mrp":
            mrp,

        "selling_price":
            selling_price,

        "discount_amount":
            discount_amount,

        "is_non_sellable":
            is_non_sellable,

        "zone":
            _s(zone),
    }

    # -----------------------------------------------------
    # APPEND ITEM
    # -----------------------------------------------------

    st.session_state.so_items.append(
        new_item
    )

    # -----------------------------------------------------
    # CLEAR ONLY SKU INPUT
    # -----------------------------------------------------

    _reset_sku_inputs()

    # -----------------------------------------------------
    # CLEAR ERROR
    # -----------------------------------------------------

    st.session_state.so_add_error = ""


# =========================================================
# CREATE SALES ORDER
# =========================================================

def _create_order(
    order_data: dict,
    item_data: list[dict],
):
    """
    Create Sales Order header and SKU item rows.

    order_id is NOT passed from Python.

    PostgreSQL generates:

        SO-000001
        SO-000002
        SO-000003
        ...
    """

    client = get_client()

    try:

        # =================================================
        # 1. CREATE SALES ORDER HEADER
        # =================================================

        response = (
            client
            .table("sales_orders")
            .insert(order_data)
            .execute()
        )

        # -------------------------------------------------
        # Supabase response check
        # -------------------------------------------------

        if not response.data:

            return (
                False,
                None,
                "Sales Order could not be created."
            )

        # -------------------------------------------------
        # Internal DB ID
        # -------------------------------------------------

        sales_order_id = response.data[0]["id"]

        # =================================================
        # 2. FETCH GENERATED ORDER ID
        # =================================================

        order_response = (
            client
            .table("sales_orders")
            .select("order_id")
            .eq("id", sales_order_id)
            .single()
            .execute()
        )

        if not order_response.data:

            return (
                False,
                None,
                "Sales Order created but Order ID could not be fetched."
            )

        order_id = order_response.data["order_id"]

        # =================================================
        # 3. PREPARE SKU ITEMS
        # =================================================

        rows = []

        for item in item_data:

            rows.append(
                {
                    "sales_order_id":
                        sales_order_id,

                    "sku_code":
                        item["sku_code"],

                    "quantity":
                        item["quantity"],

                    "shelf_life_type":
                        item["shelf_life_type"],

                    "mrp":
                        item["mrp"],

                    "selling_price":
                        item["selling_price"],

                    "discount_amount":
                        item["discount_amount"],

                    "is_non_sellable":
                        item["is_non_sellable"],

                    "zone":
                        item["zone"],
                }
            )

        # =================================================
        # 4. INSERT SKU ITEMS
        # =================================================

        if rows:

            (
                client
                .table("sales_order_items")
                .insert(rows)
                .execute()
            )

        # =================================================
        # SUCCESS
        # =================================================

        return (
            True,
            order_id,
            None,
        )

    except Exception as e:

        return (
            False,
            None,
            str(e),
        )


# =========================================================
# CSS
# =========================================================

def inject_create_so_css() -> None:

    st.markdown(
        """
        <style>

        /* =================================================
           PAGE
           ================================================= */

        .so-title {
            font-size: 1.25rem;
            font-weight: 700;
            color: #111827;
            margin-bottom: 1rem;
            padding-bottom: 0.6rem;
            border-bottom: 1px solid #e5e7eb;
        }


        /* =================================================
           FORM CARD
           ================================================= */

        .form-card {
            background: transparent !important;
            border: none !important;
            border-radius: 0 !important;
            padding: 0 !important;
            box-shadow: none !important;
            margin-bottom: 1.2rem;
        }


        /* =================================================
           SECTION TITLE
           ================================================= */

        .form-card-title {
            font-size: 0.8rem;
            font-weight: 700;
            color: #64748b;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 1rem;
            padding-bottom: 0.5rem;
            border-bottom: 1px solid #e5e7eb;
        }


        /* =================================================
           FIELD LABEL
           ================================================= */

        .field-label {
            font-size: 0.78rem;
            font-weight: 600;
            color: #374151;
            margin-bottom: 0.15rem;
            display: block;
        }


        .req {
            color: #ef4444;
        }


        .stock-hint {
            color: #16a34a;
            font-weight: 700;
        }


        /* =================================================
           TEXT INPUT
           ================================================= */

        div[data-testid="stTextInput"] input {

            border: 1px solid #cbd5e1 !important;

            border-radius: 7px !important;

            background-color: #ffffff !important;

            color: #111827 !important;

            min-height: 40px !important;
        }


        div[data-testid="stTextInput"] input:focus {

            border: 1.5px solid #2563eb !important;

            box-shadow:
                0 0 0 1px #2563eb !important;
        }


        /* =================================================
           NUMBER INPUT
           ================================================= */

        div[data-testid="stNumberInput"] input {

            border: 1px solid #cbd5e1 !important;

            border-radius: 7px !important;

            background-color: #ffffff !important;

            color: #111827 !important;

            min-height: 40px !important;
        }


        div[data-testid="stNumberInput"] input:focus {

            border: 1.5px solid #2563eb !important;

            box-shadow:
                0 0 0 1px #2563eb !important;
        }


        /* =================================================
           SELECTBOX
           ================================================= */

        div[data-testid="stSelectbox"]
        div[data-baseweb="select"] > div {

            border: 1px solid #cbd5e1 !important;

            border-radius: 7px !important;

            background-color: #ffffff !important;

            min-height: 40px !important;
        }


        div[data-testid="stSelectbox"]
        div[data-baseweb="select"] > div:focus-within {

            border: 1.5px solid #2563eb !important;

            box-shadow:
                0 0 0 1px #2563eb !important;
        }


        /* =================================================
           CHECKBOX
           ================================================= */

        div[data-testid="stCheckbox"] label p {

            font-size: 0.82rem !important;

            font-weight: 600 !important;

            color: #374151 !important;
        }


        /* =================================================
           SKU TITLE
           ================================================= */

        .sku-item-title {

            background: #ffffff;

            border: 1px solid #e2e8f0;

            border-radius: 10px 10px 0 0;

            padding: 0.85rem 1.2rem;

            font-size: 0.82rem;

            font-weight: 700;

            color: #374151;

            margin-top: 0.5rem;

            margin-bottom: 0;
        }


        /* =================================================
           ADD SKU BOX
           ================================================= */

        .add-sku-box {

            background: #ffffff;

            border: 1px dashed #cbd5e1;

            border-radius: 10px;

            padding: 1rem 1.2rem;

            margin-top: 0.8rem;

            margin-bottom: 1rem;
        }


        .add-sku-title {

            font-size: 0.8rem;

            font-weight: 700;

            color: #64748b;

            letter-spacing: 0.07em;

            text-transform: uppercase;

            margin-bottom: 0.8rem;
        }


        /* =================================================
           SUMMARY
           ================================================= */

        .so-summary {

            background: #eff6ff;

            border: 1px solid #bfdbfe;

            border-radius: 10px;

            padding: 0.75rem 1.2rem;

            color: #1d4ed8;

            font-size: 0.85rem;

            font-weight: 600;

            margin: 1rem 0;
        }


        /* =================================================
           INFO
           ================================================= */

        .same-billing-info {

            background: #dbeafe;

            border-radius: 10px;

            padding: 0.9rem 1.2rem;

            color: #174a7e;

            font-size: 0.9rem;

            margin-top: 0.6rem;

            margin-bottom: 1rem;
        }

        </style>
        """,
        unsafe_allow_html=True,
    )


# =========================================================
# LABEL
# =========================================================

def _label(
    text: str,
    required: bool = False,
) -> None:

    star = (
        '<span class="req">⭐</span> '
        if required
        else ""
    )

    st.markdown(
        f'<span class="field-label">{star}{text}</span>',
        unsafe_allow_html=True,
    )


# =========================================================
# MAIN PAGE
# =========================================================

def render_create_so(on_back=None) -> None:

    # -----------------------------------------------------
    # INITIALIZE
    # -----------------------------------------------------

    _init_state()

    inject_create_so_css()


    # =====================================================
    # SUCCESS SCREEN — AUTO REDIRECT
    # =====================================================

    if st.session_state.so_success:

        st.success(
            "🎉 Sales Order Created Successfully!"
        )

        st.markdown(
            f"""
            <div style="
                font-size:1rem;
                font-weight:600;
                color:#374151;
                margin-top:0.8rem;
                margin-bottom:1rem;
            ">
                Order ID:
                <span style="color:#2563eb;">
                    {st.session_state.so_created_order_id}
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.balloons()

        st.markdown(
            """
            <div style="
                font-size:0.9rem;
                color:#64748b;
                margin-top:1rem;
            ">
                Redirecting to Sales Order list...
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Reset form aur redirect
        st.session_state.so_success = False
        st.session_state.so_created_order_id = None
        _reset_form()

        # Go back to Sales Order list
        if on_back:
            on_back()

        st.rerun()

        return


    # =====================================================
    # PAGE TITLE
    # =====================================================

    st.markdown(
        '<div class="so-title">'
        '📋 Create Sales Order'
        '</div>',
        unsafe_allow_html=True,
    )


    # =====================================================
    # BACK
    # =====================================================

    if on_back:

        if st.button(
            "⬅ Back To Home",
            key="so_back",
        ):

            _reset_form()

            on_back()

            st.rerun()


    st.divider()


    # =====================================================
    # ORDER DETAILS
    # =====================================================

    st.markdown(
        '<div class="form-card">'
        '<div class="form-card-title">'
        '📦 ORDER DETAILS'
        '</div>',
        unsafe_allow_html=True,
    )


    c1, c2, c3 = st.columns(3)


    # -----------------------------------------------------
    # WAREHOUSE
    # -----------------------------------------------------

    with c1:

        _label(
            "Warehouse",
            required=True,
        )

        warehouse = st.selectbox(
            "Warehouse",
            _load_warehouses(),
            label_visibility="collapsed",
            key="so_warehouse",
        )


    # -----------------------------------------------------
    # EXISTING CUSTOMER
    # -----------------------------------------------------

    with c2:

        _label("Existing Customer")

        existing_customer = st.text_input(
            "Existing Customer",
            placeholder="Enter customer",
            label_visibility="collapsed",
            key="so_existing_customer",
        )


    # -----------------------------------------------------
    # ORDER TYPE
    # -----------------------------------------------------

    with c3:

        _label(
            "Order Type",
            required=True,
        )

        order_type = st.selectbox(
            "Order Type",
            ORDER_TYPE_OPTIONS,
            label_visibility="collapsed",
            key="so_order_type",
        )


    st.markdown(
        "</div>",
        unsafe_allow_html=True,
    )


    # =====================================================
    # CUSTOMER DETAILS
    # =====================================================

    st.markdown(
        '<div class="form-card">'
        '<div class="form-card-title">'
        '👤 CUSTOMER DETAILS'
        '</div>',
        unsafe_allow_html=True,
    )


    c1, c2, c3 = st.columns(3)


    with c1:

        _label(
            "Customer Name",
            required=True,
        )

        customer_name = st.text_input(
            "Customer Name",
            label_visibility="collapsed",
            key="so_customer_name",
        )


    with c2:

        _label("Email")

        email = st.text_input(
            "Email",
            placeholder="customer@email.com",
            label_visibility="collapsed",
            key="so_email",
        )


    with c3:

        _label(
            "Phone Number",
            required=True,
        )

        phone = st.text_input(
            "Phone Number",
            placeholder="Phone Number",
            label_visibility="collapsed",
            key="so_phone",
        )


    st.markdown(
        "<div style='height:0.6rem'></div>",
        unsafe_allow_html=True,
    )


    c1, c2 = st.columns(2)


    with c1:

        _label("Alternate Phone")

        alternate_phone = st.text_input(
            "Alternate Phone",
            placeholder="Alternate Phone",
            label_visibility="collapsed",
            key="so_alternate_phone",
        )


    with c2:

        _label("Remark")

        remark = st.text_input(
            "Remark",
            placeholder="Remark",
            label_visibility="collapsed",
            key="so_remark",
        )


    st.markdown(
        "</div>",
        unsafe_allow_html=True,
    )


    # =====================================================
    # BILLING ADDRESS
    # =====================================================

    st.markdown(
        '<div class="form-card">'
        '<div class="form-card-title">'
        '🏠 BILLING ADDRESS'
        '</div>',
        unsafe_allow_html=True,
    )


    c1, c2 = st.columns(2)


    with c1:

        _label(
            "Address Line 1",
            required=True,
        )

        billing_address_1 = st.text_input(
            "Billing Address Line 1",
            placeholder="Address Line 1",
            label_visibility="collapsed",
            key="so_billing_address_1",
        )


    with c2:

        _label("Address Line 2")

        billing_address_2 = st.text_input(
            "Billing Address Line 2",
            placeholder="Address Line 2",
            label_visibility="collapsed",
            key="so_billing_address_2",
        )


    st.markdown(
        "<div style='height:0.6rem'></div>",
        unsafe_allow_html=True,
    )


    c1, c2, c3 = st.columns(3)


    with c1:

        _label(
            "Pincode",
            required=True,
        )

        billing_pincode = st.text_input(
            "Billing Pincode",
            placeholder="Pincode",
            label_visibility="collapsed",
            key="so_billing_pincode",
        )


    with c2:

        _label(
            "State",
            required=True,
        )

        billing_state = st.text_input(
            "Billing State",
            placeholder="State",
            label_visibility="collapsed",
            key="so_billing_state",
        )


    with c3:

        _label(
            "City",
            required=True,
        )

        billing_city = st.text_input(
            "Billing City",
            placeholder="City",
            label_visibility="collapsed",
            key="so_billing_city",
        )


    st.markdown(
        "</div>",
        unsafe_allow_html=True,
    )


    # =====================================================
    # SHIPPING ADDRESS
    # =====================================================

    st.markdown(
        '<div class="form-card">'
        '<div class="form-card-title">'
        '🚚 SHIPPING ADDRESS'
        '</div>',
        unsafe_allow_html=True,
    )


    # -----------------------------------------------------
    # SAME AS BILLING
    # -----------------------------------------------------

    same_as_billing = st.checkbox(
        "Same as Billing Address",
        key="so_same_as_billing",
    )


    # =====================================================
    # SAME AS BILLING
    # =====================================================

    if same_as_billing:

        # -------------------------------------------------
        # NO SHIPPING INPUT FIELDS
        # -------------------------------------------------

        shipping_name = customer_name

        shipping_phone = phone

        shipping_address_1 = billing_address_1

        shipping_address_2 = billing_address_2

        shipping_pincode = billing_pincode

        shipping_state = billing_state

        shipping_city = billing_city


        st.markdown(
            """
            <div class="same-billing-info">
                Shipping address will be same as billing address.
            </div>
            """,
            unsafe_allow_html=True,
        )


    # =====================================================
    # DIFFERENT SHIPPING ADDRESS
    # =====================================================

    else:

        # -------------------------------------------------
        # SHIPPING NAME / PHONE
        # -------------------------------------------------

        c1, c2 = st.columns(2)


        with c1:

            _label("Shipping Name")

            shipping_name = st.text_input(
                "Shipping Name",
                placeholder="Shipping Name",
                label_visibility="collapsed",
                key="so_shipping_name",
            )


        with c2:

            _label("Shipping Phone")

            shipping_phone = st.text_input(
                "Shipping Phone",
                placeholder="Shipping Phone",
                label_visibility="collapsed",
                key="so_shipping_phone",
            )


        st.markdown(
            "<div style='height:0.6rem'></div>",
            unsafe_allow_html=True,
        )


        # -------------------------------------------------
        # SHIPPING ADDRESS
        # -------------------------------------------------

        c1, c2 = st.columns(2)


        with c1:

            _label(
                "Address Line 1",
                required=True,
            )

            shipping_address_1 = st.text_input(
                "Shipping Address Line 1",
                placeholder="Address Line 1",
                label_visibility="collapsed",
                key="so_shipping_address_1",
            )


        with c2:

            _label("Address Line 2")

            shipping_address_2 = st.text_input(
                "Shipping Address Line 2",
                placeholder="Address Line 2",
                label_visibility="collapsed",
                key="so_shipping_address_2",
            )


        st.markdown(
            "<div style='height:0.6rem'></div>",
            unsafe_allow_html=True,
        )


        # -------------------------------------------------
        # PIN / STATE / CITY
        # -------------------------------------------------

        c1, c2, c3 = st.columns(3)


        with c1:

            _label(
                "Pincode",
                required=True,
            )

            shipping_pincode = st.text_input(
                "Shipping Pincode",
                placeholder="Pincode",
                label_visibility="collapsed",
                key="so_shipping_pincode",
            )


        with c2:

            _label(
                "State",
                required=True,
            )

            shipping_state = st.text_input(
                "Shipping State",
                placeholder="State",
                label_visibility="collapsed",
                key="so_shipping_state",
            )


        with c3:

            _label(
                "City",
                required=True,
            )

            shipping_city = st.text_input(
                "Shipping City",
                placeholder="City",
                label_visibility="collapsed",
                key="so_shipping_city",
            )


    st.markdown(
        "</div>",
        unsafe_allow_html=True,
    )


    # =====================================================
    # ORDER ITEMS
    # =====================================================

    st.markdown(
        '<div class="form-card">'
        '<div class="form-card-title">'
        '📦 ORDER ITEMS'
        '</div>',
        unsafe_allow_html=True,
    )


    # =====================================================
    # LOAD SKUS
    # =====================================================

    all_skus = _load_skus()


    if not all_skus:

        st.warning(
            "No active SKUs found in SKU Master."
        )

        st.markdown(
            "</div>",
            unsafe_allow_html=True,
        )

        return


    sku_options = [
        "— Select SKU —"
    ] + [
        sku["sku_name"]
        for sku in all_skus
    ]


    sku_map = {
        sku["sku_name"]: sku
        for sku in all_skus
    }


    # =====================================================
    # ADDED SKU ITEMS
    # =====================================================

    for index, item in enumerate(
        st.session_state.so_items
    ):

        st.markdown(
            f"""
            <div class="sku-item-title">
                📦 Item {index + 1}
                — {item["sku_code"]}
            </div>
            """,
            unsafe_allow_html=True,
        )


        # -------------------------------------------------
        # ROW 1
        # -------------------------------------------------

        c1, c2, c3 = st.columns(3)


        with c1:

            _label("SKU Code")

            st.text_input(
                f"Saved SKU {index}",
                value=item["sku_code"],
                disabled=True,
                label_visibility="collapsed",
                key=f"so_saved_sku_{index}",
            )


        with c2:

            _label("Quantity")

            st.number_input(
                f"Saved Quantity {index}",
                min_value=1.0,
                value=_f(item["quantity"]),
                disabled=True,
                label_visibility="collapsed",
                key=f"so_saved_qty_{index}",
            )


        with c3:

            _label("Shelf Life Type")

            st.text_input(
                f"Saved Shelf {index}",
                value=item["shelf_life_type"],
                disabled=True,
                label_visibility="collapsed",
                key=f"so_saved_shelf_{index}",
            )


        # -------------------------------------------------
        # ROW 2
        # -------------------------------------------------

        c1, c2, c3 = st.columns(3)


        with c1:

            _label("MRP")

            st.number_input(
                f"Saved MRP {index}",
                min_value=0.0,
                value=_f(item["mrp"]),
                disabled=True,
                label_visibility="collapsed",
                key=f"so_saved_mrp_{index}",
            )


        with c2:

            _label("Selling Price")

            st.number_input(
                f"Saved Price {index}",
                min_value=0.0,
                value=_f(item["selling_price"]),
                disabled=True,
                label_visibility="collapsed",
                key=f"so_saved_price_{index}",
            )


        with c3:

            _label("Discount Amount")

            st.number_input(
                f"Saved Discount {index}",
                min_value=0.0,
                value=_f(item["discount_amount"]),
                disabled=True,
                label_visibility="collapsed",
                key=f"so_saved_discount_{index}",
            )


        # -------------------------------------------------
        # ROW 3
        # -------------------------------------------------

        c1, c2, c3 = st.columns(3)


        with c1:

            _label("Is Non Sellable")

            st.text_input(
                f"Saved Non Sellable {index}",
                value=item["is_non_sellable"],
                disabled=True,
                label_visibility="collapsed",
                key=f"so_saved_non_sellable_{index}",
            )


        with c2:

            _label("Zone")

            st.text_input(
                f"Saved Zone {index}",
                value=item["zone"],
                disabled=True,
                label_visibility="collapsed",
                key=f"so_saved_zone_{index}",
            )


        with c3:

            st.markdown(
                "<div style='height:1.35rem'></div>",
                unsafe_allow_html=True,
            )

            if st.button(
                "🗑 Remove SKU",
                key=f"so_remove_{index}",
                use_container_width=True,
            ):

                st.session_state.so_items.pop(
                    index
                )

                st.rerun()


        st.markdown(
            """
            <hr style="
                border:0;
                border-top:1px solid #e5e7eb;
                margin:1rem 0;
            ">
            """,
            unsafe_allow_html=True,
        )


    # =====================================================
    # ADD SKU BOX
    # =====================================================

    st.markdown(
        '<div class="add-sku-box">',
        unsafe_allow_html=True,
    )


    st.markdown(
        '<div class="add-sku-title">'
        '➕ ADD SKU'
        '</div>',
        unsafe_allow_html=True,
    )


    # -----------------------------------------------------
    # ADD SKU ROW 1
    # -----------------------------------------------------

    c1, c2, c3 = st.columns(3)


    with c1:

        _label(
            "SKU / Item",
            required=True,
        )

        selected_sku_name = st.selectbox(
            "SKU / Item",
            sku_options,
            label_visibility="collapsed",
            key="so_new_sku",
        )


    with c2:

        # Selected SKU ka live available stock, label ke
        # saamne green mein (jaise purane Emiza system mein
        # "Quantity  14" dikhta tha)
        selected_sku_for_stock = sku_map.get(
            st.session_state.so_new_sku
        )

        if selected_sku_for_stock:

            available_stock = _get_sku_stock(
                selected_sku_for_stock["sku_code"]
            )

            st.markdown(
                f'<span class="field-label">'
                f'<span class="req">⭐</span> Quantity '
                f'<span class="stock-hint">'
                f'{available_stock:g}'
                f'</span></span>',
                unsafe_allow_html=True,
            )

        else:

            _label(
                "Quantity",
                required=True,
            )

        quantity = st.number_input(
            "Quantity",
            min_value=1.0,
            value=1.0,
            step=1.0,
            label_visibility="collapsed",
            key="so_new_quantity",
        )


    with c3:

        _label("Shelf Life Type")

        shelf_life_type = st.selectbox(
            "Shelf Life Type",
            SHELF_LIFE_OPTIONS,
            label_visibility="collapsed",
            key="so_new_shelf_life",
        )


    st.markdown(
        "<div style='height:0.6rem'></div>",
        unsafe_allow_html=True,
    )


    # -----------------------------------------------------
    # ADD SKU ROW 2
    # -----------------------------------------------------

    c1, c2, c3 = st.columns(3)


    with c1:

        _label("MRP")

        mrp = st.number_input(
            "MRP",
            min_value=0.0,
            step=0.01,
            label_visibility="collapsed",
            key="so_new_mrp",
        )


    with c2:

        _label("Selling Price")

        selling_price = st.number_input(
            "Selling Price",
            min_value=0.0,
            step=0.01,
            label_visibility="collapsed",
            key="so_new_selling_price",
        )


    with c3:

        _label("Discount Amount")

        discount_amount = st.number_input(
            "Discount Amount",
            min_value=0.0,
            step=0.01,
            label_visibility="collapsed",
            key="so_new_discount",
        )


    st.markdown(
        "<div style='height:0.6rem'></div>",
        unsafe_allow_html=True,
    )


    # -----------------------------------------------------
    # ADD SKU ROW 3
    # -----------------------------------------------------

    c1, c2, c3 = st.columns(3)


    with c1:

        _label("Is Non Sellable")

        is_non_sellable = st.selectbox(
            "Is Non Sellable",
            NON_SELLABLE_OPTIONS,
            label_visibility="collapsed",
            key="so_new_non_sellable",
        )


    with c2:

        _label("Zone")

        zone = st.text_input(
            "Zone",
            placeholder="Zone",
            label_visibility="collapsed",
            key="so_new_zone",
        )


    with c3:

        st.markdown(
            "<div style='height:1.35rem'></div>",
            unsafe_allow_html=True,
        )

        # -------------------------------------------------
        # IMPORTANT:
        # NORMAL BUTTON + CALLBACK
        # NO st.fragment
        # -------------------------------------------------

        st.button(
            "➕ Add SKU",
            type="primary",
            use_container_width=True,
            key="so_add_sku",
            on_click=_add_sku_callback,
            args=(
                selected_sku_name,
                sku_map,
                quantity,
                shelf_life_type,
                mrp,
                selling_price,
                discount_amount,
                is_non_sellable,
                zone,
            ),
        )


    st.markdown(
        "</div>",
        unsafe_allow_html=True,
    )


    # =====================================================
    # ADD SKU ERROR
    # =====================================================

    if st.session_state.get(
        "so_add_error",
        "",
    ):

        st.warning(
            f"⚠️ "
            f"{st.session_state.so_add_error}"
        )

        st.session_state.so_add_error = ""


    # =====================================================
    # CLOSE ORDER ITEMS
    # =====================================================

    st.markdown(
        "</div>",
        unsafe_allow_html=True,
    )


    # =====================================================
    # TOTAL SKU SUMMARY
    # =====================================================

    if st.session_state.so_items:

        st.markdown(
            f"""
            <div class="so-summary">
                📦 Total SKU Lines:
                {len(st.session_state.so_items)}
            </div>
            """,
            unsafe_allow_html=True,
        )


    # =====================================================
    # CREATE ORDER BUTTON
    # =====================================================

    st.markdown(
        "<div style='height:0.4rem'></div>",
        unsafe_allow_html=True,
    )


    if st.button(
        "✅ Create Order",
        type="primary",
        use_container_width=True,
        key="so_create_order",
    ):

        # =================================================
        # VALIDATION
        # =================================================

        errors = []


        # -------------------------------------------------
        # CUSTOMER
        # -------------------------------------------------

        if not _s(customer_name):

            errors.append(
                "Customer Name is required."
            )


        if not _s(phone):

            errors.append(
                "Phone Number is required."
            )


        # -------------------------------------------------
        # BILLING
        # -------------------------------------------------

        if not _s(billing_address_1):

            errors.append(
                "Billing Address Line 1 is required."
            )


        if not _s(billing_pincode):

            errors.append(
                "Billing Pincode is required."
            )


        if not _s(billing_state):

            errors.append(
                "Billing State is required."
            )


        if not _s(billing_city):

            errors.append(
                "Billing City is required."
            )


        # -------------------------------------------------
        # SHIPPING
        #
        # ONLY VALIDATE IF DIFFERENT SHIPPING ADDRESS
        # -------------------------------------------------

        if not same_as_billing:

            if not _s(shipping_address_1):

                errors.append(
                    "Shipping Address Line 1 is required."
                )


            if not _s(shipping_pincode):

                errors.append(
                    "Shipping Pincode is required."
                )


            if not _s(shipping_state):

                errors.append(
                    "Shipping State is required."
                )


            if not _s(shipping_city):

                errors.append(
                    "Shipping City is required."
                )


        # -------------------------------------------------
        # SKU
        # -------------------------------------------------

        if not st.session_state.so_items:

            errors.append(
                "Please add at least one SKU."
            )


        # =================================================
        # SHOW ERRORS
        # =================================================

        if errors:

            for error in errors:

                st.error(
                    f"❌ {error}"
                )

            return


        # =================================================
        # PREPARE ORDER DATA
        # =================================================

        order_data = {

            # -------------------------------------------------
            # ORDER
            # -------------------------------------------------

            "warehouse":
                warehouse,

            "existing_customer":
                _s(existing_customer)
                or None,

            "customer_name":
                _s(customer_name),

            "email":
                _s(email)
                or None,

            "phone":
                _s(phone),

            "alternate_phone":
                _s(alternate_phone)
                or None,

            "remark":
                _s(remark)
                or None,

            "order_type":
                order_type,

            # -------------------------------------------------
            # BILLING
            # -------------------------------------------------

            "billing_address_1":
                _s(billing_address_1),

            "billing_address_2":
                _s(billing_address_2)
                or None,

            "billing_pincode":
                _s(billing_pincode),

            "billing_state":
                _s(billing_state),

            "billing_city":
                _s(billing_city),

            # -------------------------------------------------
            # SHIPPING
            #
            # If Same as Billing:
            # billing values are copied here.
            # -------------------------------------------------

            "shipping_name":
                _s(shipping_name)
                or None,

            "shipping_phone":
                _s(shipping_phone)
                or None,

            "shipping_address_1":
                _s(shipping_address_1),

            "shipping_address_2":
                _s(shipping_address_2)
                or None,

            "shipping_pincode":
                _s(shipping_pincode),

            "shipping_state":
                _s(shipping_state),

            "shipping_city":
                _s(shipping_city),

            # -------------------------------------------------
            # FLAG
            # -------------------------------------------------

            "same_as_billing":
                same_as_billing,

            # -------------------------------------------------
            # STATUS
            # -------------------------------------------------

            "status":
                "CREATED",
        }


        # =================================================
        # SAVE
        # =================================================

        with st.spinner(
            "Creating Sales Order..."
        ):

            success, order_id, error = _create_order(
                order_data,
                st.session_state.so_items,
            )


        # =================================================
        # SUCCESS
        # =================================================

        if success:

            st.session_state.so_created_order_id = (
                order_id
            )

            st.session_state.so_success = True

            st.rerun()


        # =================================================
        # ERROR
        # =================================================

        else:

            st.error(
                f"❌ Sales Order creation failed: {error}"
            )
