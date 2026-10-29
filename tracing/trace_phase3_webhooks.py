"""
Phase 3 hunter trace: receiving view -> webhook dispatcher -> HMAC signing
-> outbound POST.

Run from PowerShell, in the project root, with the venv active:

    python manage.py shell -c "exec(open('supplier_graph/trace_phase3_webhooks.py').read())"

(Not `Get-Content ... | python manage.py shell` -- piping feeds the file to
the REPL one line at a time, and the REPL executes each indented block as
soon as it looks complete, so a blank line inside a class/function/with
body ends that block early and the next indented line errors out as
unexpected. `shell -c "exec(...)"` compiles the whole file as one unit
instead, so this doesn't happen regardless of blank lines.)

What this does, in order:
1. Starts a tiny local HTTP server on 127.0.0.1 (a request-bin stand-in --
   it just records the request it receives and returns 200) and points
   settings.WEBHOOK_SUBSCRIBER_URL at it for the duration of this script.
2. Cleans up and recreates a Phase-3-namespaced fixture set (distinct
   SKU/PO/supplier names from Phase 1 and Phase 2's fixtures, so this
   script never touches their data -- same lesson learned from the
   Phase 2 ProtectedError).
3. Fires two receiving POSTs through APIClient -- one that fully
   receives a line (-> order_line.received) and one damaged partial
   receipt (-> order_line.flagged) -- each wrapped in a hunter.trace that
   follows the call from the view, into supplier_graph.webhooks, through
   hmac.new, into requests.post building and sending the real outbound
   request to the local server.
4. After each POST, independently recomputes the HMAC signature from the
   request body the server actually received and asserts it matches the
   X-Webhook-Signature header the dispatcher sent -- the "would a
   receiver independently compute the same signature" check.
"""

import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import hunter
from django.conf import settings
from django.test import override_settings
from rest_framework.test import APIClient

from supplier_graph.models import (
    OrderLine,
    Part,
    PurchaseOrder,
    ReceivingEvent,
    Supplier,
    SupplierPart,
)

# --- idempotent cleanup: FK-safe order, Phase-3-namespaced only ------------
# ReceivingEvent.order_line is on_delete=PROTECT, same lesson as Phase 2's
# ProtectedError: anything this script's own earlier run may have created
# through the receiving endpoint (a ReceivingEvent) has to go before the
# OrderLine it points at, not after.
ReceivingEvent.objects.filter(order_line__purchase_order__po_number="PO-P3-3001").delete()
OrderLine.objects.filter(purchase_order__po_number="PO-P3-3001").delete()
PurchaseOrder.objects.filter(po_number="PO-P3-3001").delete()
SupplierPart.objects.filter(part__sku="BOLT-P3-001").delete()
Part.objects.filter(sku="BOLT-P3-001").delete()
Supplier.objects.filter(name="Acme Fasteners (Phase 3 Trace)").delete()

# --- a request-bin stand-in: records what it receives, answers 200 --------
received_requests = []


class _CaptureHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        received_requests.append({"headers": dict(self.headers), "body": body})
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"received": true}')

    def log_message(self, fmt, *args):
        pass  # keep the trace output free of the server's own request log lines


server = HTTPServer(("127.0.0.1", 0), _CaptureHandler)
server_port = server.server_address[1]
server_thread = threading.Thread(target=server.serve_forever, daemon=True)
server_thread.start()

TEST_SECRET = "phase3-trace-test-secret"


def verify_last_delivery(event_type_expected):
    """
    Independently recompute the signature from the body the server
    actually received, the way a real subscriber would, and assert it
    matches the X-Webhook-Signature header the dispatcher sent.
    """
    delivery = received_requests[-1]
    body_bytes = delivery["body"]
    sent_signature = delivery["headers"].get("X-Webhook-Signature")
    sent_event_header = delivery["headers"].get("X-Webhook-Event")

    # Canonicalize the same way generate_signature does: parse back to a
    # dict, then re-serialize with sort_keys=True. A receiver only has the
    # raw bytes on the wire -- it can't see the sender's original dict --
    # so this re-parse-and-resort step is exactly what it would have to do.
    parsed = json.loads(body_bytes)
    recomputed = hmac.new(
        TEST_SECRET.encode("utf-8"),
        json.dumps(parsed, sort_keys=True).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    assert sent_event_header == event_type_expected, (sent_event_header, event_type_expected)
    assert recomputed == sent_signature, (recomputed, sent_signature)
    print(f"signature verified independently for {event_type_expected}: {recomputed[:16]}...")


client = APIClient()

with override_settings(
    WEBHOOK_SUBSCRIBER_URL=f"http://127.0.0.1:{server_port}/webhook",
    WEBHOOK_SECRET=TEST_SECRET,
):
    # --- fixtures (Phase-3-namespaced) -------------------------------------
    supplier = Supplier.objects.create(name="Acme Fasteners (Phase 3 Trace)")
    part = Part.objects.create(sku="BOLT-P3-001", name="M8 Hex Bolt (Phase 3 Trace)")
    supplier_part = SupplierPart.objects.create(
        supplier=supplier, part=part, lead_time_days=7,
    )
    po = PurchaseOrder.objects.create(supplier=supplier, po_number="PO-P3-3001")
    line_received = OrderLine.objects.create(
        purchase_order=po, supplier_part=supplier_part, quantity_ordered=50,
    )
    line_short = OrderLine.objects.create(
        purchase_order=po, supplier_part=supplier_part, quantity_ordered=50,
    )

    # --- scenario 1: full receipt -> order_line.received -------------------
    with hunter.trace(module_startswith=("supplier_graph", "hmac", "requests"), kind="call", action=hunter.CodePrinter):
        response = client.post(
            "/api/receiving-events/",
            {"order_line": line_received.id, "quantity": 50, "condition": "good"},
            format="json",
            SERVER_NAME="localhost",
        )
    print(response.status_code, response.data)
    verify_last_delivery("order_line.received")

    # --- scenario 2: damaged partial receipt -> order_line.flagged ---------
    with hunter.trace(module_startswith=("supplier_graph", "hmac", "requests"), kind="call", action=hunter.CodePrinter):
        response2 = client.post(
            "/api/receiving-events/",
            {"order_line": line_short.id, "quantity": 10, "condition": "damaged"},
            format="json",
            SERVER_NAME="localhost",
        )
    print(response2.status_code, response2.data)
    verify_last_delivery("order_line.flagged")

server.shutdown()
