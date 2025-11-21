import frappe
from erpnext.manufacturing.doctype.bom.bom import get_bom_items_as_dict
from frappe.utils import cint, nowdate, flt, add_days
from frappe.email.doctype.email_template.email_template import get_email_template


def on_submit(doc, method=None):
    frappe.enqueue(
        create_purchase_orders,
        doc=doc,
        queue="long",
        timeout=300,
        job_name=f"Create PO for Sales Order {doc.name}",
    )
    frappe.msgprint(
        f"Background job started for creating Purchase Orders for {doc.name}"
    )


def create_purchase_orders(doc):
    warehouse = (
        doc.set_warehouse
        or frappe.db.get_single_value("Stock Settings", "default_warehouse")
        or frappe.get_value(
            "Warehouse",
            {"is_group": 0, "disabled": 0, "company": doc.company},
            "name",
            order_by="creation",
        )
        or f"Stores - {doc.company}"
    )

    required_items = {}
    for so_item in doc.items:
        item_code = so_item.item_code
        qty = so_item.qty
        bom_no = so_item.bom_no or frappe.db.get_value(
            "Item", item_code, "default_bom", cache=True
        )
        if not bom_no:
            required_items[item_code] = required_items.get(item_code, 0) + qty
        else:
            bom_items = get_bom_items_as_dict(
                bom_no, doc.company, qty=qty, fetch_exploded=True
            )
            for code, detail in bom_items.items():
                required_items[code] = required_items.get(code, 0) + detail["qty"]

    to_order = {}
    for item_code, required_qty in required_items.items():
        item = frappe.get_doc("Item", item_code)
        if not item.is_purchase_item:
            continue

        reorder_level = 0
        reorder_qty = 0
        min_order_qty = flt(item.min_order_qty) or 0
        for rl in item.get("reorder_levels", []):
            if rl.warehouse == warehouse:
                reorder_level = flt(rl.warehouse_reorder_level) or 0
                reorder_qty = rl.warehouse_reorder_qty or 0
                break

        stock = flt(
            frappe.db.get_value(
                "Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"
            )
            or 0
        )

        order_qty = required_qty
        if stock < reorder_level:
            # order_qty += (reorder_level - stock) + reorder_qty
            order_qty += reorder_qty
        order_qty = max(order_qty, min_order_qty)

        if order_qty > 0:
            to_order[item_code] = {
                "qty": order_qty,
                "item": item,
                "required_qty": required_qty,
            }

    supplier_items = {}
    no_supplier_items = []

    for item_code, data in to_order.items():
        item = data["item"]
        if not item.get("supplier_items"):
            no_supplier_items.append(f"{item_code} (no supplier)")
            continue

        po_data = frappe.db.sql(
            """
            WITH last_10_records AS (
                SELECT poi.rate, po.supplier, COALESCE(po.transaction_date, po.creation) AS tx_date
                FROM `tabPurchase Order Item` poi
                JOIN `tabPurchase Order` po ON poi.parent = po.name
                WHERE poi.item_code = %s AND po.docstatus = 1
                ORDER BY tx_date DESC
                LIMIT 10
            )
            SELECT 
                supplier, 
                MIN(rate) AS lowest_rate,
                MAX(tx_date) AS latest_date  
            FROM last_10_records
            GROUP BY supplier
            ORDER BY lowest_rate ASC
            LIMIT 1; 
            """,
            (item_code,),
            as_dict=True,
        )

        if po_data:
            best_supplier = po_data[0].supplier
            best_rate = flt(po_data[0].lowest_rate)
            best_date = po_data[0].latest_date
        else:
            fallback_data = frappe.db.sql(
                """
                SELECT po.supplier, MIN(poi.rate) AS min_rate
                FROM `tabPurchase Order Item` poi
                JOIN `tabPurchase Order` po ON poi.parent = po.name
                WHERE poi.item_code = %s AND po.docstatus = 1
                GROUP BY po.supplier
                ORDER BY min_rate ASC
                LIMIT 1;
                """,
                (item_code,),
                as_dict=True,
            )
            if fallback_data:
                best_supplier = fallback_data[0].supplier
                best_rate = flt(fallback_data[0].min_rate)
                best_date = nowdate()
            else:
                no_supplier_items.append(f"{item_code} (no purchase history)")
                continue

        # Group items by this best supplier
        if best_supplier not in supplier_items:
            supplier_items[best_supplier] = []
        supplier_items[best_supplier].append(
            {
                "item_code": item_code,
                "qty": data["qty"],
                "rate": best_rate,
            }
        )

    for supplier, items in supplier_items.items():
        supplier_doc = frappe.get_cached_doc("Supplier", supplier)
        required_days = cint(supplier_doc.get("custom_required_days") or 0)

        schedule_date = add_days(nowdate(), required_days)
        po = frappe.get_doc(
            {
                "doctype": "Purchase Order",
                "supplier": supplier,
                "transaction_date": nowdate(),
                "company": doc.company,
                "schedule_date": schedule_date,
                "set_warehouse": warehouse,
                "items": [],
                "sales_order": doc.name,
            }
        )
        for it in items:
            po.append(
                "items",
                {
                    "item_code": it["item_code"],
                    "qty": it["qty"],
                    "rate": it["rate"],
                    "schedule_date": schedule_date,
                    "warehouse": warehouse,
                    "sales_order": doc.name,
                },
            )
        po.insert(ignore_permissions=True)

        if supplier_doc.custom_auto_submit_purchase_order:
            po.submit()

        if supplier_doc.custom_auto_generate_mail:
            send_po_email(po, supplier_doc)
    frappe.db.commit()

    field_value = ", ".join(sorted(set(no_supplier_items))) if no_supplier_items else ""
    doc.db_set("custom_purchase_order_record", field_value, update_modified=False)


