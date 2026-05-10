from django.core.management.base import BaseCommand

from ivtanthermo.charge_utils import parse_charge_from_label
from ivtanthermo.models import Substance, SubstanceCharge


class Command(BaseCommand):
    help = "Synchronize substance_charge table from Substance.label."

    def handle(self, *args, **options):
        existing = {
            row.substance_id: row
            for row in SubstanceCharge.objects.all()
        }

        to_create = []
        to_update = []
        seen_ids = set()

        for substance in Substance.objects.only("id", "label"):
            seen_ids.add(substance.id)
            charge = parse_charge_from_label(substance.label)
            stored = existing.get(substance.id)
            if stored is None:
                to_create.append(
                    SubstanceCharge(
                        substance_id=substance.id,
                        charge=charge,
                        source_label=substance.label,
                    )
                )
                continue
            if stored.charge != charge or stored.source_label != substance.label:
                stored.charge = charge
                stored.source_label = substance.label
                to_update.append(stored)

        stale_ids = [substance_id for substance_id in existing if substance_id not in seen_ids]

        if to_create:
            SubstanceCharge.objects.bulk_create(to_create, batch_size=1000)
        if to_update:
            SubstanceCharge.objects.bulk_update(to_update, ["charge", "source_label"], batch_size=1000)
        if stale_ids:
            SubstanceCharge.objects.filter(substance_id__in=stale_ids).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"substance_charge synchronized: created={len(to_create)}, updated={len(to_update)}, deleted={len(stale_ids)}"
            )
        )
