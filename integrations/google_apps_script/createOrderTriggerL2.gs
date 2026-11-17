/**
 * Separate Google Sheets -> L2 Sales Order trigger.
 *
 * Does not replace or modify the existing createOrderTrigger() EMIZA flow.
 * Configure Script Properties:
 *   L2_SALES_ORDER_API_URL   e.g. https://<your-render-service>/create-order
 *   L2_SALES_ORDER_API_TOKEN <secret token>
 *
 * Add a menu item to the existing onOpen() only when you want it visible:
 *   .addItem("Create L2 Orders", "createOrderTriggerL2")
 */
function createOrderTriggerL2() {
  const SHEET_NAME = "ORDER SHEET";
  const props = PropertiesService.getScriptProperties();
  const apiUrl = (props.getProperty("L2_SALES_ORDER_API_URL") || "").trim();
  const apiToken = (props.getProperty("L2_SALES_ORDER_API_TOKEN") || "").trim();
  if (!apiUrl || !apiToken) {
    throw new Error("Set L2_SALES_ORDER_API_URL and L2_SALES_ORDER_API_TOKEN in Script Properties.");
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) throw new Error('Sheet "' + SHEET_NAME + '" not found.');

  const values = sheet.getDataRange().getValues();
  if (values.length < 2) return;

  const headers = values[0].map(h => String(h).trim().toUpperCase());
  const index = {};
  headers.forEach((h, i) => { if (h) index[h] = i; });

  const required = [
    "PARTY", "PHONE", "BILLING_ADDRESS1", "WARHOUSE SELECT SO",
    "TRIGGER", "STATUS", "ORDER_ID", "SKU", "QTY BILLED", "PRICE"
  ];
  const missing = required.filter(h => index[h] === undefined);
  if (missing.length) throw new Error("Missing ORDER SHEET columns: " + missing.join(", "));

  const value = (row, header) => index[header] === undefined ? "" : row[index[header]];
  const text = v => v === null || v === undefined ? "" : String(v).trim();
  const truthy = v => ["TRUE", "YES", "1", "Y"].includes(text(v).toUpperCase());
  const number = (v, fallback) => {
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  };

  // Only rows explicitly triggered for L2 are included. Other warehouse
  // triggers remain available to the existing EMIZA automation.
  const groups = new Map();
  values.slice(1).forEach((row, offset) => {
    const sheetRow = offset + 2;
    if (text(value(row, "TRIGGER")).toUpperCase() !== "YES") return;
    if (text(value(row, "WARHOUSE SELECT SO")).toUpperCase() !== "L2") return;

    const party = text(value(row, "PARTY"));
    const phone = text(value(row, "PHONE"));
    const billing1 = text(value(row, "BILLING_ADDRESS1"));
    const warehouse = text(value(row, "WARHOUSE SELECT SO")).toUpperCase();
    const groupKey = [party, phone, billing1, warehouse].join("¦");

    if (!groups.has(groupKey)) groups.set(groupKey, { rows: [], items: [], rowNumbers: [] });
    const group = groups.get(groupKey);
    group.rows.push(row);
    group.rowNumbers.push(sheetRow);
    group.items.push({
      lineitem_sku: text(value(row, "SKU")),
      lineitem_quantity: number(value(row, "QTY BILLED"), 0),
      lineitem_price: 0,
      selling_price_new: number(value(row, "PRICE"), 0),
      zone: null
    });
  });

  let created = 0;
  for (const [groupKey, group] of groups.entries()) {
    const first = group.rows[0];
    const sameAsBilling = truthy(value(first, "SAME_AS_BILLING"));
    const billingAddress1 = text(value(first, "BILLING_ADDRESS1"));
    const billingAddress2 = text(value(first, "BILLING_ADDRESS2"));
    const billingState = text(value(first, "BILLING_STATE"));
    const billingCity = text(value(first, "BILLING_CITY"));
    const billingPincode = text(value(first, "BILLING_PINCODE"));

    const shippingAddress1 = sameAsBilling ? billingAddress1 : text(value(first, "SHIPPING_ADDRESS1"));
    const shippingAddress2 = sameAsBilling ? billingAddress2 : text(value(first, "SHIPPING_ADDRESS2"));
    const shippingState = sameAsBilling ? billingState : text(value(first, "SHIPPING_STATE"));
    const shippingCity = sameAsBilling ? billingCity : text(value(first, "SHIPPING_CITY"));
    const shippingPincode = sameAsBilling ? billingPincode : text(value(first, "SHIPPING_PINCODE"));

    try {
      if (!text(value(first, "PARTY")) || !text(value(first, "PHONE"))) {
        throw new Error("PARTY and PHONE are required.");
      }
      if (!billingAddress1 || !billingState || !billingCity || !billingPincode) {
        throw new Error("Complete billing address is required.");
      }
      if (!shippingAddress1 || !shippingState || !shippingCity || !shippingPincode) {
        throw new Error("Complete shipping address is required.");
      }
      if (!group.items.length || group.items.some(i => !i.lineitem_sku || i.lineitem_quantity <= 0)) {
        throw new Error("Every line must have SKU and positive QTY BILLED.");
      }

      // Stable across retries for this exact group of source rows.
      const requestSeed = ss.getId() + "|" + sheet.getSheetId() + "|" + group.rowNumbers.slice().sort((a,b) => a-b).join(",");
      const digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, requestSeed);
      const requestKey = digest.map(b => ("0" + ((b + 256) % 256).toString(16)).slice(-2)).join("");

      const payload = {
        request_key: requestKey,
        warehouse: "L2",
        name: text(value(first, "PARTY")),
        phone: text(value(first, "PHONE")),
        email: text(value(first, "EMAIL")),
        alternate_phone: text(value(first, "ALTERNATE_PHONE")),
        same_as_billing: sameAsBilling,
        billing_address1: billingAddress1,
        billing_address2: billingAddress2,
        billing_state: billingState,
        billing_city: billingCity,
        billing_pincode: billingPincode,
        shipping_name: text(value(first, "SHIPPING_NAME")) || text(value(first, "PARTY")),
        shipping_phone: text(value(first, "SHIPPING_PHONE")) || text(value(first, "PHONE")),
        shipping_address1: shippingAddress1,
        shipping_address2: shippingAddress2,
        shipping_state: shippingState,
        shipping_city: shippingCity,
        shipping_pincode: shippingPincode,
        business_type: text(value(first, "BUSINESS_TYPE")),
        source: "seller-dashboard",
        uploaded_by: text(value(first, "UPLOADED_BY")),
        remarks: text(value(first, "REMARKS IN SO")),
        line_items: group.items
      };

      const response = UrlFetchApp.fetch(apiUrl, {
        method: "post",
        contentType: "application/json",
        headers: { "X-API-Key": apiToken },
        payload: JSON.stringify(payload),
        muteHttpExceptions: true
      });

      const statusCode = response.getResponseCode();
      const responseText = response.getContentText();
      let result = {};
      try { result = JSON.parse(responseText || "{}"); } catch (parseError) {}

      if (statusCode < 200 || statusCode >= 300 || !result.order_id) {
        throw new Error(result.detail || result.message || ("HTTP " + statusCode + ": " + responseText));
      }

      group.rowNumbers.forEach(r => {
        sheet.getRange(r, index["STATUS"] + 1).setValue("CREATED");
        sheet.getRange(r, index["ORDER_ID"] + 1).setValue(result.order_id);
        sheet.getRange(r, index["TRIGGER"] + 1).setValue("DONE");
      });
      created++;
    } catch (err) {
      group.rowNumbers.forEach(r => {
        sheet.getRange(r, index["STATUS"] + 1).setValue("ERROR: " + String(err.message || err).slice(0, 450));
        // Leave TRIGGER=YES so the group can be retried after correction.
      });
    }
  }

  SpreadsheetApp.getActiveSpreadsheet().toast(
    created + " L2 Sales Order group(s) created.",
    "L2 Order Sync",
    5
  );
}
