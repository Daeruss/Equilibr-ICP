from django.db import models


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
    pressure_mpa = models.FloatField(blank=True, null=True)
    include_condensed = models.BooleanField(default=True)
    include_ions = models.BooleanField(default=False)
    feed_input = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return self.name
