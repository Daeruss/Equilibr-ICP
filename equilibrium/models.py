from django.db import models


class CustomSubstance(models.Model):
    PHASE_CHOICES = [
        ("g", "Газ"),
        ("c", "Конденсированная"),
        ("l", "Жидкость"),
        ("cr", "Кристалл"),
        ("am", "Аморфная"),
        ("gl", "Стекло"),
    ]

    label = models.CharField(max_length=255, unique=True)
    display_name = models.CharField(max_length=255, blank=True)
    phase = models.CharField(max_length=16, choices=PHASE_CHOICES, default="g")
    element_counts = models.JSONField(default=dict)
    molar_mass = models.FloatField()
    dfh0 = models.FloatField(default=0.0)
    tmin = models.FloatField()
    tmax = models.FloatField()
    gibbs_coefficients = models.JSONField(default=list)
    note = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["label"]

    def __str__(self) -> str:
        return self.display_name or self.label


class SavedCalculation(models.Model):
    SOURCE_MANUAL = "manual"
    SOURCE_DATABASE = "database"

    SOURCE_CHOICES = [
        (SOURCE_MANUAL, "Manual input"),
        (SOURCE_DATABASE, "Database input"),
    ]

    name = models.CharField(max_length=255)
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES)
    mode = models.CharField(max_length=16)
    example_name = models.CharField(max_length=128, blank=True)
    raw_input = models.TextField(blank=True)
    temperature = models.FloatField(blank=True, null=True)
    temperature_start = models.FloatField(blank=True, null=True)
    temperature_end = models.FloatField(blank=True, null=True)
    temperature_step = models.FloatField(blank=True, null=True)
    temperature_report = models.FloatField(blank=True, null=True)
    pressure_mpa = models.FloatField(blank=True, null=True)
    feed_basis = models.CharField(max_length=16, default="mole")
    include_condensed = models.BooleanField(default=True)
    include_ions = models.BooleanField(default=False)
    feed_input = models.TextField(blank=True)
    result_payload = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return self.name
