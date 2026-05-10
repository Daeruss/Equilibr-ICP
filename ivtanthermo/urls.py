from django.urls import path

from . import views


urlpatterns = [
    path("", views.substance_list, name="substance-list"),
    path("substance/", views.substance_list, name="substance-list-alt"),
    path("substance/thermo/<int:thermo_id>/", views.thermo_detail, name="thermo-detail"),
]
