from django.urls import path
from . import views

urlpatterns = [
    path(
        "registers/download_period/<uuid:period_id>/<str:export_type>/",
        views.download_period,
        name="download_period",
    ),
]
