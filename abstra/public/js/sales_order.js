frappe.ui.form.on("Sales Order", {
    validate: function (frm) {
        const project_rows = frm.doc.custom_project_master || [];

        if (project_rows.length === 0) return;

        project_rows.forEach(row => {
            if (!row.project_master) {
                frappe.throw(__("Project Master is required in all rows."));
            }

            if (!row.project_qty || row.project_qty <= 0) {
                frappe.throw(
                    __("Project Quantity must be greater than 0 for Project Master: {0}", [row.project_master])
                );
            }
        });
    }
});

frappe.ui.form.on("Sales Order Project Master", {

    project_master: function (frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.project_master) return;

        const is_duplicate = (frm.doc.custom_project_master || []).some(
            r => r.project_master === row.project_master && r.name !== row.name
        );

        if (is_duplicate) {
            frappe.msgprint({
                title: __("Duplicate Project"),
                message: __("Project Master {0} is already added.", [row.project_master]),
                indicator: "red"
            });

            frappe.model.set_value(cdt, cdn, "project_master", "");
            return;
        }

        const tbl = frm.doc.items || [];
        let i = tbl.length;
        while (i--) {
            if (tbl[i].custom_sales_order_project_master_reference == row.idx) {
                frm.get_field("items").grid.grid_rows[i].remove();
            }
        }

        frappe.call({
            method: "abstra.api.get_project_fg_items",
            args: {
                project_master: row.project_master,
                project_qty: row.project_qty || 1,
                delivery_date: frm.doc.delivery_date,
            },
            callback: function (r) {
                const res = r.message;
                if (!res || !res.success) {
                    frappe.msgprint(__(res?.message || "Failed to fetch Project FG Items"));
                    return;
                }

                (res.items || []).forEach(item => {
                    frm.add_child("items", {
                        ...item,
                        custom_project_master: row.project_master,
                        qty: (item.custom_project_qty * row.project_qty) || 1,
                        custom_sales_order_project_master_reference: row.idx
                    });
                });

                frm.refresh_field("items");

                frappe.show_alert({
                    message: __("FG Items fetched from Project Master: ") + row.project_master,
                    indicator: "green",
                });
            },
        });
    },

    project_qty: function (frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        row.pending_qty = row.project_qty;
        if (!row.project_master) return;

        if (!row.project_qty || row.project_qty < 1) {
            frappe.msgprint({
                title: __("Invalid Quantity"),
                message: __("Project Quantity must be at least 1."),
                indicator: "red"
            });

            frappe.model.set_value(cdt, cdn, "project_qty", 1);
            frappe.model.set_value(cdt, cdn, "pending_qty", 1);
            return;
        }

        (frm.doc.items || []).forEach(item => {
            if (item.custom_project_master === row.project_master) {
                item.qty = (item.custom_project_qty || 1) * (row.project_qty || 1);
                item.amount = item.rate * item.qty;
            }
        });

        frm.refresh_field("items");
    },

    before_custom_project_master_remove: function (frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.name) return;

        const tbl = frm.doc.items || [];
        let i = tbl.length;

        while (i--) {
            if (tbl[i].custom_project_master === row.project_master) {
                frm.get_field("items").grid.grid_rows[i].remove();
            }
        }

        frm.refresh_field("items");

        frappe.show_alert({
            message: __("Removed FG Items linked to Project Row: ") + row.project_master,
            indicator: "red",
        });
    }

});
