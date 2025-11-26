# """
# Debug script to monitor PO creation process
# Run this from bench console: bench console
# Then: from abstra.debug_po_creation import debug_sales_order
#      debug_sales_order('SAL-ORD-2025-00003')
# """

# import frappe
# from frappe.utils import flt
# import json


# def debug_sales_order(sales_order_name):
#     """
#     Debug the PO creation process for a Sales Order
#     Shows all calculations step by step
#     """
#     print("\n" + "=" * 80)
#     print(f"DEBUGGING SALES ORDER: {sales_order_name}")
#     print("=" * 80 + "\n")

#     # Get Sales Order
#     so = frappe.get_doc("Sales Order", sales_order_name)
#     print(f"Sales Order: {so.name}")
#     print(f"Company: {so.company}")
#     print(f"Customer: {so.customer}")
#     print(f"Status: {so.status}")
#     print(f"Items: {len(so.items)}")
#     print()

#     # Determine warehouse
#     warehouse = (
#         so.set_warehouse
#         or frappe.db.get_single_value("Stock Settings", "default_warehouse")
#         or frappe.get_value(
#             "Warehouse",
#             {"is_group": 0, "disabled": 0, "company": so.company},
#             "name",
#             order_by="creation",
#         )
#         or f"Stores - {so.company}"
#     )
#     print(f"Warehouse: {warehouse}\n")

#     # Process each SO item
#     print("PROCESSING SALES ORDER ITEMS:")
#     print("-" * 80)

#     required_items = {}

#     for idx, so_item in enumerate(so.items, 1):
#         print(f"\n{idx}. Item: {so_item.item_code}")
#         print(f"   Qty: {so_item.qty}")
#         print(f"   Rate: {so_item.rate}")
#         print(f"   Amount: {so_item.amount}")

#         # Check for BOM
#         bom_no = so_item.bom_no or frappe.db.get_value(
#             "Item", so_item.item_code, "default_bom", cache=True
#         )

#         if not bom_no:
#             print(f"   BOM: Not found - will order item directly")
#             required_items[so_item.item_code] = (
#                 required_items.get(so_item.item_code, 0) + so_item.qty
#             )
#         else:
#             print(f"   BOM: {bom_no}")

#             # Get BOM items
#             from erpnext.manufacturing.doctype.bom.bom import get_bom_items_as_dict

#             bom_items = get_bom_items_as_dict(
#                 bom_no, so.company, qty=so_item.qty, fetch_exploded=True
#             )

#             print(f"   BOM Components: {len(bom_items)}")
#             for code, detail in bom_items.items():
#                 print(f"      - {code}: {detail['qty']} {detail.get('uom', '')}")
#                 required_items[code] = required_items.get(code, 0) + detail["qty"]

#     # Summary of required items
#     print("\n" + "=" * 80)
#     print("REQUIRED ITEMS SUMMARY:")
#     print("=" * 80)
#     for item_code, qty in required_items.items():
#         print(f"{item_code}: {qty}")

#     # Check stock and reorder levels
#     print("\n" + "=" * 80)
#     print("STOCK ANALYSIS:")
#     print("=" * 80)

#     to_order = {}

#     for item_code, required_qty in required_items.items():
#         print(f"\n{item_code}:")

#         # Get item details
#         item = frappe.get_doc("Item", item_code)
#         print(f"  Is Purchase Item: {item.is_purchase_item}")

#         if not item.is_purchase_item:
#             print(f"  SKIPPED - Not a purchase item")
#             continue

#         # Get reorder levels
#         reorder_level = 0
#         reorder_qty = 0
#         min_order_qty = flt(item.min_order_qty) or 0

#         for rl in item.get("reorder_levels", []):
#             if rl.warehouse == warehouse:
#                 reorder_level = flt(rl.warehouse_reorder_level) or 0
#                 reorder_qty = flt(rl.warehouse_reorder_qty) or 0
#                 break

