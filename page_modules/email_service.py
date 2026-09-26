from __future__ import annotations

import os
import re
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import streamlit as st


# =========================================================
# SECRET HELPER
# =========================================================

def _get_secret(key: str, default: str = "") -> str:
    try:
        value = st.secrets.get(key)

        if value is not None:
            return str(value).strip()

    except Exception:
        pass

    return os.getenv(key, default).strip()


# =========================================================
# SAFE TEXT
# =========================================================

def _safe(value) -> str:
    if value is None:
        return ""

    return str(value).strip()


# =========================================================
# ADDRESS
# =========================================================

def _format_address(
    address_1,
    address_2,
    city,
    state,
    pincode,
) -> str:

    parts = [
        _safe(address_1),
        _safe(address_2),
        _safe(city),
        _safe(state),
        _safe(pincode),
    ]

    return ", ".join(
        part
        for part in parts
        if part
    )


# =========================================================
# EMAIL VALIDATION
# =========================================================

def _is_valid_email(email: str) -> bool:
    """
    Basic email validation.
    """

    email = email.strip()

    if not email:
        return False

    pattern = r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$"

    return bool(
        re.match(pattern, email)
    )


# =========================================================
# EMAIL RECIPIENTS
# =========================================================

def _get_recipients(accounts_email: str) -> list[str]:
    """
    Supports multiple email addresses.

    Example:

    accounts@gmail.com, manager@company.com

    Also supports:

    accounts@gmail.com; manager@company.com
    """

    if not accounts_email:
        return []

    # Normalize separators
    accounts_email = (
        accounts_email
        .replace(";", ",")
        .replace("\n", ",")
        .replace("\r", ",")
    )

    # Split by comma
    raw_recipients = accounts_email.split(",")

    recipients = []

    for email in raw_recipients:

        email = email.strip()

        if not email:
            continue

        if _is_valid_email(email):
            recipients.append(email)

    # Remove duplicates while preserving order
    unique_recipients = list(
        dict.fromkeys(recipients)
    )

    return unique_recipients


# =========================================================
# SEND GATE OUT EMAIL
# =========================================================

