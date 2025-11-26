import frappe
from erpnext.manufacturing.doctype.bom.bom import get_bom_items_as_dict
from frappe.utils import cint, nowdate, flt, add_days
from frappe.email.doctype.email_template.email_template import get_email_template
import json


def on_submit(doc, method=None):
    """Hook called when Sales Order is submitted"""
    print(f"🎯 SALES ORDER SUBMIT HOOK TRIGGERED")
    print(f"📦 Sales Order: {doc.name}")
    print(f"🏢 Company: {doc.company}")
    print(f"📝 Status: {doc.status}")
    print(f"📦 Items count: {len(doc.items)}")

    try:
        # Log the start
        frappe.logger().info(
            f"=== Sales Order {doc.name} submitted - Starting PO creation ==="
        )

        frappe.enqueue(
            create_purchase_orders,
            docname=doc.name,  # Pass docname instead of doc object
            queue="long",
            timeout=300,
            job_id=f"create_po_for_{doc.name}",  # Fixed: job_id instead of job_name
        )

        frappe.msgprint(
            f"Background job started for creating Purchase Orders for {doc.name}",
            indicator="blue",
        )
        frappe.logger().info(f"Background job enqueued for {doc.name}")
        print(f"✅ Background job enqueued for {doc.name}")

    except Exception as e:
        print(f"❌ ERROR enqueueing PO creation for {doc.name}: {str(e)}")
        frappe.logger().error(f"Error enqueueing PO creation for {doc.name}: {str(e)}")
        frappe.log_error(
            frappe.get_traceback(), f"Sales Order Submit Error - {doc.name}"
        )
        frappe.throw(f"Failed to start PO creation: {str(e)}")


def create_purchase_orders(docname):
    """
    Main function to create purchase orders based on Sales Order items
    Checks stock levels, reorder levels, and creates POs accordingly

    Args:
        docname: Name of the Sales Order document
    """
    print(f"\n{'='*80}")
    print(f"🚀 STARTING PURCHASE ORDER CREATION FOR: {docname}")
    print(f"{'='*80}")

    try:
        frappe.logger().info(f"=== Starting create_purchase_orders for {docname} ===")

        # Get the Sales Order document
        print(f"📋 Loading Sales Order document...")
        doc = frappe.get_doc("Sales Order", docname)
        print(f"✅ Sales Order loaded: {doc.name}, Status: {doc.status}")
        frappe.logger().info(f"Sales Order loaded: {doc.name}, Status: {doc.status}")

        # Step 1: Determine warehouse
        print(f"\n🏭 STEP 1: Determining warehouse...")
        warehouse = get_warehouse(doc)
        print(f"✅ Using warehouse: {warehouse}")
        frappe.logger().info(f"Using warehouse: {warehouse}")

        # Step 2: Calculate required items from SO and BOMs
        print(f"\n📊 STEP 2: Calculating required items...")
        required_items = calculate_required_items(doc)
        print(f"✅ Required items calculated: {len(required_items)} items")
        print(f"📦 Required items breakdown:")
        for item_code, qty in required_items.items():
            print(f"   - {item_code}: {qty}")
        frappe.logger().info(f"Required items calculated: {len(required_items)} items")
        frappe.logger().info(f"Required items: {json.dumps(required_items, indent=2)}")

        # Step 3: Determine what needs to be ordered
        print(f"\n🛒 STEP 3: Determining items to order...")
        to_order = determine_items_to_order(required_items, warehouse)
        print(f"✅ Items to order: {len(to_order)} items")
        print(f"📦 To order breakdown:")
        for item_code, data in to_order.items():
            print(
                f"   - {item_code}: {data['qty']} (stock: {data['current_stock']}, reorder: {data['reorder_level']})"
            )
        frappe.logger().info(f"Items to order: {len(to_order)} items")
        frappe.logger().info(
            f"To order details: {json.dumps({k: v['qty'] for k, v in to_order.items()}, indent=2)}"
        )

        # Step 4: Group items by best supplier
        print(f"\n👥 STEP 4: Grouping items by supplier...")
        supplier_items, no_supplier_items = group_items_by_supplier(to_order)
        print(f"✅ Suppliers found: {len(supplier_items)}")
        print(f"❌ Items without supplier: {len(no_supplier_items)}")

        if supplier_items:
            print(f"📋 Supplier breakdown:")
            for supplier, items in supplier_items.items():
                print(f"   - {supplier}: {len(items)} items")

        if no_supplier_items:
            print(f"⚠️  Items without supplier:")
            for item in no_supplier_items:
                print(f"   - {item}")

        frappe.logger().info(f"Suppliers found: {len(supplier_items)}")
        frappe.logger().info(f"Items without supplier: {len(no_supplier_items)}")

        # Step 5: Create Purchase Orders
        print(f"\n📝 STEP 5: Creating Purchase Orders...")
        created_pos = create_pos_for_suppliers(doc, supplier_items, warehouse)
        print(f"✅ Purchase Orders created: {len(created_pos)}")
        if created_pos:
            print(f"📄 Created POs: {', '.join(created_pos)}")
        frappe.logger().info(f"Purchase Orders created: {len(created_pos)}")

        # Step 6: Update Sales Order with items that couldn't be ordered
        print(f"\n📝 STEP 6: Updating Sales Order record...")
        update_sales_order_record(doc, no_supplier_items)
        print(f"✅ Sales Order updated with no-supplier items")

        frappe.db.commit()
        print(f"\n🎉 PURCHASE ORDER CREATION COMPLETED SUCCESSFULLY!")
        print(f"📊 Summary:")
        print(f"   - Sales Order: {docname}")
        print(f"   - POs Created: {len(created_pos)}")
        print(f"   - Items without supplier: {len(no_supplier_items)}")
        frappe.logger().info(f"=== Completed create_purchase_orders for {docname} ===")

        # Send notification
        frappe.publish_realtime(
            "po_creation_complete",
            {
                "sales_order": docname,
                "pos_created": len(created_pos),
                "items_without_supplier": len(no_supplier_items),
            },
            user=frappe.session.user,
        )

    except Exception as e:
        print(f"\n💥 CRITICAL ERROR in create_purchase_orders for {docname}: {str(e)}")
        frappe.logger().error(
            f"ERROR in create_purchase_orders for {docname}: {str(e)}"
        )
        frappe.log_error(frappe.get_traceback(), f"PO Creation Error - {docname}")
        frappe.db.rollback()
        raise


def get_warehouse(doc):
    """Determine which warehouse to use"""
    print(f"   🔍 Looking for warehouse...")
    print(f"   - Set warehouse: {doc.set_warehouse}")

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

    print(f"   ✅ Selected warehouse: {warehouse}")
    return warehouse


