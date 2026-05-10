from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("equilibrium", "0005_savedcalculation_result_payload"),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomSubstance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("label", models.CharField(max_length=255, unique=True)),
                ("display_name", models.CharField(blank=True, max_length=255)),
                (
                    "phase",
                    models.CharField(
                        choices=[
                            ("g", "Газ"),
                            ("c", "Конденсированная"),
                            ("l", "Жидкость"),
                            ("cr", "Кристалл"),
                            ("am", "Аморфная"),
                            ("gl", "Стекло"),
                        ],
                        default="g",
                        max_length=16,
                    ),
                ),
                ("element_counts", models.JSONField(default=dict)),
                ("molar_mass", models.FloatField()),
                ("dfh0", models.FloatField(default=0.0)),
                ("tmin", models.FloatField()),
                ("tmax", models.FloatField()),
                ("gibbs_coefficients", models.JSONField(default=list)),
                ("note", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["label"],
            },
        ),
    ]
