from django.db import migrations, models


def parse_charge_from_label(label: str) -> int:
    import re

    if label == "e(-g)":
        return -1

    suffix_match = re.search(r"\(([^)]*)\)$", label)
    if not suffix_match:
        return 0
    suffix = suffix_match.group(1)

    explicit_match = re.fullmatch(r"([+-])g;([+-]?\d+)", suffix)
    if explicit_match:
        return int(explicit_match.group(2))

    simple_match = re.fullmatch(r"([+-])(\d*)g", suffix)
    if simple_match:
        sign = 1 if simple_match.group(1) == "+" else -1
        magnitude = int(simple_match.group(2) or "1")
        return sign * magnitude

    return 0


def populate_substance_charges(apps, schema_editor):
    table_names = set(schema_editor.connection.introspection.table_names())
    if "substance" not in table_names:
        return

    SubstanceCharge = apps.get_model("ivtanthermo", "SubstanceCharge")

    rows = []
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT id, label FROM substance")
        substance_rows = cursor.fetchall()

    for substance_id, substance_label in substance_rows:
        rows.append(
            SubstanceCharge(
                substance_id=substance_id,
                charge=parse_charge_from_label(substance_label),
                source_label=substance_label,
            )
        )

    if rows:
        SubstanceCharge.objects.bulk_create(rows, batch_size=1000)


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="SubstanceCharge",
            fields=[
                ("substance_id", models.IntegerField(primary_key=True, serialize=False)),
                ("charge", models.SmallIntegerField(db_index=True)),
                ("source_label", models.CharField(max_length=255)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "substance_charge",
                "ordering": ("substance_id",),
            },
        ),
        migrations.RunPython(populate_substance_charges, migrations.RunPython.noop),
    ]