def calculate_required_items(doc):
    """Calculate all required items from SO items and their BOMs"""
    print(f"   📋 Processing {len(doc.items)} Sales Order items...")
    required_items = {}

    for so_item in doc.items:
        item_code = so_item.item_code
        qty = so_item.qty

        print(f"   🔍 Processing SO item: {item_code}, qty: {qty}")
        frappe.logger().info(f"Processing SO item: {item_code}, qty: {qty}")

        # Check if item has BOM
        bom_no = so_item.bom_no or frappe.db.get_value(
            "Item", item_code, "default_bom", cache=True
        )

        if not bom_no:
            # No BOM - order the item itself
            print(f"   📦 No BOM found for {item_code}, adding to required items")
            frappe.logger().info(
                f"  No BOM found for {item_code}, adding to required items"
            )
            required_items[item_code] = required_items.get(item_code, 0) + qty
        else:
            # Has BOM - explode and add components
            print(f"   🏗️  BOM found: {bom_no}, exploding...")
            frappe.logger().info(f"  BOM found: {bom_no}, exploding...")
            bom_items = get_bom_items_as_dict(
                bom_no, doc.company, qty=qty, fetch_exploded=True
            )
            print(f"   📊 BOM items found: {len(bom_items)}")
            frappe.logger().info(f"  BOM items found: {len(bom_items)}")

            for code, detail in bom_items.items():
                required_items[code] = required_items.get(code, 0) + detail["qty"]
                print(
                    f"     ➕ Added {code}: {detail['qty']} (total: {required_items[code]})"
                )
                frappe.logger().info(
                    f"    Added {code}: {detail['qty']} (total: {required_items[code]})"
                )

    return required_items


def determine_items_to_order(required_items, warehouse):
    """
    Check stock levels and reorder levels to determine what needs ordering
    """
    print(f"   🔍 Checking {len(required_items)} items for ordering...")
    to_order = {}

    for item_code, required_qty in required_items.items():
        print(f"   📦 Checking item: {item_code}, required: {required_qty}")
        frappe.logger().info(f"Checking item: {item_code}, required: {required_qty}")

        # Get item document
        item = frappe.get_doc("Item", item_code)

        # Skip non-purchase items
        if not item.is_purchase_item:
            print(f"   ⏭️  Skipping {item_code} - not a purchase item")
            frappe.logger().info(f"  Skipping {item_code} - not a purchase item")
            continue

        # Get reorder level and qty
        reorder_level = 0
        reorder_qty = 0
        min_order_qty = flt(item.min_order_qty) or 0
        print(f"   ⚙️  Min order qty: {min_order_qty}")

        for rl in item.get("reorder_levels", []):
            if rl.warehouse == warehouse:
                reorder_level = flt(rl.warehouse_reorder_level) or 0
                reorder_qty = flt(rl.warehouse_reorder_qty) or 0
                print(
                    f"   📊 Reorder level: {reorder_level}, Reorder qty: {reorder_qty}"
                )
                frappe.logger().info(
                    f"  Reorder level: {reorder_level}, Reorder qty: {reorder_qty}"
                )
                break

        # Get current stock
        stock = flt(
            frappe.db.get_value(
                "Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"
            )
            or 0
        )
        print(f"   📦 Current stock: {stock}")
        frappe.logger().info(f"  Current stock: {stock}")

        # Calculate order quantity
        order_qty = required_qty
        print(f"   📐 Base order qty: {order_qty}")

        # Add reorder qty if stock is below reorder level
        if stock < reorder_level:
            print(f"   ⚠️  Stock below reorder level! Adding reorder qty: {reorder_qty}")
            frappe.logger().info(
                f"  Stock below reorder level! Adding reorder qty: {reorder_qty}"
            )
            order_qty += reorder_qty

        # Ensure minimum order quantity
        if order_qty < min_order_qty:
            print(f"   📏 Adjusting to min order qty: {min_order_qty}")
            order_qty = min_order_qty

        print(f"   ✅ Final order qty: {order_qty}")
        frappe.logger().info(f"  Final order qty: {order_qty}")

        if order_qty > 0:
            to_order[item_code] = {
                "qty": order_qty,
                "item": item,
                "required_qty": required_qty,
                "current_stock": stock,
                "reorder_level": reorder_level,
            }

    return to_order


def group_items_by_supplier(to_order):
    """
    Group items by their best supplier based on purchase history
    """
    print(f"   🔍 Finding suppliers for {len(to_order)} items...")
    supplier_items = {}
    no_supplier_items = []

    for item_code, data in to_order.items():
        item = data["item"]

        print(f"   👥 Finding supplier for: {item_code}")
        frappe.logger().info(f"Finding supplier for: {item_code}")

        # Check if item has any suppliers configured
        if not item.get("supplier_items"):
            print(f"   ❌ No suppliers configured for {item_code}")
            frappe.logger().warning(f"  No suppliers configured for {item_code}")
            no_supplier_items.append(f"{item_code} (no supplier)")
            continue

        # Find best supplier from purchase history
        best_supplier, best_rate = find_best_supplier(item_code)

        if not best_supplier:
            print(f"   ❌ No purchase history found for {item_code}")
            frappe.logger().warning(f"  No purchase history found for {item_code}")
            no_supplier_items.append(f"{item_code} (no purchase history)")
            continue

        print(f"   ✅ Best supplier: {best_supplier}, rate: {best_rate}")
        frappe.logger().info(f"  Best supplier: {best_supplier}, rate: {best_rate}")

        # Group by supplier
        if best_supplier not in supplier_items:
            supplier_items[best_supplier] = []

        supplier_items[best_supplier].append(
            {
                "item_code": item_code,
                "qty": data["qty"],
                "rate": best_rate,
                "required_qty": data["required_qty"],
                "current_stock": data["current_stock"],
                "reorder_level": data["reorder_level"],
            }
        )

    return supplier_items, no_supplier_items


