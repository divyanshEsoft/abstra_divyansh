frappe.ui.form.on('Production Plan', {
    onload: function (frm) {
        frm.set_query("custom_sales_order", () => {
            return {
                filters: {
                    docstatus: 1,
                }
            };
        });
    },
    refresh: function (frm) {
        if (frm.doc.custom_sales_order || frm.doc.custom_project_master) {

            const tables = [
                "po_items",
                "sub_assembly_items",
                "mr_items",
                "custom__nesting_item_details",
                "custom__nesting_header",
                "custom__nesting_items"
            ];

            tables.forEach(tbl => {

                const grid = frm.fields_dict[tbl]?.grid;
                if (!grid) return;

                grid.cannot_add_rows = true;
                grid.cannot_delete_rows = true;
                grid.df.read_only = 1;

                grid.wrapper.find(".grid-add-row, .grid-remove-rows").hide();
                grid.only_sortable();

                frm.refresh_field(tbl);
            });
        }
        add_select_project_button_and_handlers(frm)
    },

    get_items_for_mr: async function (frm) {
        frm.dirty();
        frappe.call({
            method: "remove_add_sfa_raw_material",
            freeze: true,
            doc: frm.doc,
        }).then((r) => {
            frm.refresh_field("mr_items");
            frm.refresh_field("sub_assembly_items");
        });

    },

    custom_project_master: function (frm) {
        if (frm.doc.custom_project_master) {
            frappe.call({
                method: "fetch_from_project_master",
                doc: frm.doc,
                freeze: true,
                callback: function (r) {
                    if (!r.exc) {
                        const tables = [
                            "po_items",
                            "sub_assembly_items",
                            "mr_items",
                            "custom__nesting_item_details",
                            "custom__nesting_header",
                            "custom__nesting_items"
                        ];

                        tables.forEach(tbl => {
                            frm.refresh_field(tbl);
                            const grid = frm.fields_dict[tbl].grid;
                            grid.cannot_add_rows = true;
                            grid.cannot_delete_rows = true;
                            grid.df.read_only = 1
                            grid.wrapper.find('.grid-add-row, .grid-remove-rows').hide();
                            grid.only_sortable();
                        });
                        frm.refresh_fields()
                    }
                }
            });
        }

    },

    custom_project_qty: function (frm) {
        if (!frm.doc.custom_project_qty || frm.doc.custom_project_qty <= 0) {
            frappe.msgprint({
                title: __("Invalid Quantity"),
                message: __("Project Quantity must be greater than 0."),
                indicator: "red",
            });
            frm.set_value("custom_project_qty", 1);
            return;
        }

        const project_qty = frm.doc.custom_project_qty || 1;
        update_po_table_quantities(frm, project_qty);
        update_nesting_and_items(frm, project_qty);
        update_nesting_totals(frm);

        frappe.show_alert({
            message: __("Nesting data & totals updated for Project Quantity"),
            indicator: "green",
        });

    },

    custom_sales_order: function (frm) {
        if (!frm.doc.custom_sales_order) return;

        frm.clear_table("custom_project_master_of_sales_order");

        frappe.call({
            method: "fetch_project_from_sales_order",
            doc: frm.doc,
            freeze: true,
            freeze_message: __("Fetching Project Master data..."),
            callback: function (r) {
                frm.refresh_field("custom_project_master_of_sales_order");
                frappe.show_alert({
                    message: __("Fetched Project Master table from Sales Order."),
                    indicator: "green"
                });
            }
        });

    },

    custom_get_from_project_master: function (frm) {
        const fields_to_clear = [
            "po_items",
            "custom_project_master",
            "custom_sales_order",
            "custom_selected_project",
            "custom_project_master_of_sales_order",
            "sub_assembly_items",
            "mr_items",
            "custom__nesting_item_details",
            "custom__nesting_header",
            "custom__nesting_items"
        ];

        // Check if any field has data
        const has_data = fields_to_clear.some(fieldname => {
            const value = frm.doc[fieldname];
            // For child tables: check if they have rows
            if (Array.isArray(value) && value.length > 0) return true;
            // For link or data fields: check if not empty
            if (value && typeof value === "string" && value.trim() !== "") return true;
            return false;
        });

        // Handle field read-only toggle
        if (frm.doc.custom_get_from_project_master) {
            frm.set_value("get_items_from", "");
            frm.set_df_property("get_items_from", "read_only", 1);
        } else {
            frm.set_df_property("get_items_from", "read_only", 0);
        }

        // Only prompt confirmation if any of those fields have data
        if (has_data) {
            confirmation_dialog_clear_data(frm);
        }
    }


})

