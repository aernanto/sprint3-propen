from django.urls import path
from .dashboard_views import ChairmanDashboardView, StaffDashboardView

urlpatterns = [
    path('staff/', StaffDashboardView.as_view()),
    path('chairman/', ChairmanDashboardView.as_view()),
]
