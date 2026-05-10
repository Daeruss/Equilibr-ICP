from django.urls import path

from . import views


urlpatterns = [
    path("", views.equilibrium_calculator, name="equilibrium-calculator"),
]
