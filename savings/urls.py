from django.urls import path

from savings.views import (
    InitialDepositCreateView,
    SavingsDepositCreateView,
    SavingsOverviewView,
    WithdrawalBalanceView,
    WithdrawalCreateView,
)

urlpatterns = [
    path('overview/', SavingsOverviewView.as_view(), name='savings-overview'),
    path('deposits/pokok/', InitialDepositCreateView.as_view(), name='savings-deposit-pokok'),
    path('deposits/', SavingsDepositCreateView.as_view(), name='savings-deposit'),
    path('withdrawals/balance/', WithdrawalBalanceView.as_view(), name='savings-withdrawal-balance'),
    path('withdrawals/create/', WithdrawalCreateView.as_view(), name='savings-withdrawal-create'),
]
