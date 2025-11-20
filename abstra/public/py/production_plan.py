from erpnext.manufacturing.doctype.production_plan.production_plan import ProductionPlan
import frappe
from frappe.utils.data import flt

class ProductionPlanOverride(ProductionPlan):
	def add_so_in_table(self, open_so):
		self.set("sales_orders", [])
		for data in open_so:
			self.append(
				"sales_orders",
				{
					"sales_order": data.name,
					"sales_order_date": data.transaction_date,
					"customer": data.customer,
					"grand_total": data.base_grand_total,
					"custom_project_master": frappe.db.get_value(
                        "Sales Order", data.name, "custom_project_master"
                    ) or "",
					"custom_project_master_quantity": frappe.db.get_value(
                        "Sales Order", data.name, "custom_project_qty"
                    ) or 0,
				},
			)

	@frappe.whitelist()
	def remove_add_sfa_raw_material(self):

		mr_items = self.get("mr_items") or []
		po_items = self.get("po_items") or []
		sub_assembly_items = []
		remaining_mr_items = []

		sales_order = self.custom_sales_order
		linked_po_items_map = {}

		if sales_order:
			po_item_rows = frappe.get_all(
				"Purchase Order Item",
				filters={"sales_order": sales_order,"docstatus": 1}, 
				fields=["item_code", "qty", "parent"]
			)

			for poi in po_item_rows:
				linked_po_items_map[poi.item_code] = (
					linked_po_items_map.get(poi.item_code, 0) + flt(poi.qty)
				)

		for po_item in po_items:
			bom_doc = get_bom_details(po_item.bom_no)
			if not bom_doc:
				continue

			for rmrow in mr_items:
				matched_items = [
					x for x in bom_doc.items
					if x.item_code == rmrow.item_code and is_valid_sfa_item(x.custom_msf)
				]

				ordered_qty = linked_po_items_map.get(rmrow.item_code, 0)
				rmrow.ordered_qty = ordered_qty
				rmrow.quantity = max((rmrow.quantity - ordered_qty),0)

				if matched_items:
					sub_assembly_items.append({
						"production_item": rmrow.item_code,
						"item_name": rmrow.item_name,
						"qty": flt(rmrow.required_bom_qty),
						"type_of_manufacturing": "In House",
						"parent_item_code": matched_items[0].fg_item,
						"schedule_date": self.posting_date
					})
				else:
					clean_row = rmrow.as_dict()
					for key in ("name", "idx", "parent", "parentfield", "parenttype"):
						clean_row.pop(key, None)
					clean_row["ordered_qty"] = ordered_qty
					remaining_mr_items.append(clean_row)

		self.set("mr_items", [])
		for rm in remaining_mr_items:
			self.append("mr_items", rm)

		self.extend("sub_assembly_items", sub_assembly_items)

		frappe.msgprint("Sub Assembly Items and MR Items updated successfully.")

	@frappe.whitelist()
	def fetch_from_project_master(self):
		if not self.custom_project_master:
			frappe.throw("Please select a Project Master first.")

		project_doc = frappe.get_doc("Project Master", self.custom_project_master)
		self.for_warehouse = project_doc.for_warehouse
	
		table_mapping = {
			"po_items": "po_items",
			"sub_assembly_items": "sub_assembly_items",
			"mr_items": "mr_items",
			"nesting_item_details": "custom__nesting_item_details",
			"nesting_header": "custom__nesting_header",
			"nesting_items": "custom__nesting_items",
		}

		system_fields = {"name", "parent", "parentfield", "parenttype", "doctype", "idx", "owner", "creation", "modified", "modified_by"}
		nesting_qty_map = {}
		for source_table, target_table in table_mapping.items():
			child_table = getattr(self, target_table, None)
			if child_table is not None:
				child_table[:] = []  

			for row in project_doc.get(source_table) or []:
				clean_row = {
					key: value for key, value in row.as_dict().items()
						if key not in system_fields
					}
				if target_table == "custom__nesting_header":
					total_nesting_qty = (row.nesting_qty or 0) * (self.custom_project_qty or 1)
					clean_row["total_nesting_qty"] = total_nesting_qty
					clean_row["net_sheet_weight"] = (row.sheet_weight or 0) * total_nesting_qty
					clean_row["net_sub_assembly_weight"] = (row.sub_assembly_weight or 0) * total_nesting_qty
					clean_row["net_scrap_weight"] = (row.scrap_weight or 0) * total_nesting_qty

					if row.nesting_no:
						nesting_qty_map[row.nesting_no] = total_nesting_qty

				self.append(target_table, clean_row)
		
		for po in self.po_items:
			po.custom_project_planned_qty = flt(po.planned_qty or 0)
			po.planned_qty = flt(po.planned_qty or 0) * self.custom_project_qty

		for row in self.custom__nesting_items:
			if row.nesting_no and row.nesting_no in nesting_qty_map:
				total_qty = nesting_qty_map[row.nesting_no]
				row.net_qty = (row.qty or 0) * total_qty
				row.net_weight = (row.net_qty or 0) * (row.weight or 0)

		if self.custom__nesting_header:
			total_net_sheet_weight = 0
			total_net_sub_assembly_weight = 0
			total_net_scrap_weight = 0
			total_scrap_percentage = 0
			total_weight_of_sheet = 0
			max_scrap = 0
			max_scrap_nesting_no = ''

			for row in self.custom__nesting_header:
				total_net_sheet_weight += row.net_sheet_weight or 0
				total_weight_of_sheet += row.sheet_weight or 0
				total_net_sub_assembly_weight += row.net_sub_assembly_weight or 0
				total_net_scrap_weight += row.net_scrap_weight or 0
				total_scrap_percentage += row.scrap_percentage or 0

				if (row.scrap_percentage or 0) > max_scrap:
					max_scrap = row.scrap_percentage
					max_scrap_nesting_no = row.nesting_no or '(no nesting)'

			avg_scrap_percentage = (total_scrap_percentage / len(self.custom__nesting_header)) if self.custom__nesting_header else 0

			self.custom_total_sheet_weight = round(total_net_sheet_weight, 3)
			self.custom_total_weight_of_sheet = round(total_weight_of_sheet, 3)
			self.custom_total_utilized_weight = round(total_net_sub_assembly_weight, 3)
			self.custom_total_scrap_weight = round(total_net_scrap_weight, 3)
			self.custom_scrap_percentage_average = round(avg_scrap_percentage, 3)
			self.custom_highest_scrap_nesting_code = max_scrap_nesting_no


	@frappe.whitelist()
	def fetch_selected_project_master(self):
		"""Fetch project master details based on selected project in Production Plan"""
		if not self.custom_selected_project:
			frappe.throw("Please select a Project from the table first.")

		# Find the selected row from child table
		selected_row = None
		for row in self.get("custom_project_master_of_sales_order") or []:
			if str(row.idx) == str(self.custom_selected_project):
				selected_row = row
				break

		if not selected_row:
			frappe.throw("Selected Project row not found in Project Master of Sales Order table.")

		if not selected_row.project_master:
			frappe.throw("Selected row does not have a valid Project Master linked.")

		project_master = selected_row.project_master
		project_qty = selected_row.project_qty or 1

		project_doc = frappe.get_doc("Project Master", project_master)
		self.set("for_warehouse", project_doc.for_warehouse)

		table_mapping = {
			"po_items": "po_items",
			"sub_assembly_items": "sub_assembly_items",
			"mr_items": "mr_items",
			"nesting_item_details": "custom__nesting_item_details",
			"nesting_header": "custom__nesting_header",
			"nesting_items": "custom__nesting_items",
		}

		system_fields = {"name", "parent", "parentfield", "parenttype", "doctype", "idx", "owner", "creation", "modified", "modified_by"}
		nesting_qty_map = {}

		for source_table, target_table in table_mapping.items():
			child_table = getattr(self, target_table, None)
			if child_table is not None:
				child_table[:] = []  # clear table

			for row in project_doc.get(source_table) or []:
				clean_row = {
					key: value for key, value in row.as_dict().items()
					if key not in system_fields
				}

				# For nesting header calculations
				if target_table == "custom__nesting_header":
					total_nesting_qty = (row.nesting_qty or 0) * project_qty
					clean_row["total_nesting_qty"] = total_nesting_qty
					clean_row["net_sheet_weight"] = (row.sheet_weight or 0) * total_nesting_qty
					clean_row["net_sub_assembly_weight"] = (row.sub_assembly_weight or 0) * total_nesting_qty
					clean_row["net_scrap_weight"] = (row.scrap_weight or 0) * total_nesting_qty

					if row.nesting_no:
						nesting_qty_map[row.nesting_no] = total_nesting_qty

				self.append(target_table, clean_row)
		
		for po in self.po_items:
			po.custom_project_planned_qty = flt(po.planned_qty or 0)
			po.planned_qty = flt(po.planned_qty or 0) * self.custom_project_qty
			
		for row in self.custom__nesting_items:
			if row.nesting_no and row.nesting_no in nesting_qty_map:
				total_qty = nesting_qty_map[row.nesting_no]
				row.net_qty = (row.qty or 0) * total_qty
				row.net_weight = (row.net_qty or 0) * (row.weight or 0)

		if self.custom__nesting_header:
			total_net_sheet_weight = 0
			total_net_sub_assembly_weight = 0
			total_net_scrap_weight = 0
			total_scrap_percentage = 0
			max_scrap = 0
			max_scrap_nesting_no = ''
			total_weight_of_sheet = 0

			for row in self.custom__nesting_header:
				total_net_sheet_weight += row.net_sheet_weight or 0
				total_weight_of_sheet += row.sheet_weight or 0
				total_net_sub_assembly_weight += row.net_sub_assembly_weight or 0
				total_net_scrap_weight += row.net_scrap_weight or 0
				total_scrap_percentage += row.scrap_percentage or 0

				if (row.scrap_percentage or 0) > max_scrap:
					max_scrap = row.scrap_percentage
					max_scrap_nesting_no = row.nesting_no or '(no nesting)'

			avg_scrap_percentage = (total_scrap_percentage / len(self.custom__nesting_header)) if self.custom__nesting_header else 0

			self.custom_total_sheet_weight = round(total_net_sheet_weight, 3)
			self.custom_total_weight_of_sheet = round(total_weight_of_sheet, 3)
			self.custom_total_utilized_weight = round(total_net_sub_assembly_weight, 3)
			self.custom_total_scrap_weight = round(total_net_scrap_weight, 3)
			self.custom_scrap_percentage_average = round(avg_scrap_percentage, 3)
			self.custom_highest_scrap_nesting_code = max_scrap_nesting_no

		frappe.msgprint(f"Project Master data fetched for: {project_master} (Qty: {project_qty})")

	@frappe.whitelist()
	def fetch_project_from_sales_order(self):
		if not self.custom_sales_order:
			frappe.throw("Please select a Sales Order first.")

		so = frappe.get_doc("Sales Order", self.custom_sales_order)

		self.set("custom_project_master_of_sales_order", [])

		for row in so.get("custom_project_master") or []:
			self.append("custom_project_master_of_sales_order", {
				"project_master": row.project_master,
				"project_qty": row.pending_qty,
				"pending_qty": row.pending_qty,
				"status": get_status(row.project_qty, row.pending_qty),
				"project_master_ref_sales_order": row.name
			})