#         # Get current stock
#         stock = flt(
#             frappe.db.get_value(
#                 "Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"
#             )
#             or 0
#         )

#         print(f"  Current Stock: {stock}")
#         print(f"  Required Qty: {required_qty}")
#         print(f"  Reorder Level: {reorder_level}")
#         print(f"  Reorder Qty: {reorder_qty}")
#         print(f"  Min Order Qty: {min_order_qty}")

#         # Calculate order qty
#         order_qty = required_qty
#         if stock < reorder_level:
#             print(f"  STATUS: Stock below reorder level!")
#             order_qty += reorder_qty

#         order_qty = max(order_qty, min_order_qty)
#         print(f"  ORDER QTY: {order_qty}")

#         if order_qty > 0:
#             to_order[item_code] = {
#                 "qty": order_qty,
#                 "item": item,
#             }

#     # Find suppliers
#     print("\n" + "=" * 80)
#     print("SUPPLIER ANALYSIS:")
#     print("=" * 80)

#     supplier_items = {}
#     no_supplier_items = []

#     for item_code, data in to_order.items():
#         print(f"\n{item_code}:")
#         item = data["item"]

#         # Check if suppliers configured
#         if not item.get("supplier_items"):
#             print(f"  ERROR: No suppliers configured")
#             no_supplier_items.append(f"{item_code} (no supplier)")
#             continue

#         print(f"  Configured Suppliers: {len(item.supplier_items)}")
#         for si in item.supplier_items:
#             print(f"    - {si.supplier}")

#         # Find best supplier from purchase history
#         po_data = frappe.db.sql(
#             """
#             WITH last_10_records AS (
#                 SELECT 
#                     poi.rate, 
#                     po.supplier, 
#                     COALESCE(po.transaction_date, po.creation) AS tx_date
#                 FROM `tabPurchase Order Item` poi
#                 JOIN `tabPurchase Order` po ON poi.parent = po.name
#                 WHERE poi.item_code = %s AND po.docstatus = 1
#                 ORDER BY tx_date DESC
#                 LIMIT 10
#             )
#             SELECT 
#                 supplier, 
#                 MIN(rate) AS lowest_rate,
#                 MAX(tx_date) AS latest_date,
#                 COUNT(*) as order_count
#             FROM last_10_records
#             GROUP BY supplier
#             ORDER BY lowest_rate ASC
#             """,
#             (item_code,),
#             as_dict=True,
#         )

#         if po_data:
#             print(f"  Purchase History (Last 10 Orders):")
#             for idx, row in enumerate(po_data, 1):
#                 print(
#                     f"    {idx}. {row.supplier}: Rate={row.lowest_rate}, Orders={row.order_count}, Last={row.latest_date}"
#                 )

#             best_supplier = po_data[0].supplier
#             best_rate = flt(po_data[0].lowest_rate)

#             print(f"  SELECTED: {best_supplier} @ {best_rate}")

#             if best_supplier not in supplier_items:
#                 supplier_items[best_supplier] = []

#             supplier_items[best_supplier].append(
#                 {
#                     "item_code": item_code,
#                     "qty": data["qty"],
#                     "rate": best_rate,
#                 }
#             )
#         else:
#             print(f"  ERROR: No purchase history found")
#             no_supplier_items.append(f"{item_code} (no purchase history)")

#     # Summary
#     print("\n" + "=" * 80)
#     print("FINAL SUMMARY:")
#     print("=" * 80)
#     print(f"Total Items to Order: {len(to_order)}")
#     print(f"Suppliers Identified: {len(supplier_items)}")
#     print(f"Items Without Supplier: {len(no_supplier_items)}")

#     if supplier_items:
#         print("\nPURCHASE ORDERS TO CREATE:")
#         for supplier, items in supplier_items.items():
#             print(f"\n  Supplier: {supplier}")
#             total_amount = 0
#             for it in items:
#                 amount = it["qty"] * it["rate"]
#                 total_amount += amount
#                 print(f"    - {it['item_code']}: {it['qty']} @ {it['rate']} = {amount}")
#             print(f"  Total Amount: {total_amount}")