def send_po_email(po, supplier_doc):
    """Send PO email using Email Template or fallback HTML. Better email lookup."""
    try:
        email = supplier_doc.email_id
        if not email:
            contacts = frappe.get_all(
                "Contact Email",
                {
                    "parenttype": "Supplier",
                    "parent": supplier_doc.name,
                    "email_id": ["!=", ""],
                },
                "email_id",
                limit=1,
            )
            if contacts:
                email = contacts[0].email_id

        if not email:
            error_msg = f"No email found for Supplier {supplier_doc.name}. Set 'email_id' on Supplier or link a Contact with email."
            frappe.log_error(error_msg, "PO Email: No Email Found")
            frappe.throw(error_msg, title="Email Not Found")

        subject = f"Purchase Order {po.name} from {po.company}"

        attachments = [
            {
                "doctype": "Purchase Order",
                "name": po.name,
                "print_format": "Purchase Order Chapparia",
                "print_format_attachment": 1,
            }
        ]

        template_name = "Purchase Order"

        if frappe.db.exists("Email Template", template_name):
            rendered = get_email_template(template_name, po.as_dict())
            frappe.sendmail(
                recipients=email,
                subject=rendered.get("subject"),
                message=rendered.get("message"),
                attachments=attachments,
                reference_doctype="Purchase Order",
                reference_name=po.name,
                now=True,
                retry=3,
                add_unsubscribe_link=False,
            )
        else:
            items_html = ""
            for item in po.items:
                items_html += f"""
                <tr>
                    <td>{item.item_code}</td>
                    <td>{item.item_name or ''}</td>
                    <td>{item.qty}</td>
                </tr>
                """

            message = f"""
            <p>Dear {supplier_doc.supplier_name},</p>
            <p>Please find attached Purchase Order <strong>{po.name}</strong>.</p>
            <h3>Items:</h3>
            <table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; width: 100%;">
                <tr style="background-color: #f0f0f0;">
                    <th>Item</th><th>Description</th><th>Qty</th>
                </tr>
                {items_html}
            </table>
            <p>Kindly deliver the above items <strong>by {po.schedule_date}</strong></p>
            <p>View: <a href="{frappe.utils.get_url(po.get_url())}">Online Link</a></p>
            <p>Thank you,<br>{po.company}</p>
            """

            frappe.sendmail(
                recipients=[email],
                subject=subject,
                message=message,
                attachments=attachments,
                reference_doctype="Purchase Order",
                reference_name=po.name,
                now=True,
                retry=3,
                add_unsubscribe_link=False,
            )

        frappe.msgprint(
            f"Email sent successfully to {email} for PO {po.name}", indicator="green"
        )

    except frappe.ValidationError as ve:
        frappe.throw(ve)
    except Exception as e:
        error_msg = (
            f"Failed to send PO email for {po.name} to {email or 'unknown'}: {str(e)}"
        )
        frappe.log_error(error_msg, "PO Email Send Failed")
        frappe.msgprint(error_msg, indicator="red", title="Email Send Failed")
