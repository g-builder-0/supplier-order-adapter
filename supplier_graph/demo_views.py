"""
Phase 6: the demo UI's own views. Deliberately kept separate from
views.py -- these aren't part of the real API surface (receiving events,
knowledge-graph queries); they exist to make Phase 3's webhook dispatcher
observable on camera, by having this same service also play the role of
an external subscriber receiving its own webhook.
"""

import hmac

from django.conf import settings
from django.shortcuts import render
from django.views.generic import TemplateView
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import OrderLine, WebhookDeliveryLog
from .serializers import WebhookDeliveryLogSerializer
from .webhooks import generate_signature

# How many recent deliveries the demo page's log panel shows.
WEBHOOK_LOG_DISPLAY_LIMIT = 20


class WebhookReceiverView(APIView):
    """
    POST /api/demo/webhook-receiver/

    Stands in for an external webhook subscriber. WEBHOOK_SUBSCRIBER_URL
    (see .env) points at this same endpoint, so when the demo page submits
    a receiving event, webhooks.dispatch_event's outbound POST lands here
    -- this service receiving a webhook it sent to itself.

    Independently recomputes the HMAC signature exactly the way a real
    subscriber would (generate_signature over the parsed body, compared
    against X-Webhook-Signature with a constant-time comparison) rather
    than trusting the header. That's the same verification trace_phase3's
    verify_last_delivery() did in a throwaway test script; here it's real
    code, and the result (valid or not) is what gets logged and shown.
    """

    def post(self, request):
        body = request.data
        expected_signature = generate_signature(body, settings.WEBHOOK_SECRET)
        received_signature = request.headers.get("X-Webhook-Signature", "")
        signature_valid = hmac.compare_digest(expected_signature, received_signature)

        WebhookDeliveryLog.objects.create(
            event_type=body.get("event_type", request.headers.get("X-Webhook-Event", "unknown")),
            payload=body,
            signature_valid=signature_valid,
        )

        return Response({"received": True, "signature_valid": signature_valid}, status=status.HTTP_200_OK)


class WebhookLogView(APIView):
    """
    GET /api/demo/webhook-log/

    The most recent WebhookDeliveryLog entries, newest first (model's
    default ordering), for the demo page to poll after submitting a
    receiving event -- this is what makes the webhook log feel "live"
    without actual push/websocket infrastructure.
    """

    def get(self, request):
        deliveries = WebhookDeliveryLog.objects.all()[:WEBHOOK_LOG_DISPLAY_LIMIT]
        return Response(WebhookDeliveryLogSerializer(deliveries, many=True).data)


class DemoPageView(TemplateView):
    """
    GET /demo/

    The Phase 6 page itself: a form to submit a receiving event against
    an existing OrderLine, plus a panel that polls WebhookLogView so you
    can watch a delivery appear right after submitting. Deliberately
    plain -- server-rendered order-line list, vanilla fetch() for the two
    dynamic parts, no build step, no framework.
    """

    template_name = "supplier_graph/demo.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["order_lines"] = (
            OrderLine.objects.select_related(
                "purchase_order", "supplier_part__part", "supplier_part__supplier"
            ).order_by("purchase_order__po_number", "id")
        )
        return context
