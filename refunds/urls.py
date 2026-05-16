from django.urls import path

from .views import StaffRefundDetailView, StaffRefundListView, StaffRefundStatusUpdateView

urlpatterns = [
    path('', StaffRefundListView.as_view(), name='staff-refund-list'),
    path('<int:pk>/', StaffRefundDetailView.as_view(), name='staff-refund-detail'),
    path('<int:pk>/status/', StaffRefundStatusUpdateView.as_view(), name='staff-refund-status'),
]
