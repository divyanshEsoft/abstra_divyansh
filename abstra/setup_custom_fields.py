# """
# Setup script to create required custom fields for Sales Order PO automation
# Run this once from bench console:
#     bench console
#     from abstra.setup_custom_fields import setup_sales_order_fields
#     setup_sales_order_fields()
# """

# import frappe


# def setup_sales_order_fields():
#     """Create all required custom fields for Sales Order"""
#     print("\n" + "=" * 80)
#     print("SETTING UP CUSTOM FIELDS FOR SALES ORDER")
#     print("=" * 80 + "\n")

#     fields_to_create = [
#         {
#             "fieldname": "custom_purchase_order_record",
#             "label": "Items Without Supplier",
#             "fieldtype": "Long Text",
#             "insert_after": "items",
#             "read_only": 1,
#             "description": "Items that could not be ordered automatically (no supplier or no purchase history)",
#         },
#         {
#             "fieldname": "custom_po_creation_section",
#             "label": "Purchase Order Creation",
#             "fieldtype": "Section Break",
#             "insert_after": "items",
#             "collapsible": 1,
#         },
#         {
#             "fieldname": "custom_auto_create_po",
#             "label": "Auto Create Purchase Orders",
#             "fieldtype": "Check",
#             "insert_after": "custom_po_creation_section",
#             "default": "1",
#             "description": "Automatically create purchase orders when this sales order is submitted",
#         },
#     ]

#     for field_config in fields_to_create:
#         fieldname = field_config["fieldname"]

#         # Check if field already exists
#         existing = frappe.db.exists(
#             "Custom Field", {"dt": "Sales Order", "fieldname": fieldname}
#         )

#         if existing:
#             print(f"✓ Field '{fieldname}' already exists")
#             continue

#         try:
#             # Create custom field
#             custom_field = frappe.get_doc(
#                 {"doctype": "Custom Field", "dt": "Sales Order", **field_config}
#             )
#             custom_field.insert(ignore_permissions=True)
#             print(f"✓ Created field '{fieldname}'")

#         except Exception as e:
#             print(f"✗ Error creating field '{fieldname}': {str(e)}")

#     frappe.db.commit()
#     print("\n" + "=" * 80)
#     print("CUSTOM FIELDS SETUP COMPLETE")
#     print("=" * 80 + "\n")
#     print("Please run: bench clear-cache")
#     print("Then refresh your browser\n")


# def setup_supplier_fields():
#     """Create custom fields for Supplier to control PO behavior"""
#     print("\n" + "=" * 80)
#     print("SETTING UP CUSTOM FIELDS FOR SUPPLIER")
#     print("=" * 80 + "\n")

#     fields_to_create = [
#         {
#             "fieldname": "custom_po_automation_section",
#             "label": "PO Automation Settings",
#             "fieldtype": "Section Break",
#             "insert_after": "is_internal_supplier",
#             "collapsible": 1,
#         },
#         {
#             "fieldname": "custom_required_days",
#             "label": "Required Days for Delivery",
#             "fieldtype": "Int",
#             "insert_after": "custom_po_automation_section",
#             "default": "7",
#             "description": "Number of days required for this supplier to deliver items",
#         },
#         {
#             "fieldname": "custom_column_break_1",
#             "fieldtype": "Column Break",
#             "insert_after": "custom_required_days",
#         },
#         {
#             "fieldname": "custom_auto_submit_purchase_order",
#             "label": "Auto Submit Purchase Order",
#             "fieldtype": "Check",
#             "insert_after": "custom_column_break_1",
#             "default": "0",
#             "description": "Automatically submit purchase orders created for this supplier",
#         },
#         {
#             "fieldname": "custom_auto_generate_mail",
#             "label": "Auto Send Email",
#             "fieldtype": "Check",
#             "insert_after": "custom_auto_submit_purchase_order",
#             "default": "0",
#             "description": "Automatically send email to supplier when PO is created",
#         },
#     ]

#     for field_config in fields_to_create:
#         fieldname = field_config["fieldname"]

#         # Check if field already exists
#         existing = frappe.db.exists(
#             "Custom Field", {"dt": "Supplier", "fieldname": fieldname}
#         )

#         if existing:
#             print(f"✓ Field '{fieldname}' already exists")
#             continue

#         try:
#             # Create custom field
#             custom_field = frappe.get_doc(
#                 {"doctype": "Custom Field", "dt": "Supplier", **field_config}
#             )
#             custom_field.insert(ignore_permissions=True)
#             print(f"✓ Created field '{fieldname}'")

#         except Exception as e:
#             print(f"✗ Error creating field '{fieldname}': {str(e)}")

#     frappe.db.commit()
#     print("\n" + "=" * 80)
#     print("SUPPLIER FIELDS SETUP COMPLETE")
#     print("=" * 80 + "\n")


# def setup_all_fields():
#     """Setup all required custom fields"""
#     setup_sales_order_fields()
#     setup_supplier_fields()
#     print("\n✓ All custom fields created successfully!")
#     print("Run: bench clear-cache")
#     print("Then refresh your browser\n")


# def remove_custom_fields():
#     """Remove all custom fields created by this script (for cleanup/testing)"""
#     print("\n" + "=" * 80)
#     print("REMOVING CUSTOM FIELDS")
#     print("=" * 80 + "\n")

#     fields_to_remove = {
#         "Sales Order": [
#             "custom_purchase_order_record",
#             "custom_po_creation_section",
#             "custom_auto_create_po",
#         ],
#         "Supplier": [
#             "custom_po_automation_section",
#             "custom_required_days",
#             "custom_column_break_1",
#             "custom_auto_submit_purchase_order",
#             "custom_auto_generate_mail",
#         ],
#     }

#     for doctype, fieldnames in fields_to_remove.items():
#         for fieldname in fieldnames:
#             try:
#                 if frappe.db.exists(
#                     "Custom Field", {"dt": doctype, "fieldname": fieldname}
#                 ):
#                     frappe.delete_doc(
#                         "Custom Field",
#                         frappe.db.get_value(
#                             "Custom Field",
#                             {"dt": doctype, "fieldname": fieldname},
#                             "name",
#                         ),
#                         force=True,
#                     )
#                     print(f"✓ Removed {doctype}.{fieldname}")
#                 else:
#                     print(f"- Field {doctype}.{fieldname} does not exist")
#             except Exception as e:
#                 print(f"✗ Error removing {doctype}.{fieldname}: {str(e)}")

#     frappe.db.commit()
#     print("\n" + "=" * 80)
#     print("REMOVAL COMPLETE")
#     print("=" * 80 + "\n")


# if __name__ == "__main__":
#     setup_all_fields()