def find_best_supplier(item_code):
    """
    Find the best supplier for an item based on lowest rate in last 10 POs
    """
    print(f"     🔍 Searching purchase history for {item_code}...")

    # Try to find from last 10 purchase orders
    po_data = frappe.db.sql(
        """
        WITH last_10_records AS (
            SELECT 
                poi.rate, 
                po.supplier, 
                COALESCE(po.transaction_date, po.creation) AS tx_date
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
        LIMIT 1
        """,
        (item_code,),
        as_dict=True,
    )

    if po_data:
        print(
            f"     ✅ Found in last 10 POs: {po_data[0].supplier} @ {po_data[0].lowest_rate}"
        )
        frappe.logger().info(
            f"    Found in last 10 POs: {po_data[0].supplier} @ {po_data[0].lowest_rate}"
        )
        return po_data[0].supplier, flt(po_data[0].lowest_rate)

    # Fallback: search all purchase history
    print(f"     🔍 No recent POs found, searching all history...")
    fallback_data = frappe.db.sql(
        """
        SELECT po.supplier, MIN(poi.rate) AS min_rate
        FROM `tabPurchase Order Item` poi
        JOIN `tabPurchase Order` po ON poi.parent = po.name
        WHERE poi.item_code = %s AND po.docstatus = 1
        GROUP BY po.supplier
        ORDER BY min_rate ASC
        LIMIT 1
        """,
        (item_code,),
        as_dict=True,
    )

    if fallback_data:
        print(
            f"     ✅ Found in all history: {fallback_data[0].supplier} @ {fallback_data[0].min_rate}"
        )
        frappe.logger().info(
            f"    Found in all history: {fallback_data[0].supplier} @ {fallback_data[0].min_rate}"
        )
        return fallback_data[0].supplier, flt(fallback_data[0].min_rate)

    # === NEW FALLBACK LOGIC STARTS HERE ===
    print(f"     🔍 No purchase history found, checking Item Price...")

    # Look for item price
    item_price_data = frappe.db.sql(
        """
        SELECT supplier, price_list_rate
        FROM `tabItem Price`
        WHERE item_code = %s AND selling = 0 AND buying = 1
        ORDER BY price_list_rate ASC
        LIMIT 1
        """,
        (item_code,),
        as_dict=True,
    )

    if item_price_data:
        print(
            f"     ✅ Found in Item Price: {item_price_data[0].supplier} @ {item_price_data[0].price_list_rate}"
        )
        frappe.logger().info(
            f"    Found in Item Price: {item_price_data[0].supplier} @ {item_price_data[0].price_list_rate}"
        )
        return item_price_data[0].supplier, flt(item_price_data[0].price_list_rate)

    # Final fallback: use default value of 0
    print(f"     ⚠️  No price found anywhere, using default rate: 0")
    frappe.logger().warning(
        f"    No price found for {item_code}, using default rate: 0"
    )

    # Get any supplier from item's supplier list as fallback
    supplier_from_item = frappe.db.sql(
        """
        SELECT supplier 
        FROM `tabItem Supplier` 
        WHERE parent = %s 
        LIMIT 1
        """,
        (item_code,),
    )

    if supplier_from_item:
        supplier = supplier_from_item[0][0]
        print(f"     ✅ Using supplier from item master: {supplier}")
        return supplier, 0
    else:
        print(f"     ❌ No supplier found in item master either")
        return None, 0
    # === NEW FALLBACK LOGIC ENDS HERE ===


# def find_best_supplier(item_code):
#     """
#     Find the best supplier for an item based on lowest rate in last 10 POs
#     """
#     print(f"     🔍 Searching purchase history for {item_code}...")

#     # Try to find from last 10 purchase orders
#     po_data = frappe.db.sql(
#         """
#         WITH last_10_records AS (
#             SELECT
#                 poi.rate,
#                 po.supplier,
#                 COALESCE(po.transaction_date, po.creation) AS tx_date
#             FROM `tabPurchase Order Item` poi
#             JOIN `tabPurchase Order` po ON poi.parent = po.name
#             WHERE poi.item_code = %s AND po.docstatus = 1
#             ORDER BY tx_date DESC
#             LIMIT 10
#         )
#         SELECT
#             supplier,
#             MIN(rate) AS lowest_rate,
#             MAX(tx_date) AS latest_date
#         FROM last_10_records
#         GROUP BY supplier
#         ORDER BY lowest_rate ASC
#         LIMIT 1
#         """,
#         (item_code,),
#         as_dict=True,
#     )

#     if po_data:
#         print(
#             f"     ✅ Found in last 10 POs: {po_data[0].supplier} @ {po_data[0].lowest_rate}"
#         )
#         frappe.logger().info(
#             f"    Found in last 10 POs: {po_data[0].supplier} @ {po_data[0].lowest_rate}"
#         )
#         return po_data[0].supplier, flt(po_data[0].lowest_rate)

#     # Fallback: search all purchase history
#     print(f"     🔍 No recent POs found, searching all history...")
#     fallback_data = frappe.db.sql(
#         """
#         SELECT po.supplier, MIN(poi.rate) AS min_rate
#         FROM `tabPurchase Order Item` poi
#         JOIN `tabPurchase Order` po ON poi.parent = po.name
#         WHERE poi.item_code = %s AND po.docstatus = 1
#         GROUP BY po.supplier
#         ORDER BY min_rate ASC
#         LIMIT 1
#         """,
#         (item_code,),
#         as_dict=True,
#     )

#     if fallback_data:
#         print(
#             f"     ✅ Found in all history: {fallback_data[0].supplier} @ {fallback_data[0].min_rate}"
#         )
#         frappe.logger().info(
#             f"    Found in all history: {fallback_data[0].supplier} @ {fallback_data[0].min_rate}"
#         )
#         return fallback_data[0].supplier, flt(fallback_data[0].min_rate)

#     print(f"     ❌ No purchase history found")
#     return None, 0


def create_pos_for_suppliers(doc, supplier_items, warehouse):
    """
    Create Purchase Orders for each supplier
    """
    print(f"   📝 Creating POs for {len(supplier_items)} suppliers...")
    created_pos = []

    for supplier, items in supplier_items.items():
        try:
            print(f"   🛒 Creating PO for supplier: {supplier} with {len(items)} items")
            frappe.logger().info(
                f"Creating PO for supplier: {supplier} with {len(items)} items"
            )

            # Get supplier details
            supplier_doc = frappe.get_cached_doc("Supplier", supplier)
            required_days = cint(supplier_doc.get("custom_required_days") or 0)
            schedule_date = add_days(nowdate(), required_days)
            print(
                f"   📅 Schedule date: {schedule_date} (required days: {required_days})"
            )

            # Create PO
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

            # Add items
            print(f"   📦 Adding items to PO:")
            for it in items:
                print(f"     ➕ {it['item_code']}: {it['qty']} @ {it['rate']}")
                frappe.logger().info(
                    f"  Adding item: {it['item_code']}, qty: {it['qty']}, rate: {it['rate']}"
                )
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

            # Insert PO
            print(f"   💾 Inserting PO...")
            po.insert(ignore_permissions=True)
            print(f"   ✅ PO created: {po.name}")
            frappe.logger().info(f"  PO created: {po.name}")
            created_pos.append(po.name)

            # Auto-submit if configured
            if supplier_doc.custom_auto_submit_purchase_order:
                print(f"   📤 Auto-submitting PO...")
                po.submit()
                print(f"   ✅ PO submitted: {po.name}")
                frappe.logger().info(f"  PO submitted: {po.name}")
            else:
                print(f"   ⏸️  Auto-submit disabled for this supplier")

            # Send email if configured
            if supplier_doc.custom_auto_generate_mail:
                print(f"   📧 Sending email for PO...")
                send_po_email(po, supplier_doc)
                frappe.logger().info(f"  Email sent for PO: {po.name}")
            else:
                print(f"   ⏸️  Auto-email disabled for this supplier")

        except Exception as e:
            print(f"   ❌ Error creating PO for supplier {supplier}: {str(e)}")
            frappe.logger().error(
                f"Error creating PO for supplier {supplier}: {str(e)}"
            )
            frappe.log_error(frappe.get_traceback(), f"PO Creation Error - {supplier}")
            # Continue with other suppliers

    return created_pos


