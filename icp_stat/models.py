from django.db import models


class ParsedPoint(models.Model):
    SOURCE_CHOICES = (
        ("file1", "Файл 1"),
        ("file2", "Файл 2"),
        ("file4", "Файл 4 (обработанные)"),
    )

    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, db_index=True)
    batch_id = models.CharField(max_length=64, default="default", db_index=True)
    temperature = models.CharField(max_length=32, blank=True, default="", db_index=True)
    point_index = models.PositiveIntegerField()
    mass_to_charge = models.FloatField(null=True, blank=True)
    x_value = models.FloatField()
    y_value = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("source", "temperature", "point_index")
        constraints = [
            models.UniqueConstraint(
                fields=["source", "batch_id", "temperature", "point_index"],
                name="uniq_source_batch_temp_point_index",
            )
        ]

    def __str__(self):
        temp = f"@{self.temperature}" if self.temperature else ""
        return f"{self.source}{temp}:{self.point_index} [{self.x_value}, {self.y_value}]"
