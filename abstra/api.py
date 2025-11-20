
import frappe
from frappe.utils import flt


@frappe.whitelist()
def get_item_history(item_code):
    if not item_code:
        frappe.throw("No item code provided")

    if not isinstance(item_code, str):
        frappe.throw("Item code must be a string")

    query = """
        SELECT
            poi.item_code as item,
            po.supplier_name as supplier,
            po.name as purchase_order,
            po.transaction_date as purchase_date,
            poi.qty,
            poi.rate
        FROM
            `tabPurchase Order Item` poi
        JOIN
            `tabPurchase Order` po ON poi.parent = po.name
        WHERE
            poi.item_code = %(item_code)s
            AND po.docstatus = 1
        ORDER BY
            po.transaction_date DESC
        LIMIT 10
    """

    data = frappe.db.sql(query, {'item_code': item_code}, as_dict=True)

    return data


@frappe.whitelist()
def get_project_fg_items(project_master, project_qty=1, delivery_date=None):
    try:
        project_doc = frappe.get_doc("Project Master", project_master)

        if not project_doc.po_items:
            return {"success": False, "message": "No PO Items found in Project Master"}

        items = []
        project_qty = flt(project_qty)

        for po_item in project_doc.po_items:
            rate = 0

            bom_creator = frappe.db.get_value(
                "BOM", po_item.bom_no, "bom_creator")
            if bom_creator:
                rate = frappe.db.get_value(
                    "BOM Creator", bom_creator, "raw_material_cost") or 0

            items.append({
                "item_code": po_item.item_code,
                "item_name": po_item.item_code,
                "delivery_date": delivery_date,
                "bom_no": po_item.bom_no,
                "description": po_item.description,
                "uom": po_item.stock_uom,
                "custom_project_qty": po_item.planned_qty,
                "rate": flt(rate),
                "custom_costing_rate": flt(rate),
                "qty": project_qty * flt(po_item.planned_qty),
                "amount": flt(rate) * flt(project_qty * flt(po_item.planned_qty)),
                "custom_project_master": project_master,
                "custom_project_master_item_reference": po_item.name

            })

        return {"success": True, "items": items, "project": project_doc.project}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_project_fg_items Error")
        return {"success": False, "message": str(e)}
