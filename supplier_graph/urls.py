from django.urls import path

from .demo_views import DemoPageView, WebhookLogView, WebhookReceiverView
from .views import (
    PartSuppliersView,
    ReceivingEventCreateView,
    SupplierCertificationsView,
)

urlpatterns = [
    path("receiving-events/", ReceivingEventCreateView.as_view(), name="receiving-event-create"),
    path("parts/<str:sku>/suppliers/", PartSuppliersView.as_view(), name="part-suppliers"),
    path("suppliers/<int:pk>/certifications/", SupplierCertificationsView.as_view(), name="supplier-certifications"),
    # Phase 6 demo-only endpoints -- not part of the real API surface.
    path("demo/webhook-receiver/", WebhookReceiverView.as_view(), name="demo-webhook-receiver"),
    path("demo/webhook-log/", WebhookLogView.as_view(), name="demo-webhook-log"),
]
