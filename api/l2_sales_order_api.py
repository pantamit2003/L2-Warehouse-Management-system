"""
L2 Sales Order API for Google Sheets.

This is a separate service entry point. It does not import Streamlit or
modify the existing manual Sales Order UI.
"""

from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from supabase import create_client

app = FastAPI(title="L2 Sales Order API", version="1.0.0")


def _get_supabase():
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured."
        )
    return create_client(url, key)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "yes", "1", "y"}


def _check_token(authorization: str | None, x_api_key: str | None) -> None:
    expected = os.environ.get("L2_SALES_ORDER_API_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="API token is not configured.")

    supplied = (x_api_key or "").strip()
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()

    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "l2-sales-order-api"}


@app.post("/create-order")
def create_order(
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _check_token(authorization, x_api_key)

    request_key = str(payload.get("request_key") or "").strip()
    if not request_key:
        raise HTTPException(status_code=400, detail="request_key is required.")

    warehouse = str(payload.get("warehouse") or "").strip().upper()
    if warehouse != "L2":
        raise HTTPException(status_code=400, detail="This endpoint accepts only warehouse L2.")

    line_items = payload.get("line_items")
    if not isinstance(line_items, list) or not line_items:
        raise HTTPException(status_code=400, detail="At least one line_item is required.")

    same_as_billing = _as_bool(payload.get("same_as_billing", False))

    # Match the current EMIZA payload names while mapping to L2 columns.
    order_data = {
        "warehouse": "L2",
        "existing_customer": payload.get("existing_customer") or None,
        "customer_name": str(payload.get("name") or "").strip(),
        "email": payload.get("email") or None,
        "phone": str(payload.get("phone") or "").strip(),
        "alternate_phone": payload.get("alternate_phone") or None,
        "remark": payload.get("remarks") or None,
        "order_type": "Standard",
        "billing_address_1": str(payload.get("billing_address1") or "").strip(),
        "billing_address_2": payload.get("billing_address2") or None,
        "billing_pincode": str(payload.get("billing_pincode") or "").strip(),
        "billing_state": str(payload.get("billing_state") or "").strip(),
        "billing_city": str(payload.get("billing_city") or "").strip(),
        "shipping_name": payload.get("shipping_name") or payload.get("name") or None,
        "shipping_phone": payload.get("shipping_phone") or payload.get("phone") or None,
        "shipping_address_1": (
            payload.get("billing_address1")
            if same_as_billing
            else payload.get("shipping_address1")
        ),
        "shipping_address_2": (
            payload.get("billing_address2")
            if same_as_billing
            else payload.get("shipping_address2")
        ) or None,
        "shipping_pincode": (
            payload.get("billing_pincode")
            if payload.get("same_as_billing")
            else payload.get("shipping_pincode")
        ),
        "shipping_state": (
            payload.get("billing_state")
            if payload.get("same_as_billing")
            else payload.get("shipping_state")
        ),
        "shipping_city": (
            payload.get("billing_city")
            if payload.get("same_as_billing")
            else payload.get("shipping_city")
        ),
        "same_as_billing": same_as_billing,
        "status": "CREATED",
    }

    if not order_data["customer_name"] or not order_data["phone"]:
        raise HTTPException(status_code=400, detail="Customer name and phone are required.")
    if not all(
        order_data[field]
        for field in ("billing_address_1", "billing_pincode", "billing_state", "billing_city")
    ):
        raise HTTPException(status_code=400, detail="Complete billing address is required.")

    items: list[dict[str, Any]] = []
    for index, item in enumerate(line_items, start=1):
        sku = str(item.get("lineitem_sku") or "").strip()
        try:
            quantity = float(item.get("lineitem_quantity") or 0)
            selling_price = float(item.get("selling_price_new") or 0)
            mrp = float(item.get("lineitem_price") or 0)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Invalid numeric value in line item {index}.")

        if not sku or quantity <= 0:
            raise HTTPException(status_code=400, detail=f"SKU and positive quantity required in line item {index}.")

        items.append({
            "sku_code": sku,
            "quantity": quantity,
            "shelf_life_type": "None",
            "mrp": mrp,
            "selling_price": selling_price,
            "discount_amount": 0,
            "is_non_sellable": "No",
            "zone": item.get("zone"),
        })

    if not order_data["same_as_billing"] and not all(
        order_data[field]
        for field in ("shipping_address_1", "shipping_pincode", "shipping_state", "shipping_city")
    ):
        raise HTTPException(status_code=400, detail="Complete shipping address is required when it differs from billing.")

    try:
        response = _get_supabase().rpc(
            "create_sales_order_from_sheet",
            {
                "p_request_key": request_key,
                "p_order": order_data,
                "p_items": items,
            },
        ).execute()
        result = response.data
        if isinstance(result, list) and result:
            result = result[0]
        if not isinstance(result, dict) or result.get("status") != "SUCCESS":
            raise RuntimeError(f"Unexpected database response: {result!r}")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        # Do not expose database credentials or internal connection details.
        raise HTTPException(status_code=500, detail="Sales Order creation failed. Check the Render service logs.") from exc