def update_sales_order_record(doc, no_supplier_items):
    """Update the Sales Order with items that couldn't be ordered"""
    try:
        print(f"   📝 Updating Sales Order record...")

        # Check if custom field exists
        if not frappe.db.exists(
            "Custom Field",
            {"dt": "Sales Order", "fieldname": "custom_purchase_order_record"},
        ):
            print(f"   ⚠️  Custom field 'custom_purchase_order_record' not found")
            frappe.logger().warning(
                "Custom field 'custom_purchase_order_record' not found in Sales Order"
            )
            # Log to Error Log for visibility
            if no_supplier_items:
                error_msg = f"Items without supplier for SO {doc.name}:\n" + "\n".join(
                    no_supplier_items
                )
                frappe.log_error(error_msg, "Items Without Supplier")
            return

        field_value = (
            ", ".join(sorted(set(no_supplier_items))) if no_supplier_items else ""
        )
        doc.db_set("custom_purchase_order_record", field_value, update_modified=False)

        if no_supplier_items:
            print(f"   ⚠️  Updated SO with no-supplier items: {field_value}")
        else:
            print(f"   ✅ No items without suppliers")

        frappe.logger().info(f"Updated SO with no-supplier items: {field_value}")
    except Exception as e:
        print(f"   ❌ Error updating sales order record: {str(e)}")
        frappe.logger().error(f"Error updating sales order record: {str(e)}")
        # Don't fail the entire process if this update fails
        if no_supplier_items:
            error_msg = f"Items without supplier for SO {doc.name}:\n" + "\n".join(
                no_supplier_items
            )
            frappe.log_error(error_msg, "Items Without Supplier")


def send_po_email(po, supplier_doc):
    """Send PO email using Email Template or fallback HTML"""
    try:
        print(f"     📧 Preparing to send email for PO: {po.name}")

        # Get email address
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
            error_msg = f"No email found for Supplier {supplier_doc.name}"
            print(f"     ❌ {error_msg}")
            frappe.logger().warning(error_msg)
            frappe.log_error(error_msg, "PO Email: No Email Found")
            return

        print(f"     📨 Sending to: {email}")

        subject = f"Purchase Order {po.name} from {po.company}"

        # Prepare attachments
        attachments = [
            {
                "doctype": "Purchase Order",
                "name": po.name,
                "print_format": "Purchase Order Chapparia",
                "print_format_attachment": 1,
            }
        ]

        # Try email template first
        template_name = "Purchase Order"

        if frappe.db.exists("Email Template", template_name):
            print(f"     📝 Using email template: {template_name}")
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
            print(f"     📝 Using fallback HTML template")
            # Fallback HTML
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

        print(f"     ✅ Email sent successfully to {email}")
        frappe.logger().info(f"  Email sent successfully to {email}")
        frappe.msgprint(
            f"Email sent successfully to {email} for PO {po.name}", indicator="green"
        )

    except Exception as e:
        error_msg = f"Failed to send PO email for {po.name}: {str(e)}"
        print(f"     ❌ {error_msg}")
        frappe.logger().error(error_msg)
        frappe.log_error(frappe.get_traceback(), "PO Email Send Failed")
        frappe.msgprint(error_msg, indicator="orange", title="Email Send Failed")


# # import frappe
# # from erpnext.manufacturing.doctype.bom.bom import get_bom_items_as_dict
# # from frappe.utils import cint, nowdate, flt, add_days
# # from frappe.email.doctype.email_template.email_template import get_email_template
# # import json


# # def on_submit(doc, method=None):
# #     """Hook called when Sales Order is submitted"""
# #     try:
# #         # Log the start
# #         frappe.logger().info(
# #             f"=== Sales Order {doc.name} submitted - Starting PO creation ==="
# #         )

# #         frappe.enqueue(
# #             create_purchase_orders,
# #             docname=doc.name,  # Pass docname instead of doc object
# #             queue="long",
# #             timeout=300,
# #             job_id=f"create_po_for_{doc.name}",  # Fixed: job_id instead of job_name
# #         )

# #         frappe.msgprint(
# #             f"Background job started for creating Purchase Orders for {doc.name}",
# #             indicator="blue",
# #         )
# #         frappe.logger().info(f"Background job enqueued for {doc.name}")

# #     except Exception as e:
# #         frappe.logger().error(f"Error enqueueing PO creation for {doc.name}: {str(e)}")
# #         frappe.log_error(
# #             frappe.get_traceback(), f"Sales Order Submit Error - {doc.name}"
# #         )
# #         frappe.throw(f"Failed to start PO creation: {str(e)}")


# # def create_purchase_orders(docname):
# #     """
# #     Main function to create purchase orders based on Sales Order items
# #     Checks stock levels, reorder levels, and creates POs accordingly

# #     Args:
# #         docname: Name of the Sales Order document
# #     """
# #     try:
# #         frappe.logger().info(f"=== Starting create_purchase_orders for {docname} ===")

# #         # Get the Sales Order document
# #         doc = frappe.get_doc("Sales Order", docname)
# #         frappe.logger().info(f"Sales Order loaded: {doc.name}, Status: {doc.status}")

# #         # Step 1: Determine warehouse
# #         warehouse = get_warehouse(doc)
# #         frappe.logger().info(f"Using warehouse: {warehouse}")

# #         # Step 2: Calculate required items from SO and BOMs
# #         required_items = calculate_required_items(doc)
# #         frappe.logger().info(f"Required items calculated: {len(required_items)} items")
# #         frappe.logger().info(f"Required items: {json.dumps(required_items, indent=2)}")

