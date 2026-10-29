from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import OrderLine, Part, ReceivingEvent, Supplier, SupplierPart
from .serializers import (
    OrderLineStatusSerializer,
    PartSupplierSerializer,
    ReceivingEventCreateSerializer,
    ReceivingEventSerializer,
    SupplierCertificationSerializer,
)
from .webhooks import dispatch_event

# Phase 3: which order_line.* webhook event (if any) a given OrderLine.Status
# maps to. PENDING has no event -- nothing has happened yet from a
# subscriber's point of view.
_STATUS_EVENT_TYPES = {
    OrderLine.Status.PARTIAL: "order_line.partial",
    OrderLine.Status.RECEIVED: "order_line.received",
    OrderLine.Status.FLAGGED: "order_line.flagged",
}


class ReceivingEventCreateView(APIView):
    """
    POST /api/receiving-events/

    Records a ReceivingEvent against an OrderLine and, in the same atomic
    transaction, recomputes that line's quantity_received and status. The
    status/quantity update intentionally happens here rather than via a
    signal, so the transaction boundary is explicit and visible rather
    than implicit in a receiver function elsewhere.
    """

    def post(self, request):
        serializer = ReceivingEventCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order_line = get_object_or_404(
            OrderLine, pk=serializer.validated_data["order_line"].pk
        )

        with transaction.atomic():
            event = serializer.save()
            self._apply_receipt(order_line, event)

        # Fired after the transaction above has committed, deliberately
        # outside transaction.atomic() -- this is a network call, and a
        # webhook subscriber being slow or down shouldn't hold the DB
        # transaction (or its locks) open while we wait on it.
        self._dispatch_status_event(order_line, event)

        return Response(
            {
                "receiving_event": ReceivingEventSerializer(event).data,
                "order_line": OrderLineStatusSerializer(order_line).data,
            },
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _apply_receipt(order_line: OrderLine, event: ReceivingEvent) -> None:
        """
        Recompute OrderLine.quantity_received / status from this event.

        Business rule (not specified in the build plan — adjust if this
        doesn't match intent): a DAMAGED or MISMATCHED event always marks
        the line FLAGGED, regardless of quantity -- this is a quality/condition
        problem on the goods received, not a quantity shortfall, which is why
        it's a separate branch from the quantity_received vs. quantity_ordered
        comparison below. Otherwise status follows the running total against
        quantity_ordered.
        """
        order_line.quantity_received += event.quantity

        if event.condition in (
            ReceivingEvent.Condition.DAMAGED,
            ReceivingEvent.Condition.MISMATCHED,
        ):
            order_line.status = OrderLine.Status.FLAGGED
        elif order_line.quantity_received >= order_line.quantity_ordered:
            order_line.status = OrderLine.Status.RECEIVED
        else:
            order_line.status = OrderLine.Status.PARTIAL

        order_line.save(update_fields=["quantity_received", "status"])

    @staticmethod
    def _dispatch_status_event(order_line: OrderLine, event: ReceivingEvent) -> None:
        """
        Fire the order_line.* webhook event (if any) for order_line's
        CURRENT status -- i.e. after _apply_receipt has already updated
        and saved it. No event fires for PENDING (nothing's happened yet).
        """
        event_type = _STATUS_EVENT_TYPES.get(order_line.status)
        if event_type is None:
            return

        dispatch_event(
            event_type,
            {
                "order_line_id": order_line.pk,
                "purchase_order": order_line.purchase_order.po_number,
                "sku": order_line.supplier_part.part.sku,
                "quantity_ordered": order_line.quantity_ordered,
                "quantity_received": order_line.quantity_received,
                "status": order_line.status,
                "receiving_event_id": event.pk,
                "condition": event.condition,
            },
        )


class PartSuppliersView(APIView):
    """
    GET /api/parts/<sku>/suppliers/

    Phase 4: "which suppliers can provide part X" and "who else supplies
    this part if the primary is delayed" are the same query shape -- every
    SupplierPart row for this part, ranked fastest-lead-time first. Pass
    ?exclude_supplier=<id> to drop one supplier (typically the one that's
    currently delayed) from the results, which is what turns this into
    the "who else" query.

    select_related("supplier") does the Part -> SupplierPart -> Supplier
    walk in the same query as the initial SupplierPart lookup, instead of
    issuing one extra SELECT per row to fetch its supplier (an N+1). The
    Hunter trace for this endpoint is paired with Django's query log
    (django.db.connection.queries) to confirm only one query runs.
    """

    def get(self, request, sku):
        part = get_object_or_404(Part, sku=sku)

        supplier_parts = (
            SupplierPart.objects.filter(part=part)
            .select_related("supplier")
            .order_by("lead_time_days")
        )

        exclude_supplier = request.query_params.get("exclude_supplier")
        if exclude_supplier:
            supplier_parts = supplier_parts.exclude(supplier_id=exclude_supplier)

        return Response(
            {
                "part": {"sku": part.sku, "name": part.name},
                "suppliers": PartSupplierSerializer(supplier_parts, many=True).data,
            }
        )


class SupplierCertificationsView(APIView):
    """
    GET /api/suppliers/<pk>/certifications/

    Phase 4: "what's the certification status for supplier Y" -- every
    part this supplier is on file for, with the certification level and
    lead time agreed for that specific part. Certification lives on
    SupplierPart, not Supplier, because a supplier can hold ISO 9001 on
    one part and nothing on another -- there is no single certification
    status for a supplier as a whole, so this returns a list, not a
    scalar field.

    select_related("part") does the Supplier -> SupplierPart -> Part walk
    in one query; without it, each row would issue its own SELECT for
    `part` when the serializer reads part.sku / part.name.
    """

    def get(self, request, pk):
        supplier = get_object_or_404(Supplier, pk=pk)

        supplier_parts = (
            SupplierPart.objects.filter(supplier=supplier)
            .select_related("part")
            .order_by("part__sku")
        )

        return Response(
            {
                "supplier": {"id": supplier.pk, "name": supplier.name},
                "parts": SupplierCertificationSerializer(supplier_parts, many=True).data,
            }
        )
