from django.urls import path
from .chairman_views import ChairmanCashflowView

urlpatterns = [
    path('cashflow/', ChairmanCashflowView.as_view(), name='chairman-cashflow'),
]
