"""
page_modules/create_po.py — SKU Master integrated, clean layout

Flow:
  Step 1 → PO header (vendor, PO no, dates, logistics, invoice type)
  Step 2 → Add SKUs (Single: 1 row / Multiple: many rows)
  Create PO → po_master mein insert
"""
from datetime import date
import json
import streamlit as st
from db.supabase_client import get_client

def _s(val) -> str:
    return str(val or "").strip()

UOM_OPTIONS = ["Pcs", "Box", "Carton", "Kg", "Litre", "Bag", "Bundle", "Set"]
PO_TYPES    = ["Inward", "Return"]
TRANSPORT   = ["", "Road", "Rail", "Air", "Sea", "Courier", "Hand Delivery"]
VENDOR_NAME= ["", "SM TRAVEL GEAR PVT LTD.","SR INDUSTRIES"]

SKU_PLACEHOLDER = "— Select SKU —"

# po_master payload ke header wale columns (order same as pehle)
_PAYLOAD_KEYS = (
    "po_no", "warehouse", "po_type", "vendor", "po_date", "exp_date",
    "transport", "seller_po", "remarks", "invoice_type", "created_by",
)


# =========================================================
# CSS  (ek baar define, har render pe wahi string use hoti hai)
# =========================================================

_CSS = """
<style>
.po-title {
    font-size:1.25rem; font-weight:700; color:#111827;
    margin-bottom:1rem; padding-bottom:0.6rem;
    border-bottom:1px solid #e5e7eb;
}
.field-label {
    font-size:0.78rem; font-weight:600; color:#374151;
    margin-bottom:0.15rem; display:block;
}
.req { color:#ef4444; }
.summary-box {
    background:#eff6ff; border:1px solid #bfdbfe;
    border-radius:10px; padding:0.8rem 1.2rem;
    font-size:0.83rem; color:#1d4ed8; margin-bottom:1.2rem;
}
.form-card {
    background: transparent !important;
    border: none !important;
    border-radius: 0 !important;
    padding: 0 !important;
    box-shadow: none !important;
    margin-bottom: 1.2rem;
}
.form-card-title {
    font-size: 0.8rem;
    font-weight: 700;
    color: #6b7280;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 1rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid #e5e7eb;
}
/* =========================================================
   FORM INPUT BORDERS
   ========================================================= */

/* Text input */
div[data-testid="stTextInput"] input {
    border: 1px solid #cbd5e1 !important;
    border-radius: 7px !important;
    background-color: #ffffff !important;
    color: #111827 !important;
    min-height: 40px !important;
}

/* Text input focus */
div[data-testid="stTextInput"] input:focus {
    border: 1.5px solid #2563eb !important;
    box-shadow: 0 0 0 1px #2563eb !important;
}

/* Selectbox */
div[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
    border: 1px solid #cbd5e1 !important;
    border-radius: 7px !important;
    background-color: #ffffff !important;
    min-height: 40px !important;
}

/* Selectbox focus */
div[data-testid="stSelectbox"] div[data-baseweb="select"] > div:focus-within {
    border: 1.5px solid #2563eb !important;
    box-shadow: 0 0 0 1px #2563eb !important;
}

/* Date input */
div[data-testid="stDateInput"] input {
    border: 1px solid #cbd5e1 !important;
    border-radius: 7px !important;
    background-color: #ffffff !important;
    color: #111827 !important;
    min-height: 40px !important;
}

/* Date input focus */
div[data-testid="stDateInput"] input:focus {
    border: 1.5px solid #2563eb !important;
    box-shadow: 0 0 0 1px #2563eb !important;
}
</style>
"""


# =========================================================
# PROCESSING OVERLAY
#
# Create PO dabane par poori screen ke beech dikhta hai
# (Gate Out jaisa). Balloons ki jagah yahi use hota hai.
# =========================================================

_PROCESSING_OVERLAY_HTML = """
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
        <div class="po-spinner"></div>
        <div style="
            margin-top: 1.2rem;
            font-size: 1.05rem;
            font-weight: 700;
            color: #111827;
        ">
            Processing PO...
        </div>
        <div style="
            margin-top: 0.3rem;
            font-size: 0.82rem;
            color: #6b7280;
        ">
            Please wait, do not refresh.
        </div>
    </div>
</div>

<style>
.po-spinner {
    width: 48px;
    height: 48px;
    border: 5px solid #e5e7eb;
    border-top: 5px solid #0284c7;
    border-radius: 50%;
    margin: 0 auto;
    animation: po-spin 0.8s linear infinite;
}
@keyframes po-spin {
    0%   { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
}
</style>
"""


# =========================================================
# STATE
# =========================================================

