"""
Run with:
    python manage.py shell -c "exec(open('supplier_graph/trace_phase4_queries.py').read())"

(Not piped via `Get-Content | python manage.py shell` -- that invocation
hits the REPL blank-line gotcha documented in trace_phase3_webhooks.py.
-c "exec(...)" compiles this whole file as one unit instead.)

Produces a hunter trace of both Phase 4 knowledge-graph query endpoints:

  1. PartSuppliersView  (part -> SupplierPart -> supplier)
  2. SupplierCertificationsView (supplier -> SupplierPart -> part)

paired with Django's own query log (django.test.utils.CaptureQueriesContext)
so the actual SQL each endpoint runs is visible alongside the trace -- this
is what answers the Phase 4 trace point's real question: is select_related
actually doing its job, or is there an N+1 hiding in here that the hunter
trace alone wouldn't make obvious (hunter shows *that* a query ran, not how
many extra ones a missing join would have caused).
"""

import hunter
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from supplier_graph.models import CertificationLevel, Part, Supplier, SupplierPart

# --- cleanup: make this script idempotent, namespaced so it never touches
# Phase 1/2/3/5's own data (same discipline as trace_phase2/3) ---
SupplierPart.objects.filter(part__sku="BOLT-P4-001").delete()
Part.objects.filter(sku="BOLT-P4-001").delete()
Supplier.objects.filter(name__endswith="(Phase 4 Trace)").delete()

# --- fixture: one part, three suppliers covering it (so "which suppliers
# can provide this part" returns more than one row -- the multi-hop case
# the build plan calls out), and one of those suppliers also covering a
# second part (so SupplierCertificationsView returns more than one row too) ---
supplier_a = Supplier.objects.create(name="Acme Fasteners (Phase 4 Trace)", contact_email="orders@acme.test")
supplier_b = Supplier.objects.create(name="Titan Alloys (Phase 4 Trace)", contact_email="orders@titan.test")
supplier_c = Supplier.objects.create(name="Precision Aerostructures (Phase 4 Trace)", contact_email="procurement@precisionaero.test")

part = Part.objects.create(sku="BOLT-P4-001", name="M8 Hex Bolt (Phase 4 Trace)")
part_2 = Part.objects.create(sku="BRACKET-P4-002", name="Aluminum Bracket (Phase 4 Trace)")

SupplierPart.objects.create(supplier=supplier_a, part=part, lead_time_days=5, certification_level=CertificationLevel.STANDARD, unit_price="0.42")
SupplierPart.objects.create(supplier=supplier_b, part=part, lead_time_days=12, certification_level=CertificationLevel.ISO_9001, unit_price="0.38")
SupplierPart.objects.create(supplier=supplier_c, part=part, lead_time_days=18, certification_level=CertificationLevel.AS_9100, unit_price="0.95")
SupplierPart.objects.create(supplier=supplier_a, part=part_2, lead_time_days=9, certification_level=CertificationLevel.STANDARD, unit_price="6.10")

client = APIClient()

# --- scenario 1: PartSuppliersView -- "which suppliers can provide this part" ---
with CaptureQueriesContext(connection) as queries_1:
    with hunter.trace(
        module_startswith=("supplier_graph", "rest_framework", "django.db.models"),
        kind="call",
        action=hunter.CodePrinter,
    ):
        response_1 = client.get(f"/api/parts/{part.sku}/suppliers/", SERVER_NAME="localhost")

print(response_1.status_code, response_1.data)
print(f"--- scenario 1: {len(queries_1)} SQL query(ies) executed ---")
for q in queries_1:
    print(q["sql"])

# --- scenario 2: SupplierCertificationsView -- "what is supplier A on file for" ---
with CaptureQueriesContext(connection) as queries_2:
    with hunter.trace(
        module_startswith=("supplier_graph", "rest_framework", "django.db.models"),
        kind="call",
        action=hunter.CodePrinter,
    ):
        response_2 = client.get(f"/api/suppliers/{supplier_a.pk}/certifications/", SERVER_NAME="localhost")

print(response_2.status_code, response_2.data)
print(f"--- scenario 2: {len(queries_2)} SQL query(ies) executed ---")
for q in queries_2:
    print(q["sql"])