# #         # Step 3: Determine what needs to be ordered
# #         to_order = determine_items_to_order(required_items, warehouse)
# #         frappe.logger().info(f"Items to order: {len(to_order)} items")
# #         frappe.logger().info(
# #             f"To order details: {json.dumps({k: v['qty'] for k, v in to_order.items()}, indent=2)}"
# #         )

# #         # Step 4: Group items by best supplier
# #         supplier_items, no_supplier_items = group_items_by_supplier(to_order)
# #         frappe.logger().info(f"Suppliers found: {len(supplier_items)}")
# #         frappe.logger().info(f"Items without supplier: {len(no_supplier_items)}")

# #         # Step 5: Create Purchase Orders
# #         created_pos = create_pos_for_suppliers(doc, supplier_items, warehouse)
# #         frappe.logger().info(f"Purchase Orders created: {len(created_pos)}")

# #         # Step 6: Update Sales Order with items that couldn't be ordered
# #         update_sales_order_record(doc, no_supplier_items)

# #         frappe.db.commit()
# #         frappe.logger().info(f"=== Completed create_purchase_orders for {docname} ===")

# #         # Send notification
# #         frappe.publish_realtime(
# #             "po_creation_complete",
# #             {
# #                 "sales_order": docname,
# #                 "pos_created": len(created_pos),
# #                 "items_without_supplier": len(no_supplier_items),
# #             },
# #             user=frappe.session.user,
# #         )

# #     except Exception as e:
# #         frappe.logger().error(
# #             f"ERROR in create_purchase_orders for {docname}: {str(e)}"
# #         )
# #         frappe.log_error(frappe.get_traceback(), f"PO Creation Error - {docname}")
# #         frappe.db.rollback()
# #         raise


# # def get_warehouse(doc):
# #     """Determine which warehouse to use"""
# #     warehouse = (
# #         doc.set_warehouse
# #         or frappe.db.get_single_value("Stock Settings", "default_warehouse")
# #         or frappe.get_value(
# #             "Warehouse",
# #             {"is_group": 0, "disabled": 0, "company": doc.company},
# #             "name",
# #             order_by="creation",
# #         )
# #         or f"Stores - {doc.company}"
# #     )
# #     return warehouse


# # def calculate_required_items(doc):
# #     """Calculate all required items from SO items and their BOMs"""
# #     required_items = {}

# #     for so_item in doc.items:
# #         item_code = so_item.item_code
# #         qty = so_item.qty

# #         frappe.logger().info(f"Processing SO item: {item_code}, qty: {qty}")

# #         # Check if item has BOM
# #         bom_no = so_item.bom_no or frappe.db.get_value(
# #             "Item", item_code, "default_bom", cache=True
# #         )

# #         if not bom_no:
# #             # No BOM - order the item itself
# #             frappe.logger().info(
# #                 f"  No BOM found for {item_code}, adding to required items"
# #             )
# #             required_items[item_code] = required_items.get(item_code, 0) + qty
# #         else:
# #             # Has BOM - explode and add components
# #             frappe.logger().info(f"  BOM found: {bom_no}, exploding...")
# #             bom_items = get_bom_items_as_dict(
# #                 bom_no, doc.company, qty=qty, fetch_exploded=True
# #             )
# #             frappe.logger().info(f"  BOM items found: {len(bom_items)}")

# #             for code, detail in bom_items.items():
# #                 required_items[code] = required_items.get(code, 0) + detail["qty"]
# #                 frappe.logger().info(
# #                     f"    Added {code}: {detail['qty']} (total: {required_items[code]})"
# #                 )

# #     return required_items


# # def determine_items_to_order(required_items, warehouse):
# #     """
# #     Check stock levels and reorder levels to determine what needs ordering
# #     """
# #     to_order = {}

# #     for item_code, required_qty in required_items.items():
# #         frappe.logger().info(f"Checking item: {item_code}, required: {required_qty}")

# #         # Get item document
# #         item = frappe.get_doc("Item", item_code)

# #         # Skip non-purchase items
# #         if not item.is_purchase_item:
# #             frappe.logger().info(f"  Skipping {item_code} - not a purchase item")
# #             continue

# #         # Get reorder level and qty
# #         reorder_level = 0
# #         reorder_qty = 0
# #         min_order_qty = flt(item.min_order_qty) or 0

# #         for rl in item.get("reorder_levels", []):
# #             if rl.warehouse == warehouse:
# #                 reorder_level = flt(rl.warehouse_reorder_level) or 0
# #                 reorder_qty = flt(rl.warehouse_reorder_qty) or 0
# #                 frappe.logger().info(
# #                     f"  Reorder level: {reorder_level}, Reorder qty: {reorder_qty}"
# #                 )
# #                 break

# #         # Get current stock
# #         stock = flt(
# #             frappe.db.get_value(
# #                 "Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"
# #             )
# #             or 0
# #         )
# #         frappe.logger().info(f"  Current stock: {stock}")

# #         # Calculate order quantity
# #         order_qty = required_qty

# #         # Add reorder qty if stock is below reorder level
# #         if stock < reorder_level:
# #             frappe.logger().info(
# #                 f"  Stock below reorder level! Adding reorder qty: {reorder_qty}"
# #             )
# #             order_qty += reorder_qty

# #         # Ensure minimum order quantity
# #         order_qty = max(order_qty, min_order_qty)
# #         frappe.logger().info(f"  Final order qty: {order_qty}")

# #         if order_qty > 0:
# #             to_order[item_code] = {
# #                 "qty": order_qty,
# #                 "item": item,
# #                 "required_qty": required_qty,
# #                 "current_stock": stock,
# #                 "reorder_level": reorder_level,
# #             }

# #     return to_order


# # def group_items_by_supplier(to_order):
# #     """
# #     Group items by their best supplier based on purchase history
# #     """
# #     supplier_items = {}
# #     no_supplier_items = []

# #     for item_code, data in to_order.items():
# #         item = data["item"]

# #         frappe.logger().info(f"Finding supplier for: {item_code}")

# #         # Check if item has any suppliers configured
# #         if not item.get("supplier_items"):
# #             frappe.logger().warning(f"  No suppliers configured for {item_code}")
# #             no_supplier_items.append(f"{item_code} (no supplier)")
# #             continue

# #         # Find best supplier from purchase history
# #         best_supplier, best_rate = find_best_supplier(item_code)

# #         if not best_supplier:
# #             frappe.logger().warning(f"  No purchase history found for {item_code}")
# #             no_supplier_items.append(f"{item_code} (no purchase history)")
# #             continue

# #         frappe.logger().info(f"  Best supplier: {best_supplier}, rate: {best_rate}")