def send_gate_out_email(
    order_data: dict,
    gate_out_items: list[dict],
    processed_by: str = "",
) -> tuple[bool, str | None]:

    # =====================================================
    # EMAIL CONFIG
    # =====================================================

    sender_email = _get_secret(
        "WMS_EMAIL"
    )

    sender_password = _get_secret(
        "WMS_EMAIL_PASSWORD"
    )

    accounts_email = _get_secret(
        "ACCOUNTS_EMAIL"
    )

    smtp_host = _get_secret(
        "SMTP_HOST",
        "smtp.gmail.com",
    )

    smtp_port_raw = _get_secret(
        "SMTP_PORT",
        "465",
    )

    try:
        smtp_port = int(
            smtp_port_raw
        )

    except ValueError:

        return (
            False,
            "SMTP_PORT must be a valid number.",
        )

    # =====================================================
    # CONFIG VALIDATION
    # =====================================================

    if not sender_email:

        return (
            False,
            "WMS_EMAIL is not configured.",
        )

    if not sender_password:

        return (
            False,
            "WMS_EMAIL_PASSWORD is not configured.",
        )

    if not accounts_email:

        return (
            False,
            "ACCOUNTS_EMAIL is not configured.",
        )

    # =====================================================
    # GET RECIPIENTS
    # =====================================================

    recipients = _get_recipients(
        accounts_email
    )

    if not recipients:

        return (
            False,
            (
                "No valid Accounts email recipient was found. "
                "Use comma-separated emails, for example: "
                "accounts@gmail.com, manager@gmail.com"
            ),
        )

    # =====================================================
    # ORDER DATA
    # =====================================================

    order_id = _safe(
        order_data.get("order_id")
    )

    customer_name = _safe(
        order_data.get("customer_name")
    )

    customer_email = _safe(
        order_data.get("email")
    )

    phone = _safe(
        order_data.get("phone")
    )

    alternate_phone = _safe(
        order_data.get("alternate_phone")
    )

    warehouse = _safe(
        order_data.get("warehouse")
    )

    order_type = _safe(
        order_data.get("order_type")
    )

    existing_customer = _safe(
        order_data.get("existing_customer")
    )

    remark = _safe(
        order_data.get("remark")
    )

    # =====================================================
    # BILLING ADDRESS
    # =====================================================

    billing_address = _format_address(
        order_data.get("billing_address_1"),
        order_data.get("billing_address_2"),
        order_data.get("billing_city"),
        order_data.get("billing_state"),
        order_data.get("billing_pincode"),
    )

    # =====================================================
    # SHIPPING ADDRESS
    # =====================================================

    shipping_address = _format_address(
        order_data.get("shipping_address_1"),
        order_data.get("shipping_address_2"),
        order_data.get("shipping_city"),
        order_data.get("shipping_state"),
        order_data.get("shipping_pincode"),
    )

    # =====================================================
    # DATE / TIME
    # =====================================================

    gate_out_time = datetime.now().strftime(
        "%d-%m-%Y %I:%M:%S %p"
    )

    # =====================================================
    # ITEMS
    # =====================================================

    item_rows = ""

    total_qty = 0.0

    for item in gate_out_items:

        sku = _safe(
            item.get("sku_code")
        )

        location = _safe(
            item.get("location")
        )

        item_warehouse = _safe(
            item.get("warehouse")
        )

        # If warehouse is not present in item,
        # use Sales Order warehouse.
        if not item_warehouse:
            item_warehouse = warehouse

        qty = item.get(
            "qty",
            0,
        )

        try:

            total_qty += float(
                qty
            )

        except Exception:
            pass

        rate = _safe(item.get("mrp")) or "-"

        selling_price = _safe(item.get("selling_price")) or "-"

        item_rows += f"""
        <tr>
            <td>{sku}</td>

            <td>{item_warehouse}</td>

            <td>{location}</td>

            <td style="text-align:center;">
                {qty}
            </td>

            <td style="text-align:right;">
                {rate}
            </td>

            <td style="text-align:right;">
                {selling_price}
            </td>
        </tr>
        """

    # =====================================================
    # SUBJECT
    # =====================================================

    subject = (
        f"Gate Out Completed - {order_id}"
    )

    # =====================================================
    # REMARK HTML
    # =====================================================

    remark_html = ""

    if remark:

        remark_html = f"""
        <div class="section">

            <div class="section-title">
                Remark
            </div>

            <table>

                <tr>
                    <td>{remark}</td>
                </tr>

            </table>

        </div>
        """

    # =====================================================
    # EMAIL HTML
    # =====================================================

    html_body = f"""
<!DOCTYPE html>

<html>

<head>

<meta charset="UTF-8">

<style>

body {{
    font-family: Arial, Helvetica, sans-serif;
    background: #f5f6f8;
    margin: 0;
    padding: 20px;
}}

.container {{
    max-width: 900px;
    margin: auto;
    background: #ffffff;
    padding: 25px;
    border-radius: 10px;
}}

.header {{
    font-size: 22px;
    font-weight: 700;
    color: #111827;
    margin-bottom: 15px;
}}

.status {{
    background: #ecfdf5;
    border: 1px solid #bbf7d0;
    color: #166534;
    padding: 12px;
    border-radius: 7px;
    font-weight: 700;
    margin-bottom: 25px;
}}

.section {{
    margin-top: 25px;
}}

.section-title {{
    font-size: 16px;
    font-weight: 700;
    color: #374151;
    margin-bottom: 10px;
}}

table {{
    width: 100%;
    border-collapse: collapse;
}}

th {{
    background: #f3f4f6;
    color: #374151;
    text-align: left;
    padding: 10px;
    border: 1px solid #d1d5db;
}}

td {{
    color: #111827;
    padding: 10px;
    border: 1px solid #d1d5db;
}}

.summary {{
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    padding: 15px;
    border-radius: 7px;
    margin-top: 20px;
    color: #1e3a8a;
}}

.footer {{
    margin-top: 30px;
    font-size: 12px;
    color: #6b7280;
}}

</style>

</head>


<body>

<div class="container">

    <div class="header">
        EMIZA WMS - Gate Out Notification
    </div>

    <div class="status">
        GATE OUT COMPLETED SUCCESSFULLY
    </div>


    <!-- ORDER INFORMATION -->

    <div class="section">

        <div class="section-title">
            Order Information
        </div>

        <table>

            <tr>
                <th>Sales Order</th>
                <td>{order_id}</td>
            </tr>

            <tr>
                <th>Customer</th>
                <td>{customer_name}</td>
            </tr>

            <tr>
                <th>Customer Email</th>
                <td>{customer_email or "-"}</td>
            </tr>

            <tr>
                <th>Phone</th>
                <td>{phone or "-"}</td>
            </tr>

            <tr>
                <th>Alternate Phone</th>
                <td>{alternate_phone or "-"}</td>
            </tr>

            <tr>
                <th>Warehouse</th>
                <td>{warehouse or "-"}</td>
            </tr>

            <tr>
                <th>Order Type</th>
                <td>{order_type or "-"}</td>
            </tr>

            <tr>
                <th>Existing Customer</th>
                <td>{existing_customer or "-"}</td>
            </tr>

            <tr>
                <th>Gate Out Date / Time</th>
                <td>{gate_out_time}</td>
            </tr>

            <tr>
                <th>Processed By</th>
                <td>{processed_by or "-"}</td>
            </tr>

        </table>

    </div>


    <!-- BILLING ADDRESS -->

    <div class="section">

        <div class="section-title">
            Billing Address
        </div>

        <table>

            <tr>
                <td>
                    {billing_address or "-"}
                </td>
            </tr>

        </table>

    </div>


    <!-- SHIPPING ADDRESS -->

    <div class="section">

        <div class="section-title">
            Shipping Address
        </div>

        <table>

            <tr>
                <td>
                    {shipping_address or "-"}
                </td>
            </tr>

        </table>

    </div>


    <!-- GATE OUT ITEMS -->

    <div class="section">

        <div class="section-title">
            Gate Out Items
        </div>

        <table>

            <thead>

                <tr>
                    <th>SKU</th>
                    <th>Warehouse</th>
                    <th>Location</th>
                    <th>Gate Out Qty</th>
                    <th>Rate (MRP)</th>
                    <th>Selling Price</th>
                </tr>

            </thead>

            <tbody>

                {item_rows}

            </tbody>

        </table>

    </div>


    <!-- SUMMARY -->

    <div class="summary">

        <b>Total Gate Out Quantity:</b>
        {total_qty:g}

        <br><br>

        <b>Status:</b>
        COMPLETED

    </div>


    <!-- REMARK -->

    {remark_html}


    <div class="footer">

        This is an automated notification from EMIZA WMS.
        Please do not reply to this email.

    </div>

</div>

</body>

</html>
"""

    # =====================================================
    # CREATE EMAIL
    # =====================================================

    message = MIMEMultipart(
        "alternative"
    )

    message["From"] = sender_email

    # Human-readable header
    message["To"] = ", ".join(
        recipients
    )

    message["Subject"] = subject

    message.attach(
        MIMEText(
            html_body,
            "html",
            "utf-8",
        )
    )

    # =====================================================
    # SEND EMAIL
    # =====================================================

    try:

        with smtplib.SMTP_SSL(
            smtp_host,
            smtp_port,
            timeout=30,
        ) as server:

            # Login with WMS Gmail
            server.login(
                sender_email,
                sender_password,
            )

            # IMPORTANT:
            # This MUST be the list of individual
            # email addresses.
            server.sendmail(
                sender_email,
                list(recipients),
                message.as_string(),
            )

        return (
            True,
            None,
        )

    except smtplib.SMTPAuthenticationError:

        return (
            False,
            (
                "Gmail authentication failed. "
                "Check WMS_EMAIL and make sure "
                "WMS_EMAIL_PASSWORD is the 16-character "
                "Google App Password."
            ),
        )

    except smtplib.SMTPRecipientsRefused as e:

        return (
            False,
            f"One or more recipient emails were refused: {e}",
        )

    except smtplib.SMTPException as e:

        return (
            False,
            f"SMTP error: {e}",
        )

    except Exception as e:

        return (
            False,
            f"Email Error: {e}",
        )
