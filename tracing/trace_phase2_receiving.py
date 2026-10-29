"""
Paste this into `python manage.py shell` (or run with
`Get-Content supplier_graph\\trace_phase2_receiving.py | python manage.py shell`)
to produce a hunter trace of the Phase 2 receiving workflow:
DRF view -> serializer -> transaction.atomic() -> ORM update.

APIClient().post() runs the full Django request/response cycle
in-process (routing, view, serializer, DB) without a live server --
which is exactly what we want to trace in one hunter.trace() block,
the same way Phase 1 traced .objects.create() directly in the shell.
"""

import hunter
from rest_framework.test import APIClient

from supplier_graph.models import (
    CertificationLevel,
    OrderLine,
    Part,
    PurchaseOrder,
    ReceivingEvent,
    Supplier,
    SupplierPart,
)

# --- cleanup: make this script idempotent against db.sqlite3 ---
# These fixture values (sku, po_number, supplier name) are namespaced to this
# script specifically -- "...P2..." / "(Phase 2 Trace)" -- so this cleanup
# can never touch Phase 1's own leftover demo data (e.g. its "BOLT-001" /
# "Acme Fasteners" / "PO-1001" rows). Re-running this file previously failed
# with `ProtectedError` because it was reusing Phase 1's identifiers and
# trying to delete rows that Phase 1's own OrderLine still protects.
#
# Deletion order matters: OrderLine.supplier_part and
# ReceivingEvent.order_line are both on_delete=PROTECT, so children must go
# before parents. Part -> SupplierPart is on_delete=CASCADE, so deleting
# Part below also removes its SupplierPart automatically.
ReceivingEvent.objects.filter(order_line__purchase_order__po_number="PO-P2-2001").delete()
OrderLine.objects.filter(purchase_order__po_number="PO-P2-2001").delete()
PurchaseOrder.objects.filter(po_number="PO-P2-2001").delete()
Part.objects.filter(sku="BOLT-P2-001").delete()
Supplier.objects.filter(name="Acme Fasteners (Phase 2 Trace)").delete()

# --- fixture setup (left untraced -- same Phase 1 .create() calls you've already traced) ---
supplier = Supplier.objects.create(name="Acme Fasteners (Phase 2 Trace)", contact_email="orders@acme.test")
part = Part.objects.create(sku="BOLT-P2-001", name="M8 Hex Bolt (Phase 2 Trace)")
supplier_part = SupplierPart.objects.create(
    supplier=supplier,
    part=part,
    lead_time_days=5,
    certification_level=CertificationLevel.STANDARD,
    unit_price="0.42",
)
po = PurchaseOrder.objects.create(supplier=supplier, po_number="PO-P2-2001")
order_line = OrderLine.objects.create(
    purchase_order=po,
    supplier_part=supplier_part,
    quantity_ordered=100,
)

client = APIClient()

# --- traced: the actual receiving POST ---
# module_startswith scopes the trace to your app, DRF, and the ORM/transaction
# layer -- widen or narrow this tuple depending on what you want to see.
with hunter.trace(
    module_startswith=("supplier_graph", "rest_framework", "django.db"),
    kind="call",
    action=hunter.CodePrinter,
):
    response = client.post(
        "/api/receiving-events/",
        {
            "order_line": order_line.id,
            "quantity": 40,
            "condition": "good",
            "note": "first partial shipment",
        },
        format="json",
        SERVER_NAME="localhost",
    )

print(response.status_code, response.data)

# --- a second POST, to see the FLAGGED-status branch and a second atomic pass ---
with hunter.trace(
    module_startswith=("supplier_graph", "rest_framework", "django.db"),
    kind="call",
    action=hunter.CodePrinter,
):
    response2 = client.post(
        "/api/receiving-events/",
        {
            "order_line": order_line.id,
            "quantity": 10,
            "condition": "damaged",
            "note": "partial shipment arrived with damage",
        },
        format="json",
        SERVER_NAME="localhost",
    )

print(response2.status_code, response2.data)
