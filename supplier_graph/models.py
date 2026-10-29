from django.db import models


class Supplier(models.Model):
    """A company that can provide parts against purchase orders."""
    name = models.CharField(max_length=200)
    contact_email = models.EmailField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Part(models.Model):
    """A component or material the system tracks orders and receipts for."""
    sku = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    def __str__(self):
        return f"{self.sku} — {self.name}"


class CertificationLevel(models.TextChoices):
    NONE = "none", "No certification on file"
    STANDARD = "standard", "Standard"
    ISO_9001 = "iso_9001", "ISO 9001"
    AS_9100 = "as_9100", "AS9100 (aerospace)"


class SupplierPart(models.Model):
    """
    The graph edge: which supplier can provide which part, and on what terms.
    This is the table the knowledge-graph queries in Phase 4 walk across —
    "who else supplies this part" is a query over SupplierPart rows sharing
    a part, filtered/ranked by lead_time_days and certification_level.
    """
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name="supplier_parts")
    part = models.ForeignKey(Part, on_delete=models.CASCADE, related_name="supplier_parts")
    lead_time_days = models.PositiveIntegerField()
    certification_level = models.CharField(
        max_length=20,
        choices=CertificationLevel.choices,
        default=CertificationLevel.NONE,
    )
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        unique_together = ("supplier", "part")

    def __str__(self):
        return f"{self.supplier} → {self.part} ({self.lead_time_days}d)"


class PurchaseOrder(models.Model):
    """An open commitment to a supplier for one or more parts."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        PARTIAL = "partial", "Partially received"
        RECEIVED = "received", "Fully received"
        CLOSED = "closed", "Closed"
        CANCELLED = "cancelled", "Cancelled"

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_orders")
    po_number = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    expected_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.po_number


class OrderLine(models.Model):
    """
    One part/quantity commitment within a purchase order. Tied to the
    specific SupplierPart agreement it was sourced from, not just to
    'part' and 'supplier' independently — that keeps the lead-time and
    certification terms this line was ordered under traceable.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PARTIAL = "partial", "Partially received"
        RECEIVED = "received", "Received"
        FLAGGED = "flagged", "Flagged / discrepancy"

    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    supplier_part = models.ForeignKey(SupplierPart, on_delete=models.PROTECT, related_name="order_lines")
    quantity_ordered = models.PositiveIntegerField()
    quantity_received = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    def __str__(self):
        return f"{self.purchase_order.po_number} / {self.supplier_part.part.sku}"


class WebhookDeliveryLog(models.Model):
    """
    Phase 6 demo-only record of a webhook delivery. Not a real delivery
    audit trail (no retry tracking, no per-subscriber scoping -- that's
    the Phase 4-alternative scope that wasn't built) -- this exists purely
    so the demo page has something to poll and display as "the webhook
    log," proving end to end that dispatch_event's outbound POST actually
    arrived and carried a signature this same service can independently
    verify. Populated by WebhookReceiverView, which plays the part of an
    external subscriber receiving its own service's webhook.
    """

    event_type = models.CharField(max_length=100)
    payload = models.JSONField()
    signature_valid = models.BooleanField()
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.event_type} ({'valid' if self.signature_valid else 'INVALID'} sig) @ {self.received_at:%H:%M:%S}"


class ReceivingEvent(models.Model):
    """
    Append-only audit record of a receipt against an order line. Never
    updated or deleted after creation — OrderLine.quantity_received and
    .status are the current-state summary; this table is the history that
    summary is derived from. Mirrors the InventoryTransaction discipline
    from fishbowl-clone.
    """

    class Condition(models.TextChoices):
        GOOD = "good", "Good"
        DAMAGED = "damaged", "Damaged"
        MISMATCHED = "mismatched", "Mismatched / wrong item"

    order_line = models.ForeignKey(OrderLine, on_delete=models.PROTECT, related_name="receiving_events")
    quantity = models.PositiveIntegerField()
    condition = models.CharField(max_length=20, choices=Condition.choices, default=Condition.GOOD)
    note = models.CharField(max_length=500, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.quantity} received on {self.order_line} ({self.condition})"