# #         # Group by supplier
# #         if best_supplier not in supplier_items:
# #             supplier_items[best_supplier] = []

# #         supplier_items[best_supplier].append(
# #             {
# #                 "item_code": item_code,
# #                 "qty": data["qty"],
# #                 "rate": best_rate,
# #                 "required_qty": data["required_qty"],
# #                 "current_stock": data["current_stock"],
# #                 "reorder_level": data["reorder_level"],
# #             }
# #         )

# #     return supplier_items, no_supplier_items


# # def find_best_supplier(item_code):
# #     """
# #     Find the best supplier for an item based on lowest rate in last 10 POs
# #     """
# #     # Try to find from last 10 purchase orders
# #     po_data = frappe.db.sql(
# #         """
# #         WITH last_10_records AS (
# #             SELECT
# #                 poi.rate,
# #                 po.supplier,
# #                 COALESCE(po.transaction_date, po.creation) AS tx_date
# #             FROM `tabPurchase Order Item` poi
# #             JOIN `tabPurchase Order` po ON poi.parent = po.name
# #             WHERE poi.item_code = %s AND po.docstatus = 1
# #             ORDER BY tx_date DESC
# #             LIMIT 10
# #         )
# #         SELECT
# #             supplier,
# #             MIN(rate) AS lowest_rate,
# #             MAX(tx_date) AS latest_date
# #         FROM last_10_records
# #         GROUP BY supplier
# #         ORDER BY lowest_rate ASC
# #         LIMIT 1
# #         """,
# #         (item_code,),
# #         as_dict=True,
# #     )

# #     if po_data:
# #         frappe.logger().info(
# #             f"    Found in last 10 POs: {po_data[0].supplier} @ {po_data[0].lowest_rate}"
# #         )
# #         return po_data[0].supplier, flt(po_data[0].lowest_rate)

# #     # Fallback: search all purchase history
# #     fallback_data = frappe.db.sql(
# #         """
# #         SELECT po.supplier, MIN(poi.rate) AS min_rate
# #         FROM `tabPurchase Order Item` poi
# #         JOIN `tabPurchase Order` po ON poi.parent = po.name
# #         WHERE poi.item_code = %s AND po.docstatus = 1
# #         GROUP BY po.supplier
# #         ORDER BY min_rate ASC
# #         LIMIT 1
# #         """,
# #         (item_code,),
# #         as_dict=True,
# #     )

# #     if fallback_data:
# #         frappe.logger().info(
# #             f"    Found in all history: {fallback_data[0].supplier} @ {fallback_data[0].min_rate}"
# #         )
# #         return fallback_data[0].supplier, flt(fallback_data[0].min_rate)

# #     return None, 0


# # def create_pos_for_suppliers(doc, supplier_items, warehouse):
# #     """
# #     Create Purchase Orders for each supplier
# #     """
# #     created_pos = []

# #     for supplier, items in supplier_items.items():
# #         try:
# #             frappe.logger().info(
# #                 f"Creating PO for supplier: {supplier} with {len(items)} items"
# #             )

# #             # Get supplier details
# #             supplier_doc = frappe.get_cached_doc("Supplier", supplier)
# #             required_days = cint(supplier_doc.get("custom_required_days") or 0)
# #             schedule_date = add_days(nowdate(), required_days)

# #             # Create PO
# #             po = frappe.get_doc(
# #                 {
# #                     "doctype": "Purchase Order",
# #                     "supplier": supplier,
# #                     "transaction_date": nowdate(),
# #                     "company": doc.company,
# #                     "schedule_date": schedule_date,
# #                     "set_warehouse": warehouse,
# #                     "items": [],
# #                     "sales_order": doc.name,
# #                 }
# #             )

# #             # Add items
# #             for it in items:
# #                 frappe.logger().info(
# #                     f"  Adding item: {it['item_code']}, qty: {it['qty']}, rate: {it['rate']}"
# #                 )
# #                 po.append(
# #                     "items",
# #                     {
# #                         "item_code": it["item_code"],
# #                         "qty": it["qty"],
# #                         "rate": it["rate"],
# #                         "schedule_date": schedule_date,
# #                         "warehouse": warehouse,
# #                         "sales_order": doc.name,
# #                     },
# #                 )

# #             # Insert PO
# #             po.insert(ignore_permissions=True)
# #             frappe.logger().info(f"  PO created: {po.name}")
# #             created_pos.append(po.name)

# #             # Auto-submit if configured
# #             if supplier_doc.custom_auto_submit_purchase_order:
# #                 po.submit()
# #                 frappe.logger().info(f"  PO submitted: {po.name}")

# #             # Send email if configured
# #             if supplier_doc.custom_auto_generate_mail:
# #                 send_po_email(po, supplier_doc)
# #                 frappe.logger().info(f"  Email sent for PO: {po.name}")

# #         except Exception as e:
# #             frappe.logger().error(
# #                 f"Error creating PO for supplier {supplier}: {str(e)}"
# #             )
# #             frappe.log_error(frappe.get_traceback(), f"PO Creation Error - {supplier}")
# #             # Continue with other suppliers

# #     return created_pos


# # def update_sales_order_record(doc, no_supplier_items):
# #     """Update the Sales Order with items that couldn't be ordered"""
# #     try:
# #         # Check if custom field exists
# #         if not frappe.db.exists(
# #             "Custom Field",
# #             {"dt": "Sales Order", "fieldname": "custom_purchase_order_record"},
# #         ):
# #             frappe.logger().warning(
# #                 "Custom field 'custom_purchase_order_record' not found in Sales Order"
# #             )
# #             # Log to Error Log for visibility
# #             if no_supplier_items:
# #                 error_msg = f"Items without supplier for SO {doc.name}:\n" + "\n".join(
# #                     no_supplier_items
# #                 )
# #                 frappe.log_error(error_msg, "Items Without Supplier")
# #             return

# #         field_value = (
# #             ", ".join(sorted(set(no_supplier_items))) if no_supplier_items else ""
# #         )
# #         doc.db_set("custom_purchase_order_record", field_value, update_modified=False)
# #         frappe.logger().info(f"Updated SO with no-supplier items: {field_value}")
# #     except Exception as e:
# #         frappe.logger().error(f"Error updating sales order record: {str(e)}")
# #         # Don't fail the entire process if this update fails
# #         if no_supplier_items:
# #             error_msg = f"Items without supplier for SO {doc.name}:\n" + "\n".join(
# #                 no_supplier_items
# #             )
# #             frappe.log_error(error_msg, "Items Without Supplier")