def _new_rows() -> list[dict]:
    """Har baar fresh list + fresh dict (shared object mutate na ho)."""
    return [{"sku_code": "", "qty": 1.0, "uom": "Pcs", "rate": 0.0}]


def _init_state() -> None:
    defaults = {
        "po_created":   False,
        "po_step":      1,
        "po_header":    {},
        "sku_rows":     _new_rows(),
        "invoice_type": "Single",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _reset_po_flow() -> None:
    st.session_state.po_step   = 1
    st.session_state.po_header = {}
    st.session_state.sku_rows  = _new_rows()


# =========================================================
# DATA
# =========================================================

@st.cache_data(ttl=300, show_spinner=False)
def _load_skus() -> list[dict]:
    # 'category' is page mein use nahi hota, isliye sirf 2 columns
    try:
        res = (get_client()
               .table("sku_master")
               .select("sku_code,sku_name")
               .eq("is_active", True)
               .order("sku_name")
               .execute())
        return res.data or []
    except Exception:
        return []


# =========================================================
# SMALL UI HELPERS
# =========================================================

def _label(text: str) -> None:
    st.markdown(f'<span class="field-label">{text}</span>',
                unsafe_allow_html=True)


def _card_open(title: str) -> None:
    st.markdown(
        f'<div class="form-card"><div class="form-card-title">{title}</div>',
        unsafe_allow_html=True,
    )


def _card_close() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


# =========================================================
# STEP 1 — HEADER
# =========================================================

def _render_step1() -> None:

    # ── Card 1: Main PO Info ─────────────────────────────────────
    _card_open("📋 PO Information")

    # Row 1: Warehouse | Type | Vendor Name
    c1, c2, c3 = st.columns(3)
    with c1:
        _label("⭐ Warehouse")
        st.selectbox("Warehouse", ["L2"], label_visibility="collapsed",
                     key="po_warehouse", disabled=True)

    with c2:
        _label("⭐ Type")
        po_type = st.selectbox("Type", PO_TYPES,
                               label_visibility="collapsed", key="po_type")

    with c3:
        _label("⭐ Vendor Name")
        vendor = st.selectbox("Vendor", VENDOR_NAME,
                               label_visibility="collapsed", key="po_vendor")

    st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)

    # Row 2: PO Number | PO Date | Expected Delivery Date
    c4, c5, c6 = st.columns(3)
    with c4:
        _label("⭐ PO Number")
        po_no = st.text_input("PO No", placeholder="PO Number",
                              label_visibility="collapsed", key="po_number")

    with c5:
        _label("⭐ PO Date")
        po_date = st.date_input("PO Date", value=date.today(), format="DD/MM/YYYY",
                                label_visibility="collapsed", key="po_date")

    with c6:
        _label("⭐ Expected Delivery Date")
        exp_date = st.date_input("Exp Date", value=None,
                                 min_value=date.today(), format="DD/MM/YYYY",
                                 label_visibility="collapsed", key="po_exp_date")

    _card_close()

    # ── Card 2: Logistics ────────────────────────────────────────
    _card_open("🚛 Logistics & Additional Info")

    # Row 3: Mode of Transport | Seller PO Code | Remarks
    c7, c8, c9 = st.columns(3)
    with c7:
        _label("Mode of Transportation")
        transport = st.selectbox("Transport", TRANSPORT,
                                 label_visibility="collapsed", key="po_transport")

    with c8:
        _label("Seller Invoice No")
        seller_po = st.text_input("Seller PO", placeholder="Seller Invoice No",
                                  label_visibility="collapsed", key="po_seller")

    with c9:
        _label("Remarks")
        remarks = st.text_input("Remarks", placeholder="Remarks",
                                label_visibility="collapsed", key="po_remarks")

    _card_close()

    # ── Card 3: Invoice ──────────────────────────────────────────
    _card_open("🧾 Invoice Type")
    _label("⭐ Invoice")
    invoice_type = st.radio("Invoice", ["Single", "Multiple"],
                            horizontal=True, label_visibility="collapsed",
                            key="po_invoice_type")
    _card_close()

    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

    _, btn_col = st.columns([3, 1])
    with btn_col:
        proceed = st.button("Proceed to Add Items ➡",
                            use_container_width=True, type="primary")

    if not proceed:
        return

    errors = []
    if not vendor.strip():  errors.append("Vendor Name")
    if not po_no.strip():   errors.append("PO Number")
    if exp_date is None:    errors.append("Expected Delivery Date")
    if errors:
        st.error(f"❌ Required: {', '.join(errors)}")
        return

    st.session_state.po_header = {
        "warehouse":    "L2",
        "po_type":      po_type,
        "vendor":       vendor.strip(),
        "po_no":        po_no.strip(),
        "po_date":      po_date.strftime("%d-%m-%Y"),
        "exp_date":     exp_date.strftime("%d-%m-%Y"),
        "transport":    transport,
        "seller_po":    seller_po.strip(),
        "remarks":      remarks.strip(),
        "invoice_type": invoice_type,
        "created_by":   st.session_state.get("username", ""),
    }
    st.session_state.po_step = 2
    st.rerun()


