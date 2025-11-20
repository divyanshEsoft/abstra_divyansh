import frappe

def on_submit(self, method=None):    
    if not self.custom_sales_order:
        return

    if not self.custom_selected_project:
        frappe.msgprint("No selected project found; skipping Sales Order update.")
        return

    selected_row = None
    for row in self.get("custom_project_master_of_sales_order") or []:
        if str(row.idx) == str(self.custom_selected_project):
            selected_row = row
            break

    if not selected_row:
        frappe.msgprint("Selected project row not found; skipping Sales Order update.")
        return

    if not selected_row.project_master_ref_sales_order:
        frappe.msgprint("No reference found for the selected project in Sales Order.")
        return

    try:
        original_pending = frappe.db.get_value(
            "Sales Order Project Master",
            selected_row.project_master_ref_sales_order,
            "pending_qty"
        )

        if original_pending is None:
            frappe.throw("Could not find linked Sales Order Project Master row.")

        if (selected_row.project_qty or 0) > (original_pending or 0):
            frappe.throw(
                f"Cannot submit Production Plan — Project Qty ({selected_row.project_qty}) "
                f"cannot exceed Pending Qty ({original_pending})."
            )

        new_pending = max((original_pending or 0) - (selected_row.project_qty or 0), 0)

        frappe.db.set_value(
            "Sales Order Project Master",
            selected_row.project_master_ref_sales_order,
            "pending_qty",
            new_pending
        )

        frappe.msgprint(
            f"Updated pending qty in Sales Order Project Master: "
            f"<b>{selected_row.project_master_ref_sales_order}</b> "
            f"from {original_pending} → {new_pending}"
        )

    except frappe.DoesNotExistError:
        frappe.throw(f"Linked Sales Order {self.custom_sales_order} not found.")


