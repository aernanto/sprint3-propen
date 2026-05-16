from django.urls import path

from .staff_views import StaffWithdrawalListView, StaffWithdrawalStatusUpdateView

urlpatterns = [
    path('', StaffWithdrawalListView.as_view(), name='staff-withdrawal-list'),
    path('<int:pk>/status/', StaffWithdrawalStatusUpdateView.as_view(), name='staff-withdrawal-status'),
]