frappe.ui.form.on('Production Plan Project Master', {
    project_qty: function (frm, cdt, cdn) {
        if (!frm.doc.custom_selected_project) {
            frappe.msgprint({
                title: __("No Project Selected"),
                message: __("Please select a Project Master row first using the 'Select Project' button."),
                indicator: "red"
            });
            return;
        };
        validate_project_qty_not_exceed_pending(frm, cdt, cdn);

        const row = locals[cdt][cdn];
        if (!row) return;

        const project_qty = row.project_qty || 1;

        update_po_table_quantities(frm, project_qty);
        update_nesting_and_items(frm, project_qty);
        update_nesting_totals(frm);

        frappe.show_alert({
            message: __("Updated nesting data and totals for selected project."),
            indicator: "green",
        });
    }
});

function validate_project_qty_not_exceed_pending(frm, cdt, cdn) {
    const row = locals[cdt][cdn];

    if (!row) return;

    if (row.status === "Completed") {
        frappe.msgprint({
            title: __("Production Plan Completed"),
            message: __("This project is already marked as Completed in Sales Order Project Master."),
            indicator: "green"
        });

        row.project_qty = 0;
        frm.refresh_field("custom_project_master_of_sales_order");
        return;
    }

    if ((row.project_qty || 0) > (row.pending_qty || 0)) {
        frappe.model.set_value(cdt, cdn, "project_qty", row.pending_qty);
        frappe.throw(
            `Project Qty (${row.project_qty}) cannot exceed Pending Qty (${row.pending_qty}).`
        );
    }
}

function confirmation_dialog_clear_data(frm) {
    frappe.confirm(
        __("This action will clear all existing project-related data, including items, tables, and linked fields. Do you want to proceed?"),
        function () {
            const fields_to_clear = [
                "po_items",
                "custom_project_master",
                // "custom_project_qty",
                "custom_sales_order",
                "custom_selected_project",
                "custom_project_master_of_sales_order",
                "sub_assembly_items",
                "mr_items",
                "custom__nesting_item_details",
                "custom__nesting_header",
                "custom__nesting_items"
            ];

            fields_to_clear.forEach(field => {
                const df = frm.fields_dict[field];
                if (!df) return;

                if (df.df.fieldtype === "Table") {
                    frm.clear_table(field);
                } else {
                    frm.set_value(field, null);
                }
            });

            frm.refresh_fields(fields_to_clear);

            frappe.show_alert({
                message: __("All related project data has been cleared successfully."),
                indicator: "green"
            });
        },
        function () {
            frappe.show_alert({
                message: __("Action cancelled. No data was cleared."),
                indicator: "orange"
            });
        }
    );
}

function add_select_project_button_and_handlers(frm) {
    frm.fields_dict["custom_project_master_of_sales_order"].grid.add_custom_button(
        __("Select Project"),
        function () {
            const selected = frm.fields_dict["custom_project_master_of_sales_order"].grid.get_selected_children();

            if (!selected.length) {
                frappe.msgprint({
                    title: __("No Selection"),
                    message: __("Please select at least one Project Master row first."),
                    indicator: "red"
                });
                return;
            }

            if (selected.length > 1) {
                frappe.msgprint({
                    title: __("Multiple Selected"),
                    message: __("Please select only one Project Master row at a time."),
                    indicator: "orange"
                });
                return;
            }

            const row = selected[0];

            frm.set_value("custom_selected_project", row.idx);
            frappe.call({
                method: "fetch_selected_project_master",
                doc: frm.doc,
                freeze: true,
                callback: function (r) {
                    if (!r.exc) {
                        const tables = [
                            "po_items",
                            "sub_assembly_items",
                            "mr_items",
                            "custom__nesting_item_details",
                            "custom__nesting_header",
                            "custom__nesting_items"
                        ];

                        tables.forEach(tbl => {
                            frm.refresh_field(tbl);
                            const grid = frm.fields_dict[tbl].grid;
                            grid.cannot_add_rows = true;
                            grid.cannot_delete_rows = true;
                            grid.df.read_only = 1
                            grid.wrapper.find('.grid-add-row, .grid-remove-rows').hide();
                            grid.only_sortable();
                        });
                        frm.refresh_fields()
                    }
                    frm.refresh_fields();
                }
            });
        },
    );
}


