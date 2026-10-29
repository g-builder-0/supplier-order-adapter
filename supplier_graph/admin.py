from django.contrib import admin

from .models import (
    CertificationLevel,
    OrderLine,
    Part,
    PurchaseOrder,
    ReceivingEvent,
    Supplier,
    SupplierPart,
)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_email", "created_at")
    search_fields = ("name",)


@admin.register(Part)
class PartAdmin(admin.ModelAdmin):
    list_display = ("sku", "name")
    search_fields = ("sku", "name")


@admin.register(SupplierPart)
class SupplierPartAdmin(admin.ModelAdmin):
    list_display = ("supplier", "part", "lead_time_days", "certification_level", "unit_price")
    list_filter = ("certification_level",)
    search_fields = ("supplier__name", "part__sku", "part__name")


class OrderLineInline(admin.TabularInline):
    model = OrderLine
    extra = 1


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ("po_number", "supplier", "status", "expected_date", "created_at")
    list_filter = ("status",)
    search_fields = ("po_number", "supplier__name")
    inlines = [OrderLineInline]


@admin.register(OrderLine)
class OrderLineAdmin(admin.ModelAdmin):
    list_display = ("purchase_order", "supplier_part", "quantity_ordered", "quantity_received", "status")
    list_filter = ("status",)


@admin.register(ReceivingEvent)
class ReceivingEventAdmin(admin.ModelAdmin):
    list_display = ("order_line", "quantity", "condition", "received_at")
    list_filter = ("condition",)
    readonly_fields = [f.name for f in ReceivingEvent._meta.fields]

    def has_change_permission(self, request, obj=None):
        # Append-only: admin can view but never edit a receiving event.
        return False
