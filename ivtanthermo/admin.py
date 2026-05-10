from django.contrib import admin
from django.db import models

from . import models as app_models


def _is_composite_pk(model):
    return isinstance(model._meta.pk, models.CompositePrimaryKey)


def _build_list_display(model):
    concrete_fields = [field.name for field in model._meta.concrete_fields]
    return tuple(concrete_fields[:5])


def _build_search_fields(model):
    supported_types = (models.CharField, models.TextField)
    search_fields = []
    preferred_names = ("label", "name", "title", "formula", "symbol", "cas", "version")

    concrete_fields = {field.name: field for field in model._meta.concrete_fields}
    for field_name in preferred_names:
        field = concrete_fields.get(field_name)
        if isinstance(field, supported_types):
            search_fields.append(field_name)

    if search_fields:
        return tuple(search_fields[:3])

    fallback = [
        field.name
        for field in model._meta.concrete_fields
        if isinstance(field, supported_types)
    ]
    return tuple(fallback[:3])


def _build_list_filter(model):
    supported_types = (models.BooleanField, models.DateField, models.DateTimeField)
    filters = [
        field.name
        for field in model._meta.concrete_fields
        if isinstance(field, supported_types)
    ]
    return tuple(filters[:4])


class ReadOnlyAdmin(admin.ModelAdmin):
    list_per_page = 50
    ordering = ("pk",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff

    def get_model_perms(self, request):
        if not self.has_view_permission(request):
            return {}
        return {"view": True}


admin.site.site_header = "Equilibr Admin"
admin.site.site_title = "Equilibr Admin"
admin.site.index_title = "Data browser"


for model in app_models.__dict__.values():
    if not isinstance(model, type):
        continue
    if not issubclass(model, models.Model):
        continue
    if model is models.Model or _is_composite_pk(model):
        continue

    admin_class = type(
        f"{model.__name__}Admin",
        (ReadOnlyAdmin,),
        {
            "list_display": _build_list_display(model),
            "search_fields": _build_search_fields(model),
            "list_filter": _build_list_filter(model),
            "readonly_fields": [field.name for field in model._meta.fields],
        },
    )
    admin.site.register(model, admin_class)
