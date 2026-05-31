from django.urls import path

from savings.staff_views import (
    StaffWithdrawalExportView,
    StaffWithdrawalListView,
    StaffWithdrawalStatusUpdateView,
)

urlpatterns = [
    path('', StaffWithdrawalListView.as_view(), name='staff-withdrawal-list'),
    path('export/', StaffWithdrawalExportView.as_view(), name='staff-withdrawal-export'),
    path('<int:pk>/status/', StaffWithdrawalStatusUpdateView.as_view(), name='staff-withdrawal-status-update'),
]
