frappe.ui.form.on("Purchase Order Item", {
    custom_fetch_previous_price: function (frm, cdt, cdn) {

        const row = frappe.get_doc(cdt, cdn);
        if (!row.item_code) {
            frappe.msgprint({
                title: __("Error"),
                message: __("Please select an item first."),
                indicator: "red"
            });
            return;
        }
        frappe.call({
            method: "abstra.api.get_item_history",
            args: {
                item_code: row.item_code
            },
            callback: function (r) {
                if (r.message) {
                    display_history_in_dialog(r.message, row.item_code);
                } else {
                    frappe.msgprint({
                        title: __("Error"),
                        message: __("No purchase history found or an error occurred."),
                        indicator: "red"
                    });
                }
            }
        });
    }
});

function display_history_in_dialog(data, item_code) {
    var dialog = new frappe.ui.Dialog({
        title: __("Purchase History for {0}", [item_code]),
        fields: [
            {
                fieldtype: "HTML",
                fieldname: "history_table"
            }
        ],
        primary_action: function () {
            dialog.hide();
        },
        primary_action_label: __("Close")
    });

    var html = "<table class='table table-bordered'><thead><tr>" +
        "<th>Item</th><th>Supplier</th><th>Purchase Order</th><th>Purchase Date</th><th>Qty</th><th>Rate</th>" +
        "</tr></thead><tbody>";
    data.forEach(row => {
        html += "<tr>" +
            `<td>${row.item || ''}</td>` +
            `<td>${row.supplier || ''}</td>` +
            `<td>${row.purchase_order || ''}</td>` +
            `<td>${row.purchase_date || ''}</td>` +
            `<td>${row.qty || ''}</td>` +
            `<td>${row.rate || ''}</td>` +
            "</tr>";
    });
    html += "</tbody></table>";

    dialog.fields_dict.history_table.$wrapper.html(html);
    dialog.show();
}
