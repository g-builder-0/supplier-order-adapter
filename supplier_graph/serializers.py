from rest_framework import serializers

from .models import OrderLine, ReceivingEvent, SupplierPart, WebhookDeliveryLog


class ReceivingEventCreateSerializer(serializers.ModelSerializer):
    """
    Validates the inbound receipt. Deliberately only exposes the fields a
    caller should be supplying — order_line, quantity, condition, note.
    quantity_received / status updates on OrderLine are not writable here;
    those are derived, inside the view, from accepted ReceivingEvents only.
    """

    class Meta:
        model = ReceivingEvent
        fields = ["order_line", "quantity", "condition", "note"]

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("quantity must be greater than zero.")
        return value


class OrderLineStatusSerializer(serializers.ModelSerializer):
    """Read-only summary of an OrderLine's current state, returned after a receipt is recorded."""

    class Meta:
        model = OrderLine
        fields = ["id", "purchase_order", "supplier_part", "quantity_ordered", "quantity_received", "status"]
        read_only_fields = fields


class ReceivingEventSerializer(serializers.ModelSerializer):
    """Read-only representation of a persisted ReceivingEvent, for the response body."""

    class Meta:
        model = ReceivingEvent
        fields = ["id", "order_line", "quantity", "condition", "note", "received_at"]
        read_only_fields = fields


class PartSupplierSerializer(serializers.ModelSerializer):
    """
    Phase 4: one supplier's terms for a given part, as returned by
    PartSuppliersView ("which suppliers can provide part X" / "who else
    supplies this part"). Reads across the SupplierPart -> Supplier join
    that view's select_related("supplier") already fetched, so these
    `source="supplier.*"` lookups don't trigger their own queries.
    """

    supplier_id = serializers.IntegerField(source="supplier.id")
    supplier_name = serializers.CharField(source="supplier.name")
    contact_email = serializers.EmailField(source="supplier.contact_email")
    certification_level_display = serializers.CharField(source="get_certification_level_display")

    class Meta:
        model = SupplierPart
        fields = [
            "supplier_id",
            "supplier_name",
            "contact_email",
            "lead_time_days",
            "certification_level",
            "certification_level_display",
            "unit_price",
        ]
        read_only_fields = fields


class SupplierCertificationSerializer(serializers.ModelSerializer):
    """
    Phase 4: one part a supplier is on file for, as returned by
    SupplierCertificationsView ("what's the certification status for
    supplier Y"). certification_level lives on SupplierPart, not Supplier
    -- a supplier can hold a different certification per part -- so this
    is one row per part, not a single status for the supplier.
    """

    part_sku = serializers.CharField(source="part.sku")
    part_name = serializers.CharField(source="part.name")
    certification_level_display = serializers.CharField(source="get_certification_level_display")

    class Meta:
        model = SupplierPart
        fields = [
            "part_sku",
            "part_name",
            "lead_time_days",
            "certification_level",
            "certification_level_display",
            "unit_price",
        ]
        read_only_fields = fields


class WebhookDeliveryLogSerializer(serializers.ModelSerializer):
    """Read-only representation of a logged webhook delivery, for the demo page's polling endpoint."""

    class Meta:
        model = WebhookDeliveryLog
        fields = ["id", "event_type", "payload", "signature_valid", "received_at"]
        read_only_fields = fields
