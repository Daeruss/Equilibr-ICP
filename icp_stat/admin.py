from django.contrib import admin
from .models import ParsedPoint


@admin.register(ParsedPoint)
class ParsedPointAdmin(admin.ModelAdmin):
    list_display = ("source", "batch_id", "point_index", "x_value", "y_value", "created_at")
    list_filter = ("source", "batch_id")
    search_fields = ("batch_id",)