#     if no_supplier_items:
#         print("\nITEMS THAT CANNOT BE ORDERED:")
#         for item in no_supplier_items:
#             print(f"  - {item}")

#     print("\n" + "=" * 80)
#     print("DEBUG COMPLETE")
#     print("=" * 80 + "\n")


# def check_item_setup(item_code):
#     """Check if an item is properly configured for automatic PO creation"""
#     print("\n" + "=" * 80)
#     print(f"CHECKING ITEM SETUP: {item_code}")
#     print("=" * 80 + "\n")

#     if not frappe.db.exists("Item", item_code):
#         print("ERROR: Item does not exist!")
#         return

#     item = frappe.get_doc("Item", item_code)

#     print(f"Item Code: {item.item_code}")
#     print(f"Item Name: {item.item_name}")
#     print(f"Is Purchase Item: {item.is_purchase_item}")
#     print(f"Default BOM: {item.default_bom or 'Not Set'}")
#     print(f"Min Order Qty: {item.min_order_qty or 0}")
#     print()

#     # Check suppliers
#     print("SUPPLIERS:")
#     if not item.supplier_items:
#         print("  ERROR: No suppliers configured!")
#     else:
#         for idx, si in enumerate(item.supplier_items, 1):
#             print(f"  {idx}. {si.supplier} - {si.supplier_part_no or 'No Part No'}")
#     print()

#     # Check reorder levels
#     print("REORDER LEVELS:")
#     if not item.reorder_levels:
#         print("  WARNING: No reorder levels set")
#     else:
#         for idx, rl in enumerate(item.reorder_levels, 1):
#             print(f"  {idx}. Warehouse: {rl.warehouse}")
#             print(f"     Reorder Level: {rl.warehouse_reorder_level}")
#             print(f"     Reorder Qty: {rl.warehouse_reorder_qty}")
#     print()

#     # Check purchase history
#     print("PURCHASE HISTORY (Last 5):")
#     history = frappe.db.sql(
#         """
#         SELECT 
#             po.name,
#             po.supplier,
#             po.transaction_date,
#             poi.qty,
#             poi.rate
#         FROM `tabPurchase Order Item` poi
#         JOIN `tabPurchase Order` po ON poi.parent = po.name
#         WHERE poi.item_code = %s AND po.docstatus = 1
#         ORDER BY po.transaction_date DESC
#         LIMIT 5
#     """,
#         (item_code,),
#         as_dict=True,
#     )

#     if not history:
#         print("  WARNING: No purchase history found")
#     else:
#         for idx, h in enumerate(history, 1):
#             print(f"  {idx}. PO: {h.name}")
#             print(f"     Supplier: {h.supplier}")
#             print(f"     Date: {h.transaction_date}")
#             print(f"     Qty: {h.qty}, Rate: {h.rate}")

#     print("\n" + "=" * 80)
#     print("CHECK COMPLETE")
#     print("=" * 80 + "\n")


# def view_error_logs(limit=5):
#     """View recent error logs"""
#     print("\n" + "=" * 80)
#     print("RECENT ERROR LOGS")
#     print("=" * 80 + "\n")

#     logs = frappe.get_all(
#         "Error Log",
#         filters={"error": ["like", "%PO%"]},
#         fields=["name", "creation", "error", "method"],
#         order_by="creation desc",
#         limit=limit,
#     )

#     if not logs:
#         print("No recent PO-related errors found")
#         return

#     for idx, log in enumerate(logs, 1):
#         print(f"\n{idx}. Error Log: {log.name}")
#         print(f"   Time: {log.creation}")
#         print(f"   Method: {log.method}")
#         print(f"   Error: {log.error[:200]}...")
#         print("-" * 80)