# =========================================================
# STEP 2 — SKU EDITORS
# =========================================================

def _render_single_editor(sku_opts: list[str], sku_map: dict) -> list[dict]:
    c1, c2, c3, c4 = st.columns([3, 1.5, 1.5, 1.5])
    with c1:
        st.markdown("**SKU / Item**")
        sku_sel = st.selectbox("SKU", sku_opts,
                               label_visibility="collapsed", key="s_sku")
    with c2:
        st.markdown("**Quantity**")
        qty = st.number_input("Qty", min_value=0.0, step=1.0,
                              label_visibility="collapsed", key="s_qty")
    with c3:
        st.markdown("**UOM**")
        uom = st.selectbox("UOM", UOM_OPTIONS,
                           label_visibility="collapsed", key="s_uom")
    with c4:
        st.markdown("**Rate (₹)**")
        rate = st.number_input("Rate", min_value=0.0, step=0.01,
                               label_visibility="collapsed", key="s_rate")

    resolved = sku_map.get(sku_sel, {})
    return [{
        "sku_code": resolved.get("sku_code", ""),
        "sku_name": resolved.get("sku_name", sku_sel),
        "qty": qty, "uom": uom, "rate": rate,
    }]


def _render_multi_editor(sku_opts: list[str], sku_map: dict) -> list[dict]:
    rows = st.session_state.sku_rows

    hc0, hc1, hc2, hc3, hc4, hc5 = st.columns([0.4, 3, 1.5, 1.5, 1.5, 0.5])
    hc0.markdown("**#**")
    hc1.markdown("**SKU / Item**")
    hc2.markdown("**Qty**")
    hc3.markdown("**UOM**")
    hc4.markdown("**Rate (₹)**")
    hc5.markdown("**Del**")

    to_delete = None
    for i, row in enumerate(rows):
        rc0, rc1, rc2, rc3, rc4, rc5 = st.columns([0.4, 3, 1.5, 1.5, 1.5, 0.5])

        with rc0:
            st.markdown(
                f"<div style='padding-top:.55rem;color:#6b7280;font-size:.85rem'>{i+1}</div>",
                unsafe_allow_html=True)
        with rc1:
            cur = row.get("sku_code", "")
            idx = sku_opts.index(cur) if cur in sku_opts else 0
            rows[i]["sku_code"] = st.selectbox(f"sku_{i}", sku_opts,
                                               index=idx,
                                               label_visibility="collapsed",
                                               key=f"msku_{i}")
        with rc2:
            rows[i]["qty"] = st.number_input(f"qty_{i}",
                                             min_value=0.0, step=1.0,
                                             value=float(row.get("qty", 1)),
                                             label_visibility="collapsed",
                                             key=f"mqty_{i}")
        with rc3:
            uom_idx = UOM_OPTIONS.index(row["uom"]) if row.get("uom") in UOM_OPTIONS else 0
            rows[i]["uom"] = st.selectbox(f"uom_{i}", UOM_OPTIONS,
                                          index=uom_idx,
                                          label_visibility="collapsed",
                                          key=f"muom_{i}")
        with rc4:
            rows[i]["rate"] = st.number_input(f"rate_{i}",
                                              min_value=0.0, step=0.01,
                                              value=float(row.get("rate", 0)),
                                              label_visibility="collapsed",
                                              key=f"mrate_{i}")
        with rc5:
            if i > 0:
                if st.button("🗑", key=f"del_{i}"):
                    to_delete = i

    if to_delete is not None:
        rows.pop(to_delete)
        st.rerun()

    if st.button("➕ Add Row", key="add_row"):
        rows.append(_new_rows()[0])
        st.rerun()

    sku_list = []

    for r in rows:
        sel = r.get("sku_code", "")
        res = sku_map.get(sel, {})

        # Placeholder ya invalid SKU ko blank rakho
        if sel == SKU_PLACEHOLDER or not res:
            sku_code = ""
            sku_name = ""
        else:
            sku_code = res.get("sku_code", "")
            sku_name = res.get("sku_name", "")

        sku_list.append({
            "sku_code": sku_code,
            "sku_name": sku_name,
            "qty": r["qty"],
            "uom": r["uom"],
            "rate": r["rate"],
        })

    return sku_list