# # def send_po_email(po, supplier_doc):
# #     """Send PO email using Email Template or fallback HTML"""
# #     try:
# #         frappe.logger().info(f"Sending email for PO: {po.name}")

# #         # Get email address
# #         email = supplier_doc.email_id
# #         if not email:
# #             contacts = frappe.get_all(
# #                 "Contact Email",
# #                 {
# #                     "parenttype": "Supplier",
# #                     "parent": supplier_doc.name,
# #                     "email_id": ["!=", ""],
# #                 },
# #                 "email_id",
# #                 limit=1,
# #             )
# #             if contacts:
# #                 email = contacts[0].email_id

# #         if not email:
# #             error_msg = f"No email found for Supplier {supplier_doc.name}"
# #             frappe.logger().warning(error_msg)
# #             frappe.log_error(error_msg, "PO Email: No Email Found")
# #             return

# #         frappe.logger().info(f"  Sending to: {email}")

# #         subject = f"Purchase Order {po.name} from {po.company}"

# #         # Prepare attachments
# #         attachments = [
# #             {
# #                 "doctype": "Purchase Order",
# #                 "name": po.name,
# #                 "print_format": "Purchase Order Chapparia",
# #                 "print_format_attachment": 1,
# #             }
# #         ]

# #         # Try email template first
# #         template_name = "Purchase Order"

# #         if frappe.db.exists("Email Template", template_name):
# #             rendered = get_email_template(template_name, po.as_dict())
# #             frappe.sendmail(
# #                 recipients=email,
# #                 subject=rendered.get("subject"),
# #                 message=rendered.get("message"),
# #                 attachments=attachments,
# #                 reference_doctype="Purchase Order",
# #                 reference_name=po.name,
# #                 now=True,
# #                 retry=3,
# #                 add_unsubscribe_link=False,
# #             )
# #         else:
# #             # Fallback HTML
# #             items_html = ""
# #             for item in po.items:
# #                 items_html += f"""
# #                 <tr>
# #                     <td>{item.item_code}</td>
# #                     <td>{item.item_name or ''}</td>
# #                     <td>{item.qty}</td>
# #                 </tr>
# #                 """

# #             message = f"""
# #             <p>Dear {supplier_doc.supplier_name},</p>
# #             <p>Please find attached Purchase Order <strong>{po.name}</strong>.</p>
# #             <h3>Items:</h3>
# #             <table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; width: 100%;">
# #                 <tr style="background-color: #f0f0f0;">
# #                     <th>Item</th><th>Description</th><th>Qty</th>
# #                 </tr>
# #                 {items_html}
# #             </table>
# #             <p>Kindly deliver the above items <strong>by {po.schedule_date}</strong></p>
# #             <p>View: <a href="{frappe.utils.get_url(po.get_url())}">Online Link</a></p>
# #             <p>Thank you,<br>{po.company}</p>
# #             """

# #             frappe.sendmail(
# #                 recipients=[email],
# #                 subject=subject,
# #                 message=message,
# #                 attachments=attachments,
# #                 reference_doctype="Purchase Order",
# #                 reference_name=po.name,
# #                 now=True,
# #                 retry=3,
# #                 add_unsubscribe_link=False,
# #             )

# #         frappe.logger().info(f"  Email sent successfully to {email}")
# #         frappe.msgprint(
# #             f"Email sent successfully to {email} for PO {po.name}", indicator="green"
# #         )

# #     except Exception as e:
# #         error_msg = f"Failed to send PO email for {po.name}: {str(e)}"
# #         frappe.logger().error(error_msg)
# #         frappe.log_error(frappe.get_traceback(), "PO Email Send Failed")
# #         frappe.msgprint(error_msg, indicator="orange", title="Email Send Failed")


# # -=========================================================================
# # -=========================================================================


# import frappe
# from erpnext.manufacturing.doctype.bom.bom import get_bom_items_as_dict
# from frappe.utils import cint, nowdate, flt, add_days
# from frappe.email.doctype.email_template.email_template import get_email_template


# def on_submit(doc, method=None):
#     frappe.enqueue(
#         create_purchase_orders,
#         doc=doc,
#         queue="long",
#         timeout=300,
#         job_name=f"Create PO for Sales Order {doc.name}",
#     )
#     frappe.msgprint(
#         f"Background job started for creating Purchase Orders for {doc.name}"
#     )


# def create_purchase_orders(doc):
#     warehouse = (
#         doc.set_warehouse
#         or frappe.db.get_single_value("Stock Settings", "default_warehouse")
#         or frappe.get_value(
#             "Warehouse",
#             {"is_group": 0, "disabled": 0, "company": doc.company},
#             "name",
#             order_by="creation",
#         )
#         or f"Stores - {doc.company}"
#     )

#     required_items = {}
#     for so_item in doc.items:
#         item_code = so_item.item_code
#         qty = so_item.qty
#         bom_no = so_item.bom_no or frappe.db.get_value(
#             "Item", item_code, "default_bom", cache=True
#         )
#         if not bom_no:
#             required_items[item_code] = required_items.get(item_code, 0) + qty
#         else:
#             bom_items = get_bom_items_as_dict(
#                 bom_no, doc.company, qty=qty, fetch_exploded=True
#             )
#             for code, detail in bom_items.items():
#                 required_items[code] = required_items.get(code, 0) + detail["qty"]

#     to_order = {}
#     for item_code, required_qty in required_items.items():
#         item = frappe.get_doc("Item", item_code)
#         if not item.is_purchase_item:
#             continue

#         reorder_level = 0
#         reorder_qty = 0
#         min_order_qty = flt(item.min_order_qty) or 0
#         for rl in item.get("reorder_levels", []):
#             if rl.warehouse == warehouse:
#                 reorder_level = flt(rl.warehouse_reorder_level) or 0
#                 reorder_qty = rl.warehouse_reorder_qty or 0
#                 break

#         stock = flt(
#             frappe.db.get_value(
#                 "Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"
#             )
#             or 0
#         )

#         order_qty = required_qty
#         if stock < reorder_level:
#             # order_qty += (reorder_level - stock) + reorder_qty
#             order_qty += reorder_qty
#         order_qty = max(order_qty, min_order_qty)

#         if order_qty > 0:
#             to_order[item_code] = {
#                 "qty": order_qty,
#                 "item": item,
#                 "required_qty": required_qty,
#             }

#     supplier_items = {}
#     no_supplier_items = []

#     for item_code, data in to_order.items():
#         item = data["item"]
#         if not item.get("supplier_items"):
#             no_supplier_items.append(f"{item_code} (no supplier)")
#             continue

