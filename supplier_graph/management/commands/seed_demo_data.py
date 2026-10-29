"""
Phase 5: seeds a believable small demo dataset -- suppliers, parts,
overlapping SupplierPart coverage (so Phase 4's "who else supplies this
part" queries return something non-trivial), and a few open purchase
orders ready to receive against on camera for the Demo Day video.

Idempotent by design: re-running this command updates existing rows
in place (get_or_create / update_or_create keyed on each model's real
unique field -- Supplier.name, Part.sku, SupplierPart's
(supplier, part) pair, PurchaseOrder.po_number, OrderLine's
(purchase_order, supplier_part) pair) rather than creating duplicates
on a second run.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from supplier_graph.models import (
    CertificationLevel,
    OrderLine,
    Part,
    PurchaseOrder,
    Supplier,
    SupplierPart,
)

SUPPLIERS = [
    {"name": "Acme Fasteners", "contact_email": "sales@acmefasteners.example.com"},
    {"name": "Titan Alloys", "contact_email": "orders@titanalloys.example.com"},
    {"name": "Precision Aerostructures", "contact_email": "procurement@precisionaero.example.com"},
    {"name": "Lonestar Machining", "contact_email": "info@lonestarmachining.example.com"},
    {"name": "Summit Industrial Supply", "contact_email": "sales@summitindustrial.example.com"},
]

PARTS = [
    {"sku": "BOLT-M8-001", "name": "M8x40 Hex Bolt, Grade 8", "description": "Hex head cap screw, M8x40, Grade 8 steel, zinc plated."},
    {"sku": "BOLT-M6-002", "name": "M6x25 Hex Bolt, Grade 8", "description": "Hex head cap screw, M6x25, Grade 8 steel, zinc plated."},
    {"sku": "WASHER-M8-003", "name": "M8 Flat Washer, Zinc Plated", "description": "Flat washer sized for M8 hardware, zinc plated steel."},
    {"sku": "NUT-M8-004", "name": "M8 Hex Nut, Grade 8", "description": "Hex nut, M8, Grade 8 steel, zinc plated."},
    {"sku": "BRACKET-AL-005", "name": "Aluminum L-Bracket, 6061-T6", "description": "Right-angle mounting bracket, 6061-T6 aluminum."},
    {"sku": "BRACKET-STL-006", "name": "Steel Mounting Bracket, 1/8in", "description": "Formed steel mounting bracket, 1/8in plate."},
    {"sku": "GASKET-RUB-007", "name": "Rubber Gasket, 2in OD", "description": "Molded rubber gasket, 2in outer diameter."},
    {"sku": "SEAL-RING-008", "name": "Viton O-Ring Seal", "description": "O-ring seal, Viton compound, chemical/heat resistant."},
    {"sku": "PIN-DOWEL-009", "name": "Dowel Pin, 6mm x 20mm", "description": "Precision ground dowel pin, 6mm diameter, 20mm length."},
    {"sku": "SPRING-COMP-010", "name": "Compression Spring, 10mm OD", "description": "Steel compression spring, 10mm outer diameter."},
]

# (supplier name, part sku, lead_time_days, certification_level, unit_price)
# Deliberately overlapping -- every part below is covered by at least two
# suppliers, so "which suppliers can provide part X" / "who else supplies
# this part" have a real answer rather than a list of one.
SUPPLIER_PART_COVERAGE = [
    ("Acme Fasteners", "BOLT-M8-001", 5, CertificationLevel.STANDARD, "0.42"),
    ("Acme Fasteners", "BOLT-M6-002", 5, CertificationLevel.STANDARD, "0.31"),
    ("Acme Fasteners", "WASHER-M8-003", 4, CertificationLevel.STANDARD, "0.06"),
    ("Acme Fasteners", "NUT-M8-004", 4, CertificationLevel.STANDARD, "0.09"),
    ("Acme Fasteners", "PIN-DOWEL-009", 7, CertificationLevel.STANDARD, "0.55"),

    ("Titan Alloys", "BOLT-M8-001", 12, CertificationLevel.ISO_9001, "0.38"),
    ("Titan Alloys", "BRACKET-AL-005", 10, CertificationLevel.ISO_9001, "6.75"),
    ("Titan Alloys", "BRACKET-STL-006", 9, CertificationLevel.ISO_9001, "4.20"),
    ("Titan Alloys", "SPRING-COMP-010", 8, CertificationLevel.ISO_9001, "1.15"),

    ("Precision Aerostructures", "BOLT-M8-001", 18, CertificationLevel.AS_9100, "0.95"),
    ("Precision Aerostructures", "BRACKET-AL-005", 21, CertificationLevel.AS_9100, "14.50"),
    ("Precision Aerostructures", "PIN-DOWEL-009", 15, CertificationLevel.AS_9100, "1.80"),

    ("Lonestar Machining", "BRACKET-STL-006", 6, CertificationLevel.STANDARD, "3.60"),
    ("Lonestar Machining", "GASKET-RUB-007", 5, CertificationLevel.STANDARD, "0.75"),
    ("Lonestar Machining", "SPRING-COMP-010", 6, CertificationLevel.STANDARD, "0.95"),
    ("Lonestar Machining", "SEAL-RING-008", 7, CertificationLevel.STANDARD, "0.40"),

    ("Summit Industrial Supply", "WASHER-M8-003", 3, CertificationLevel.NONE, "0.05"),
    ("Summit Industrial Supply", "NUT-M8-004", 3, CertificationLevel.NONE, "0.07"),
    ("Summit Industrial Supply", "GASKET-RUB-007", 3, CertificationLevel.NONE, "0.60"),
    ("Summit Industrial Supply", "SEAL-RING-008", 3, CertificationLevel.NONE, "0.32"),
    ("Summit Industrial Supply", "BOLT-M6-002", 4, CertificationLevel.NONE, "0.25"),
]

# Each PO's supplier must have SupplierPart coverage for every line's part
# sku above, or this command will fail loudly rather than seed a line
# that couldn't exist in reality.
PURCHASE_ORDERS = [
    {
        "po_number": "PO-2026-1001",
        "supplier": "Acme Fasteners",
        "expected_in_days": 10,
        "lines": [
            {"part_sku": "BOLT-M8-001", "quantity_ordered": 500},
            {"part_sku": "WASHER-M8-003", "quantity_ordered": 500},
            {"part_sku": "NUT-M8-004", "quantity_ordered": 500},
        ],
    },
    {
        "po_number": "PO-2026-1002",
        "supplier": "Titan Alloys",
        "expected_in_days": 14,
        "lines": [
            {"part_sku": "BRACKET-AL-005", "quantity_ordered": 50},
            {"part_sku": "SPRING-COMP-010", "quantity_ordered": 200},
        ],
    },
    {
        "po_number": "PO-2026-1003",
        "supplier": "Lonestar Machining",
        "expected_in_days": 7,
        "lines": [
            {"part_sku": "GASKET-RUB-007", "quantity_ordered": 300},
            {"part_sku": "SEAL-RING-008", "quantity_ordered": 300},
        ],
    },
]


class Command(BaseCommand):
    help = (
        "Seeds a demo dataset: suppliers, parts, overlapping SupplierPart "
        "coverage, and open purchase orders ready to receive against. "
        "Safe to re-run -- existing rows are updated in place, not duplicated."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        suppliers = self._seed_suppliers()
        parts = self._seed_parts()
        self._seed_supplier_parts(suppliers, parts)
        self._seed_purchase_orders(suppliers, parts)
        self.stdout.write(self.style.SUCCESS(
            f"Seed data ready: {len(suppliers)} suppliers, {len(parts)} parts, "
            f"{len(SUPPLIER_PART_COVERAGE)} supplier-part terms, "
            f"{len(PURCHASE_ORDERS)} purchase orders."
        ))

    def _seed_suppliers(self):
        suppliers = {}
        for data in SUPPLIERS:
            supplier, created = Supplier.objects.get_or_create(
                name=data["name"], defaults={"contact_email": data["contact_email"]}
            )
            suppliers[data["name"]] = supplier
            self.stdout.write(f"  {'created' if created else 'exists'}: supplier {supplier.name}")
        return suppliers

    def _seed_parts(self):
        parts = {}
        for data in PARTS:
            part, created = Part.objects.get_or_create(
                sku=data["sku"],
                defaults={"name": data["name"], "description": data["description"]},
            )
            parts[data["sku"]] = part
            self.stdout.write(f"  {'created' if created else 'exists'}: part {part.sku}")
        return parts

    def _seed_supplier_parts(self, suppliers, parts):
        for supplier_name, sku, lead_time_days, cert, price in SUPPLIER_PART_COVERAGE:
            supplier_part, created = SupplierPart.objects.update_or_create(
                supplier=suppliers[supplier_name],
                part=parts[sku],
                defaults={
                    "lead_time_days": lead_time_days,
                    "certification_level": cert,
                    "unit_price": Decimal(price),
                },
            )
            self.stdout.write(f"  {'created' if created else 'updated'}: {supplier_part}")

    def _seed_purchase_orders(self, suppliers, parts):
        today = date.today()
        for po_data in PURCHASE_ORDERS:
            supplier = suppliers[po_data["supplier"]]
            po, created = PurchaseOrder.objects.get_or_create(
                po_number=po_data["po_number"],
                defaults={
                    "supplier": supplier,
                    "expected_date": today + timedelta(days=po_data["expected_in_days"]),
                },
            )
            self.stdout.write(f"  {'created' if created else 'exists'}: purchase order {po.po_number}")

            for line_data in po_data["lines"]:
                supplier_part = SupplierPart.objects.get(
                    supplier=supplier, part=parts[line_data["part_sku"]]
                )
                line, line_created = OrderLine.objects.get_or_create(
                    purchase_order=po,
                    supplier_part=supplier_part,
                    defaults={"quantity_ordered": line_data["quantity_ordered"]},
                )
                self.stdout.write(f"    {'created' if line_created else 'exists'}: line {line}")
