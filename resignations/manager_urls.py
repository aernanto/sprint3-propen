from django.urls import path

from .manager_views import (
    ManagerResignationDetailView,
    ManagerResignationExportView,
    ManagerResignationListView,
    ManagerResignationStatusUpdateView,
)

urlpatterns = [
    path('', ManagerResignationListView.as_view(), name='manager-resignations-list'),
    path('export/', ManagerResignationExportView.as_view(), name='manager-resignations-export'),
    path('<int:pk>/status/', ManagerResignationStatusUpdateView.as_view(), name='manager-resignations-status'),
    path('<int:pk>/', ManagerResignationDetailView.as_view(), name='manager-resignations-detail'),
]