#         po_data = frappe.db.sql(
#             """
#             WITH last_10_records AS (
#                 SELECT poi.rate, po.supplier, COALESCE(po.transaction_date, po.creation) AS tx_date
#                 FROM `tabPurchase Order Item` poi
#                 JOIN `tabPurchase Order` po ON poi.parent = po.name
#                 WHERE poi.item_code = %s AND po.docstatus = 1
#                 ORDER BY tx_date DESC
#                 LIMIT 10
#             )
#             SELECT
#                 supplier,
#                 MIN(rate) AS lowest_rate,
#                 MAX(tx_date) AS latest_date
#             FROM last_10_records
#             GROUP BY supplier
#             ORDER BY lowest_rate ASC
#             LIMIT 1;
#             """,
#             (item_code,),
#             as_dict=True,
#         )

#         if po_data:
#             best_supplier = po_data[0].supplier
#             best_rate = flt(po_data[0].lowest_rate)
#             best_date = po_data[0].latest_date
#         else:
#             fallback_data = frappe.db.sql(
#                 """
#                 SELECT po.supplier, MIN(poi.rate) AS min_rate
#                 FROM `tabPurchase Order Item` poi
#                 JOIN `tabPurchase Order` po ON poi.parent = po.name
#                 WHERE poi.item_code = %s AND po.docstatus = 1
#                 GROUP BY po.supplier
#                 ORDER BY min_rate ASC
#                 LIMIT 1;
#                 """,
#                 (item_code,),
#                 as_dict=True,
#             )
#             if fallback_data:
#                 best_supplier = fallback_data[0].supplier
#                 best_rate = flt(fallback_data[0].min_rate)
#                 best_date = nowdate()
#             else:
#                 no_supplier_items.append(f"{item_code} (no purchase history)")
#                 continue

#         # Group items by this best supplier
#         if best_supplier not in supplier_items:
#             supplier_items[best_supplier] = []
#         supplier_items[best_supplier].append(
#             {
#                 "item_code": item_code,
#                 "qty": data["qty"],
#                 "rate": best_rate,
#             }
#         )

#     for supplier, items in supplier_items.items():
#         supplier_doc = frappe.get_cached_doc("Supplier", supplier)
#         required_days = cint(supplier_doc.get("custom_required_days") or 0)

#         schedule_date = add_days(nowdate(), required_days)
#         po = frappe.get_doc(
#             {
#                 "doctype": "Purchase Order",
#                 "supplier": supplier,
#                 "transaction_date": nowdate(),
#                 "company": doc.company,
#                 "schedule_date": schedule_date,
#                 "set_warehouse": warehouse,
#                 "items": [],
#                 "sales_order": doc.name,
#             }
#         )
#         for it in items:
#             po.append(
#                 "items",
#                 {
#                     "item_code": it["item_code"],
#                     "qty": it["qty"],
#                     "rate": it["rate"],
#                     "schedule_date": schedule_date,
#                     "warehouse": warehouse,
#                     "sales_order": doc.name,
#                 },
#             )
#         po.insert(ignore_permissions=True)

#         if supplier_doc.custom_auto_submit_purchase_order:
#             po.submit()

#         if supplier_doc.custom_auto_generate_mail:
#             send_po_email(po, supplier_doc)
#     frappe.db.commit()

#     field_value = ", ".join(sorted(set(no_supplier_items))) if no_supplier_items else ""
#     doc.db_set("custom_purchase_order_record", field_value, update_modified=False)


# def send_po_email(po, supplier_doc):
#     """Send PO email using Email Template or fallback HTML. Better email lookup."""
#     try:
#         email = supplier_doc.email_id
#         if not email:
#             contacts = frappe.get_all(
#                 "Contact Email",
#                 {
#                     "parenttype": "Supplier",
#                     "parent": supplier_doc.name,
#                     "email_id": ["!=", ""],
#                 },
#                 "email_id",
#                 limit=1,
#             )
#             if contacts:
#                 email = contacts[0].email_id

#         if not email:
#             error_msg = f"No email found for Supplier {supplier_doc.name}. Set 'email_id' on Supplier or link a Contact with email."
#             frappe.log_error(error_msg, "PO Email: No Email Found")
#             frappe.throw(error_msg, title="Email Not Found")

#         subject = f"Purchase Order {po.name} from {po.company}"

#         attachments = [
#             {
#                 "doctype": "Purchase Order",
#                 "name": po.name,
#                 "print_format": "Purchase Order Chapparia",
#                 "print_format_attachment": 1,
#             }
#         ]

#         template_name = "Purchase Order"

#         if frappe.db.exists("Email Template", template_name):
#             rendered = get_email_template(template_name, po.as_dict())
#             frappe.sendmail(
#                 recipients=email,
#                 subject=rendered.get("subject"),
#                 message=rendered.get("message"),
#                 attachments=attachments,
#                 reference_doctype="Purchase Order",
#                 reference_name=po.name,
#                 now=True,
#                 retry=3,
#                 add_unsubscribe_link=False,
#             )
#         else:
#             items_html = ""
#             for item in po.items:
#                 items_html += f"""
#                 <tr>
#                     <td>{item.item_code}</td>
#                     <td>{item.item_name or ''}</td>
#                     <td>{item.qty}</td>
#                 </tr>
#                 """

#             message = f"""
#             <p>Dear {supplier_doc.supplier_name},</p>
#             <p>Please find attached Purchase Order <strong>{po.name}</strong>.</p>
#             <h3>Items:</h3>
#             <table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; width: 100%;">
#                 <tr style="background-color: #f0f0f0;">
#                     <th>Item</th><th>Description</th><th>Qty</th>
#                 </tr>
#                 {items_html}
#             </table>
#             <p>Kindly deliver the above items <strong>by {po.schedule_date}</strong></p>
#             <p>View: <a href="{frappe.utils.get_url(po.get_url())}">Online Link</a></p>
#             <p>Thank you,<br>{po.company}</p>
#             """

#             frappe.sendmail(
#                 recipients=[email],
#                 subject=subject,
#                 message=message,
#                 attachments=attachments,
#                 reference_doctype="Purchase Order",
#                 reference_name=po.name,
#                 now=True,
#                 retry=3,
#                 add_unsubscribe_link=False,
#             )

#         frappe.msgprint(
#             f"Email sent successfully to {email} for PO {po.name}", indicator="green"
#         )

#     except frappe.ValidationError as ve:
#         frappe.throw(ve)
#     except Exception as e:
#         error_msg = (
#             f"Failed to send PO email for {po.name} to {email or 'unknown'}: {str(e)}"
#         )
#         frappe.log_error(error_msg, "PO Email Send Failed")
#         frappe.msgprint(error_msg, indicator="red", title="Email Send Failed")