function update_po_table_quantities(frm, project_qty) {
    if (!frm || !project_qty) return;

    (frm.doc.po_items || []).forEach(row => {
        row.planned_qty = (row.custom_project_planned_qty || 0) * project_qty;
        console.log(row.planned_qty);

    });

    frm.refresh_field("po_items");
}



function update_nesting_and_items(frm, project_qty) {
    if (!frm || !project_qty) return;

    let nesting_qty_map = {};

    (frm.doc.custom__nesting_header || []).forEach(row => {
        row.total_nesting_qty = (row.nesting_qty || 0) * project_qty;
        row.net_sheet_weight = (row.sheet_weight || 0) * row.total_nesting_qty;
        row.net_sub_assembly_weight = (row.sub_assembly_weight || 0) * row.total_nesting_qty;
        row.net_scrap_weight = (row.scrap_weight || 0) * row.total_nesting_qty;

        if (row.nesting_no) {
            nesting_qty_map[row.nesting_no] = row.total_nesting_qty;
        }
    });

    (frm.doc.custom__nesting_items || []).forEach(row => {
        const total_qty = nesting_qty_map[row.nesting_no] || 0;
        row.net_qty = (row.qty || 0) * total_qty;
        row.net_weight = (row.net_qty || 0) * (row.weight || 0);
    });

    frm.refresh_field("custom__nesting_header");
    frm.refresh_field("custom__nesting_items");
}


function update_nesting_totals(frm) {
    if (!frm) return;

    let total_net_sheet_weight = 0;
    let total_weight_of_sheet = 0;
    let total_net_sub_assembly_weight = 0;
    let total_net_scrap_weight = 0;
    let total_scrap_percentage = 0;
    let max_scrap = 0;
    let max_scrap_nesting_no = "";

    (frm.doc.custom__nesting_header || []).forEach(row => {
        total_net_sheet_weight += row.net_sheet_weight || 0;
        total_weight_of_sheet += row.sheet_weight || 0;
        total_net_sub_assembly_weight += row.net_sub_assembly_weight || 0;
        total_net_scrap_weight += row.net_scrap_weight || 0;
        total_scrap_percentage += row.scrap_percentage || 0;

        if ((row.scrap_percentage || 0) > max_scrap) {
            max_scrap = row.scrap_percentage;
            max_scrap_nesting_no = row.nesting_no || "(no nesting)";
        }
    });

    const avg_scrap_percentage = (frm.doc.custom__nesting_header?.length || 0)
        ? total_scrap_percentage / frm.doc.custom__nesting_header.length
        : 0;

    frappe.model.set_value(frm.doctype, frm.docname, "custom_total_sheet_weight", flt(total_net_sheet_weight, 3));
    frappe.model.set_value(frm.doctype, frm.docname, "custom_total_weight_of_sheet", flt(total_weight_of_sheet, 3));
    frappe.model.set_value(frm.doctype, frm.docname, "custom_total_utilized_weight", flt(total_net_sub_assembly_weight, 3));
    frappe.model.set_value(frm.doctype, frm.docname, "custom_total_scrap_weight", flt(total_net_scrap_weight, 3));
    frappe.model.set_value(frm.doctype, frm.docname, "custom_scrap_percentage_average", flt(avg_scrap_percentage, 3));
    frappe.model.set_value(frm.doctype, frm.docname, "custom_highest_scrap_nesting_code", max_scrap_nesting_no);

    frm.refresh_field([
        "custom_total_sheet_weight",
        "custom_total_weight_of_sheet",
        "custom_total_utilized_weight",
        "custom_total_scrap_weight",
        "custom_scrap_percentage_average",
        "custom_highest_scrap_nesting_code",
    ]);
}

