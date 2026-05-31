from django.urls import path

from .manager_views import ManagerPendingLoansView, ManagerLoanDetailView, ManagerDashboardView, ManagerLoanStatusUpdateView
from .manager_overdue_views import (
    ManagerOverdueLoansExportView,
    ManagerOverdueLoansView,
    ManagerOverdueLoanStatusView,
    ManagerOverdueLoanWarningView,
)

urlpatterns = [
    path('dashboard/', ManagerDashboardView.as_view(), name='manager-dashboard'),
    path('pending/', ManagerPendingLoansView.as_view(), name='manager-pending-loans'),
    path('<int:pk>/status/', ManagerLoanStatusUpdateView.as_view(), name='manager-loan-status-update'),
    path('<int:pk>/', ManagerLoanDetailView.as_view(), name='manager-loan-detail'),
    path('overdue/', ManagerOverdueLoansView.as_view(), name='manager-overdue-loans'),
    path('overdue/export/', ManagerOverdueLoansExportView.as_view(), name='manager-overdue-loans-export'),
    path('overdue/<int:pk>/status/', ManagerOverdueLoanStatusView.as_view(), name='manager-overdue-loan-status'),
    path('overdue/<int:pk>/warning/', ManagerOverdueLoanWarningView.as_view(), name='manager-overdue-loan-warning'),
]