def get_status(project_qty, pending_qty):
	if flt(pending_qty) <= 0:
		return "Completed"
	elif flt(pending_qty) < flt(project_qty):
		return "Partially Completed	"
	else:
		return "Pending"
	
def get_bom_details(bom_item_code):
    bom_creator_name = frappe.db.get_value("BOM", bom_item_code, "bom_creator")
    if not bom_creator_name:
        return None

    try:
        return frappe.get_doc("BOM Creator", bom_creator_name)
    except frappe.DoesNotExistError:
        return None

def is_valid_sfa_item(operation_list):

    if not operation_list:
        return False

    cache = frappe.cache()
    valid_ops = cache.get_value("valid_sfa_operations")

    if not valid_ops:
        valid_ops = frappe.get_all(
            "Operation",
            filters={"custom_is_valid_for_sfa_item": 1},
            pluck="name"
        )
        valid_ops = set(valid_ops)
        cache.set_value("valid_sfa_operations", list(valid_ops))

    ops = [op.strip() for op in operation_list.split(",") if op.strip()]
    if not ops:
        return False

    return any(op in valid_ops for op in ops)

def clean_row_for_append(row):
    keys_to_remove = ["name", "idx", "parent", "parentfield", "parenttype", "doctype", "modified", "creation", "owner", "modified_by"]
    return {k: v for k, v in row.items() if k not in keys_to_remove}