def _submit_po(h: dict, sku_list: list[dict]) -> None:
    """Create PO dabane par: validate → po_master insert → success state."""

    valid = [
        s for s in sku_list
        if _s(s.get("sku_code"))
           and _s(s.get("sku_code")) != SKU_PLACEHOLDER
           and _s(s.get("sku_name")) != SKU_PLACEHOLDER
           and float(s.get("qty") or 0) > 0
    ]

    if not valid:
        st.error("❌ Please select a valid SKU and enter quantity greater than 0.")
        return

    if len(valid) != len(sku_list):
        st.error(
            "❌ Ek ya zyada rows mein SKU select nahi hai "
            "ya quantity invalid hai. Rows correct ya delete karo."
        )
        return


    payload = {k: h[k] for k in _PAYLOAD_KEYS}
    payload["sku_data"] = json.dumps(valid)

    # Save ke dauran poori screen pe "Processing" overlay
    processing = st.empty()
    processing.markdown(_PROCESSING_OVERLAY_HTML, unsafe_allow_html=True)

    try:
        get_client().table("po_master").insert(payload).execute()
    except Exception as e:
        processing.empty()            # failure me overlay turant hatao
        st.error(f"❌ PO Save Nahi Hua: {e}")
        return

    st.session_state.po_created = True
    st.session_state.sku_rows = _new_rows()

    # Overlay yahan nahi hataya: agla run apna overlay dikhaye aur
    # page poora render hone ke baad hi hataye (purani screen ka
    # flash na aaye).
    st.session_state.po_show_overlay = True
    st.rerun()


# =========================================================
# STEP 2 — ADD SKUs + CREATE PO
# =========================================================

def _render_step2() -> None:
    h = st.session_state.po_header

    st.markdown(f"""
<div class="summary-box">
  <b>PO Summary</b> &nbsp;|&nbsp;
  Warehouse: <b>{h['warehouse']}</b> &nbsp;|&nbsp;
  Type: <b>{h['po_type']}</b> &nbsp;|&nbsp;
  Vendor: <b>{h['vendor']}</b> &nbsp;|&nbsp;
  PO No: <b>{h['po_no']}</b> &nbsp;|&nbsp;
  PO Date: <b>{h['po_date']}</b> &nbsp;|&nbsp;
  Invoice: <b>{h['invoice_type']}</b>
</div>
""", unsafe_allow_html=True)

    st.markdown("#### 📦 Add SKUs")

    # Load SKU master
    all_skus = _load_skus()

    # Dropdown me sirf SKU NAME dikhega
    sku_opts = [SKU_PLACEHOLDER] + [s["sku_name"] for s in all_skus]

    # SKU name se complete SKU record milega
    sku_map = {s["sku_name"]: s for s in all_skus}

    if h["invoice_type"] == "Single":
        sku_list = _render_single_editor(sku_opts, sku_map)
    else:
        sku_list = _render_multi_editor(sku_opts, sku_map)

    st.divider()

    back_col, _, submit_col = st.columns([1, 3, 1])
    with back_col:
        if st.button("⬅ Back to PO Details", key="step_back"):
            st.session_state.po_step = 1
            st.rerun()

    with submit_col:
        if st.button("✅ Create PO", type="primary",
                     use_container_width=True, key="final_submit"):
            _submit_po(h, sku_list)


# =========================================================
# MAIN PAGE
# =========================================================

def _render_create_po_body(on_back=None) -> None:
    _init_state()

    st.markdown(_CSS, unsafe_allow_html=True)

    st.markdown('<div class="po-title">📄 Create Purchase Order</div>',
                unsafe_allow_html=True)

    if st.button("⬅ Back To Home", key="po_back"):
        _reset_po_flow()
        st.session_state.invoice_type = "Single"
        if on_back:
            on_back()
        st.rerun()

    st.divider()

    if st.session_state.po_created:
        st.success("✅ PO Created Successfully!")
        st.session_state.po_created = False
        _reset_po_flow()

    if st.session_state.po_step == 1:
        _render_step1()
    elif st.session_state.po_step == 2:
        _render_step2()


# =========================================================
# ENTRY POINT
#
# Create PO ke baad ka agla run yahan overlay dikhata hai aur
# page render hone ke baad hi hatata hai.
# =========================================================

def render_create_po(on_back=None) -> None:
    overlay = None

    if st.session_state.pop("po_show_overlay", False):
        overlay = st.empty()
        overlay.markdown(_PROCESSING_OVERLAY_HTML, unsafe_allow_html=True)

    try:
        _render_create_po_body(on_back)
    finally:
        if overlay is not None:
            overlay.empty()
