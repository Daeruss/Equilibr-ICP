from django.urls import path
from .views import ExportCsvView, GraphPageView

app_name = "icp_stat"

urlpatterns = [
    path("", GraphPageView.as_view(), name="graph-page"),
    path("export-csv/", ExportCsvView.as_view(), name="export-csv"),
]
