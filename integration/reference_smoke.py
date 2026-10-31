"""Run real Frappe/ERPNext operations in the disposable PostgreSQL CI site."""

import argparse
import json
from pathlib import Path

import frappe

from frappe_originchaindb.database import OriginChainDatabase


def framework():
    assert isinstance(frappe.db, OriginChainDatabase)
    try:
        OriginChainDatabase(host="unintended-target.invalid")
    except ValueError:
        pass
    else:
        raise AssertionError("Alternate target silently fell back to the site's database")
    assert frappe.db.db_type == "postgres"  # SQL dialect is distinct from backend identity.
    frappe.db.commit()
    assert frappe.db.sql("SHOW transaction_isolation")[0][0] == "repeatable read"
    name = "OC Adapter Probe"
    if not frappe.db.exists("DocType", name):
        frappe.get_doc(
            {
                "doctype": "DocType",
                "name": name,
                "module": "Custom",
                "custom": 1,
                "autoname": "field:title",
                "fields": [
                    {"fieldname": "title", "label": "Title", "fieldtype": "Data", "reqd": 1},
                    {"fieldname": "amount", "label": "Amount", "fieldtype": "Currency"},
                ],
                "permissions": [{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1}],
            }
        ).insert()
    frappe.db.commit()
    if frappe.db.exists(name, "persisted"):
        frappe.delete_doc(name, "persisted")
        frappe.db.commit()
    doc = frappe.get_doc({"doctype": name, "title": "persisted", "amount": 12.5}).insert()
    frappe.db.commit()
    assert frappe.get_doc(name, doc.name).amount == 12.5
    frappe.db.set_value(name, doc.name, "amount", 99)
    frappe.db.rollback()
    assert frappe.db.get_value(name, doc.name, "amount") == 12.5
    frappe.db.savepoint("oc_smoke")
    frappe.get_doc({"doctype": name, "title": "rolled-back"}).insert()
    frappe.db.rollback(save_point="oc_smoke")
    frappe.db.release_savepoint("oc_smoke")
    assert not frappe.db.exists(name, "rolled-back")
    frappe.db.commit()
    meta = frappe.get_doc("DocType", name)
    if not any(field.fieldname == "extra_note" for field in meta.fields):
        meta.append("fields", {"fieldname": "extra_note", "label": "Extra Note", "fieldtype": "Data"})
        meta.save()
    frappe.db.commit()
    frappe.db.set_value(name, doc.name, "extra_note", "schema evolved")
    frappe.db.commit()
    assert frappe.get_doc(name, doc.name).extra_note == "schema evolved"
    for write in [
        '/* write */ UPDATE "tabOC Adapter Probe" SET amount=88 WHERE name=%s',
        'WITH changed AS (UPDATE "tabOC Adapter Probe" SET amount=88 WHERE name=%s RETURNING name) SELECT * FROM changed',
    ]:
        frappe.db.sql(write, (doc.name,))
        frappe.db.savepoint("oc_guard")
        frappe.db.set_value(name, doc.name, "amount", 77)
        frappe.db.rollback(save_point="oc_guard")
        try:
            frappe.db.sql('CREATE TABLE "oc_forbidden_implicit_commit" (name TEXT)')
        except frappe.ImplicitCommitError:
            pass
        else:
            raise AssertionError(
                "DDL was accepted after rollback to savepoint with earlier writes still pending"
            )
        finally:
            frappe.db.rollback()
        assert frappe.db.get_value(name, doc.name, "amount") == 12.5
    return [
        "backend_dispatch",
        "alternate_target_refused",
        "doctype_schema",
        "document_insert_read",
        "rollback",
        "savepoints",
        "schema_evolution",
        "implicit_commit_guard",
        "writable_cte_accounting",
        "savepoint_preserves_ddl_guard",
    ]


def erpnext():
    assert "erpnext" in frappe.get_installed_apps()
    assert frappe.db.exists("DocType", "Sales Invoice")
    from erpnext.crm.report.lost_opportunity.lost_opportunity import get_data
    from erpnext.stock.doctype.pick_list.pick_list import GroupConcat

    rows = get_data(frappe._dict())
    assert isinstance(rows, list)
    item = frappe.qb.DocType("Pick List Item")
    query = frappe.qb.from_(item).select(GroupConcat(item.sales_order).distinct())
    assert "STRING_AGG" in query.get_sql()
    query.run()
    return [
        "erpnext_installation",
        "sales_invoice_metadata",
        "lost_opportunity_query",
        "pick_list_aggregation",
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["framework", "erpnext"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {
        "target": "reference_postgresql_18",
        "originchaindb_tested": False,
        "full_functionality_verified": False,
        "phase": args.phase,
        "status": "failed",
    }
    try:
        frappe.init("oc-test.local", sites_path=".")
        frappe.connect()
        frappe.set_user("Administrator")
        report["checks"] = framework() if args.phase == "framework" else erpnext()
        report["status"] = "passed"
    finally:
        frappe.destroy()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
